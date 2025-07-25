import os
import logging
import subprocess
from pathlib import Path
import tempfile
from zipfile import ZipFile
from datetime import datetime
import re

from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    send_file,
    after_this_request,
)
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
import psycopg2

from get_config import get_config
from database import PostgresqlDatabase
from utils.aws_utils import validate_aws_credentials, check_support_nvidia
from utils.scp import (
    get_instance_ips,
    get_ssh_private_key,
    extract_slp_from_docker,
    rsync_slp_files_to_allocator,
    find_slp_files_in_container,
)

app = Flask(__name__)
auth = HTTPBasicAuth()
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "postgresql://lablink:lablink@localhost:5432/lablink_db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Load the configuration
cfg = get_config()

# Initialize variables
PIN = "123456"
MESSAGE_CHANNEL = cfg.db.message_channel
users = {cfg.app.admin_user: generate_password_hash(cfg.app.admin_password)}
ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
allocator_ip = os.getenv("ALLOCATOR_PUBLIC_IP")
key_name = os.getenv("ALLOCATOR_KEY_NAME")
ENVIRONMENT = os.getenv("ENVIRONMENT", "prod").strip().lower().replace(" ", "-")


# Initialize the database connection
database = PostgresqlDatabase(
    dbname=cfg.db.dbname,
    user=cfg.db.user,
    password=cfg.db.password,
    host=cfg.db.host,
    port=cfg.db.port,
    table_name=cfg.db.table_name,
)

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class vms(db.Model):
    hostname = db.Column(db.String(1024), primary_key=True)
    pin = db.Column(db.String(1024), nullable=True)
    crdcommand = db.Column(db.String(1024), nullable=True)
    useremail = db.Column(db.String(1024), nullable=True)
    inuse = db.Column(db.Boolean, nullable=False, default=False, server_default="false")
    healthy = db.Column(db.String(1024), nullable=True)


@auth.verify_password
def verify_password(username, password):
    """Verify the username and password against the stored users.
    Args:
        username (str): The username to verify.
        password (str): The password to verify.
    Returns:
        str: The username if the credentials are valid, None otherwise.
    """
    if username in users and check_password_hash(users.get(username), password):
        return username


def check_crd_input(crd_command: str) -> bool:
    """Check if the CRD command is valid.

    Args:
        crd_command (string): The CRD command to check.

    Returns:
        bool: True if the command is valid, False otherwise.
    """
    if crd_command is None:
        logger.error("CRD command is None.")
        return False

    elif "--code" not in crd_command:
        logger.error("Invalid CRD command: --code not found.")
        return False

    return True


def notify_participants():
    """Trigger function to notify participant VMs."""
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cursor = conn.cursor()
    cursor.execute("LISTEN vm_updates;")
    conn.commit()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/admin/create")
@auth.login_required
def create_instances():
    return render_template("create-instances.html")


@app.route("/admin")
@auth.login_required
def admin():
    # If credentials are not set, render the admin page without a message
    if not all(
        [
            os.getenv("AWS_ACCESS_KEY_ID"),
            os.getenv("AWS_SECRET_ACCESS_KEY"),
            os.getenv("AWS_SESSION_TOKEN"),
        ]
    ):
        return render_template("admin.html")

    # Check if AWS credentials are set and valid
    is_credentials_valid = validate_aws_credentials()

    # If credentials are set and valid, display the admin dashboard
    if is_credentials_valid:
        message = "AWS credentials are already set and valid."
        return render_template("admin.html", message=message)

    # If credentials are not set or invalid, prompt the user to set them
    else:
        error = (
            "AWS credentials are not set or invalid. Please set your AWS credentials."
        )
        return render_template("admin.html", error=error)


@app.route("/api/admin/set-aws-credentials", methods=["POST"])
@auth.login_required
def set_aws_credentials():
    aws_access_key = request.form.get("aws_access_key_id", "").strip()
    aws_secret_key = request.form.get("aws_secret_access_key", "").strip()
    aws_token = request.form.get("aws_token", "").strip()

    if not aws_access_key or not aws_secret_key:
        return jsonify({"error": "AWS Access Key and Secret Key are required"}), 400

    # also set the environment variables
    os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_key
    os.environ["AWS_SESSION_TOKEN"] = aws_token

    # Check if the AWS credentials are valid
    if not validate_aws_credentials():
        logger.error("Invalid AWS credentials provided.")

        # Remove environment variables if credentials are invalid
        del os.environ["AWS_ACCESS_KEY_ID"]
        del os.environ["AWS_SECRET_ACCESS_KEY"]
        del os.environ["AWS_SESSION_TOKEN"]

        return render_template(
            "admin.html",
            error="Invalid AWS credentials provided. Please check your credentials.",
        )

    # Save the credentials to a file or environment variable
    terraform_dir = Path("terraform")
    credential_file = terraform_dir / "terraform.credentials.tfvars"

    with credential_file.open("w") as f:
        f.write(f'aws_access_key = "{aws_access_key}"\n')
        f.write(f'aws_secret_key = "{aws_secret_key}"\n')
        f.write(f'aws_session_token = "{aws_token}"\n')

    return render_template("admin.html", message="AWS credentials set successfully.")


@app.route("/admin/instances")
@auth.login_required
def view_instances():
    instances = vms.query.all()
    return render_template("instances.html", instances=instances)


@app.route("/admin/instances/delete")
@auth.login_required
def delete_instances():
    instances = vms.query.all()
    return render_template("delete-instances.html", instances=instances)


@app.route("/api/request_vm", methods=["POST"])
def submit_vm_details():
    try:
        data = request.form  # If you're sending JSON, use request.json instead
        email = data.get("email")
        crd_command = data.get("crd_command")

        # If email or crd_command is not provided, return an error
        if not email or not crd_command:
            return render_template(
                "index.html", error="Email and CRD command are required."
            )

        # Check if the CRD command is valid
        if not check_crd_input(crd_command=crd_command):
            logger.error("Invalid CRD command: --code not found.")
            return render_template(
                "index.html",
                error="Invalid CRD command received. Please ask your instructor for help.",
            )

        # Check if there are any available VMs
        if len(database.get_unassigned_vms()) == 0:
            logger.error("No available VMs found.")
            return render_template(
                "index.html",
                error="No available VMs. Please try again later. Please ask your instructor for help",
            )

        # Assign the VM
        database.assign_vm(email=email, crd_command=crd_command, pin=PIN)

        # Display success message
        assigned_vm = database.get_vm_details(email=email)
        return render_template("success.html", host=assigned_vm[0], pin=assigned_vm[1])
    except Exception as e:
        logger.error(f"Error in submit_vm_details: {e}")
        return render_template(
            "index.html",
            error="An unexpected error occurred while processing your request. Please ask your instructor for help.",
        )


@app.route("/api/launch", methods=["POST"])
@auth.login_required
def launch():
    num_vms = int(request.form.get("num_vms"))
    terraform_dir = Path("terraform")
    runtime_file = terraform_dir / "terraform.runtime.tfvars"

    # Check if the credentials file exists
    credentials_file = terraform_dir / "terraform.credentials.tfvars"
    if not credentials_file.exists():
        logger.error(
            "AWS credentials file not found. Please set AWS credentials first."
        )
        return render_template(
            "dashboard.html",
            credential_error="AWS credentials file not found.",
        )

    try:
        # Calculate the number of VMs to launch
        total_vms = num_vms + database.get_row_count()

        # Init Terraform (optional if already initialized)
        subprocess.run(["terraform", "init"], cwd=terraform_dir, check=True)

        logger.debug(f"Machine type: {cfg.machine.machine_type}")
        logger.debug(f"Image name: {cfg.machine.image}")
        logger.debug(f"client VM AMI ID: {cfg.machine.ami_id}")
        logger.debug(f"GitHub repository: {cfg.machine.repository}")
        logger.debug(f"Subject Software: {cfg.machine.software}")

        if not allocator_ip or not key_name:
            logger.error("Missing allocator outputs.")
            return render_template(
                "dashboard.html", error="Allocator outputs not found."
            )

        logger.debug(f"Allocator IP: {allocator_ip}")
        logger.debug(f"Key Name: {key_name}")
        logger.debug(f"ENVIRONMENT: {ENVIRONMENT}")

        # Check if GPU is supported
        gpu_support_bool = check_support_nvidia(machine_type=cfg.machine.machine_type)

        # Process GPU support so that it can be used in the runtime file
        if gpu_support_bool:
            logger.info("GPU support is enabled for the machine type.")
            gpu_support = "true"
        else:
            logger.info("GPU support is not enabled for the machine type.")
            gpu_support = "false"

        # Write the runtime variables to the file
        with runtime_file.open("w") as f:
            f.write(f'allocator_ip = "{allocator_ip}"\n')
            f.write(f'machine_type = "{cfg.machine.machine_type}"\n')
            f.write(f'image_name = "{cfg.machine.image}"\n')
            f.write(f'repository = "{cfg.machine.repository}"\n')
            f.write(f'client_ami_id = "{cfg.machine.ami_id}"\n')
            f.write(f'subject_software = "{cfg.machine.software}"\n')
            f.write(f'resource_suffix = "{ENVIRONMENT}"\n')
            f.write(f'gpu_support = "{gpu_support}"\n')

        # Apply with the new number of instances
        apply_cmd = [
            "terraform",
            "apply",
            "-auto-approve",
            "-var-file=terraform.runtime.tfvars",
            "-var-file=terraform.credentials.tfvars",
            f"-var=instance_count={total_vms}",
        ]

        logger.debug(f"Running command: {' '.join(apply_cmd)}")

        # Run the Terraform apply command
        result = subprocess.run(
            apply_cmd, cwd=terraform_dir, check=True, capture_output=True, text=True
        )

        # Format the output to remove ANSI escape codes
        clean_output = ANSI_ESCAPE.sub("", result.stdout)

        return render_template("dashboard.html", output=clean_output)

    except subprocess.CalledProcessError as e:
        logger.error(f"Error during Terraform apply: {e}")
        error_output = e.stderr or e.stdout
        clean_output = ANSI_ESCAPE.sub("", error_output or "")
        return render_template("dashboard.html", error=clean_output)


@app.route("/destroy", methods=["POST"])
@auth.login_required
def destroy():
    terraform_dir = Path("terraform")
    try:
        # Destroy Terraform resources
        apply_cmd = [
            "terraform",
            "destroy",
            "-auto-approve",
            "-var-file=terraform.runtime.tfvars",
            "-var-file=terraform.credentials.tfvars",
        ]
        result = subprocess.run(
            apply_cmd, cwd=terraform_dir, check=True, capture_output=True, text=True
        )

        # Clear the database
        logger.debug("Clearing the database...")
        database.clear_database()
        logger.debug("Database cleared successfully.")

        # Format the output to remove ANSI escape codes
        clean_output = ANSI_ESCAPE.sub("", result.stdout)

        return render_template("dashboard.html", output=clean_output)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error during Terraform destroy: {e}")
        error_output = e.stderr or e.stdout
        clean_output = ANSI_ESCAPE.sub("", error_output or "")
        return render_template("dashboard.html", error=clean_output)


@app.route("/vm_startup", methods=["POST"])
def vm_startup():
    data = request.get_json()
    hostname = data.get("hostname")

    if not hostname:
        return jsonify({"error": "Hostname are required."}), 400

    # Add to the database
    logger.debug(f"Adding VM {hostname} to database...")
    database.insert_vm(hostname=hostname)
    result = database.listen_for_notifications(
        channel=MESSAGE_CHANNEL, target_hostname=hostname
    )

    return jsonify(result), 200


@app.route("/api/scp-client", methods=["GET"])
@auth.login_required
def download_all_data():
    if database.get_row_count() == 0:
        logger.warning("No VMs found in the database.")
        return jsonify({"error": "No VMs found in the database."}), 404
    try:
        instance_ips = get_instance_ips(terraform_dir="terraform")
        key_path = get_ssh_private_key(terraform_dir="terraform")
        empty_data = True

        with tempfile.TemporaryDirectory() as temp_dir:
            for i, ip in enumerate(instance_ips):
                # Make temporary directory for each VM
                logger.debug(f"Downloading data from VM {i + 1} at {ip}...")
                vm_dir = Path(temp_dir) / f"vm_{i + 1}"
                vm_dir.mkdir(parents=True, exist_ok=True)

                logger.info(f"Extracting .slp files from container on {ip}...")

                # Find slp files from the Docker container
                slp_files = find_slp_files_in_container(ip=ip, key_path=key_path)

                # If no .slp files are found, log a warning and continue to the next VM
                if len(slp_files) == 0:
                    logger.warning(f"No .slp files found in container on {ip}.")
                    continue
                else:
                    logger.debug(
                        f"Found {len(slp_files)} .slp files in container on {ip}."
                    )
                    # Extract .slp files from the Docker container
                    extract_slp_from_docker(
                        ip=ip,
                        key_path=key_path,
                        slp_files=slp_files,
                    )
                    empty_data = False
                logger.info(f"Copying .slp files from {ip} to {vm_dir}...")

                # Copy the extracted .slp files to the allocator container's local directory
                rsync_slp_files_to_allocator(
                    ip=ip,
                    key_path=key_path,
                    local_dir=vm_dir.as_posix(),
                )

            if empty_data:
                logger.warning("No .slp files found in any VMs.")
                return jsonify({"error": "No .slp files found in any VMs."}), 404

            logger.info(f"All .slp files copied to {temp_dir}.")

            # Create a zip file of the downloaded data with a timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_file = Path(tempfile.gettempdir()) / f"lablink_data{timestamp}.zip"

            with ZipFile(zip_file, "w") as archive:
                for vm_dir in Path(temp_dir).iterdir():
                    if vm_dir.is_dir():
                        logger.debug(f"Zipping data for VM: {vm_dir.name}")
                        for slp_file in vm_dir.rglob("*.slp"):
                            logger.debug(f"Adding {slp_file.name} to zip archive.")
                            # Add with relative path inside zip
                            archive.write(
                                slp_file, arcname=slp_file.relative_to(temp_dir)
                            )
            logger.debug("All data downloaded and zipped successfully.")

            # Send the zip file as a response and remove it after the request
            @after_this_request
            def remove_zip_file(response):
                try:
                    os.remove(zip_file)
                    logger.debug(f"Removed zip file: {zip_file}")
                except Exception as e:
                    logger.error(f"Error removing zip file: {e}")
                return response

            return send_file(zip_file, as_attachment=True)

    except subprocess.CalledProcessError as e:
        logger.error(f"Error downloading data: {e}")
        return (
            jsonify({"error": "An error occurred while downloading data from VMs."}),
            500,
        )


@app.route("/api/unassigned_vms_count", methods=["GET"])
def get_unassigned_instance_counts():
    """Get the counts of all instance types."""
    instance_counts = len(database.get_unassigned_vms())
    return jsonify(count=instance_counts), 200


@app.route("/api/update_inuse_status", methods=["POST"])
def update_inuse_status():
    """Update the in-use status of a VM."""
    data = request.get_json()
    hostname = data.get("hostname")
    in_use = data.get("status")

    logger.debug(f"Updating in-use status for {hostname} to {in_use}")

    if not hostname:
        return jsonify({"error": "Hostname is required."}), 400

    try:
        database.update_vm_in_use(hostname=hostname, in_use=in_use)
        return jsonify({"message": "In-use status updated successfully."}), 200
    except Exception as e:
        logger.error(f"Error updating in-use status: {e}")
        return jsonify({"error": "Failed to update in-use status."}), 500


@app.route("/api/gpu_health", methods=["POST"])
def update_gpu_health():
    """Check the health of the GPU."""
    data = request.get_json()
    gpu_status = data.get("gpu_status")
    hostname = data.get("hostname")
    if gpu_status is None:
        return jsonify({"error": "GPU status is required."}), 400

    try:
        database.update_health(hostname=hostname, healthy=gpu_status)
        logger.info(f"Updated GPU health status for {hostname} to {gpu_status}")
        return jsonify({"message": "GPU health status updated successfully."}), 200
    except Exception as e:
        logger.error(f"Error updating GPU health status: {e}")
        return jsonify({"error": "Failed to update GPU health status."}), 500


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000, threaded=True)
