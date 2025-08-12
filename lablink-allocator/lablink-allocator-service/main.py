import os
import logging
import subprocess
from pathlib import Path
import tempfile
from zipfile import ZipFile
from datetime import datetime
import re
import base64

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
    extract_slp_from_docker,
    rsync_slp_files_to_allocator,
    find_slp_files_in_container,
)
from utils.terraform_utils import (
    get_instance_ips,
    get_ssh_private_key,
    get_instance_names,
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
cloud_init_output_log_group = os.getenv("CLOUD_INIT_LOG_GROUP")


# Initialize the database connection
database = None


def init_database():
    """Initialize the database connection."""
    global database
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
    status = db.Column(db.String(1024), nullable=True)
    logs = db.Column(db.Text, nullable=True)


@auth.verify_password
def verify_password(username, password):
    """Verify the username and password against the stored users.
    Args:
        username (str): The username to verify.
        password (str): The password to verify.
    Returns:
        str: The username if the credentials are valid, None otherwise.
    """
    logger.debug(f"Received auth: {username}, {password}")
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
        ]
    ):
        return render_template("admin.html")

    # Check if AWS credentials are set and valid
    credential_response = validate_aws_credentials()
    logger.debug(f"Credential response: {credential_response}")

    # Check if the credentials are valid
    is_credentials_valid = credential_response.get("valid", False)

    # If credentials are set and valid, display the admin dashboard
    if is_credentials_valid:
        message = "AWS credentials are already set and valid."
        return render_template("admin.html", message=message)

    # If credentials are not set or invalid, prompt the user to set them
    else:
        error = credential_response.get(
            "message", "Invalid AWS credentials. Please set them."
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
    credentials_response = validate_aws_credentials()
    is_credentials_valid = credentials_response.get("valid", False)
    if not is_credentials_valid:
        logger.error(
            "Invalid AWS credentials provided. Removing them from environment variables."
        )

        # Remove environment variables if credentials are invalid
        del os.environ["AWS_ACCESS_KEY_ID"]
        del os.environ["AWS_SECRET_ACCESS_KEY"]
        del os.environ["AWS_SESSION_TOKEN"]

        error = credentials_response.get(
            "message",
            "Invalid AWS credentials provided. Please check your credentials.",
        )

        return render_template(
            "admin.html",
            error=error,
        )

    return render_template("admin.html", message="AWS credentials set successfully.")


@app.route("/admin/instances")
@auth.login_required
def view_instances():
    instances = vms.query.all()
    return render_template("instances.html", instances=instances)


@app.route("/admin/instances/delete")
@auth.login_required
def delete_instances():
    return render_template("delete-instances.html")


@app.route("/api/request_vm", methods=["POST"])
def submit_vm_details():
    try:
        data = request.form
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

    try:
        # Calculate the number of VMs to launch
        total_vms = num_vms + database.get_row_count()

        logger.debug(f"Machine type: {cfg.machine.machine_type}")
        logger.debug(f"Image name: {cfg.machine.image}")
        logger.debug(f"client VM AMI ID: {cfg.machine.ami_id}")
        logger.debug(f"GitHub repository: {cfg.machine.repository}")
        logger.debug(f"Subject Software: {cfg.machine.software}")
        logger.debug(f"Region: {cfg.app.region}")
        logger.debug(f"Allocator IP: {allocator_ip}")
        logger.debug(f"Cloud Init Output Log Group: {cloud_init_output_log_group}")

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

        names = [
            f"lablink-client-{ENVIRONMENT}-{database.get_row_count()+i+1}"
            for i in range(num_vms)
        ]

        for n in names:
            if not database.get_vm_by_hostname(n):
                logger.debug(f"Inserting VM: {n}")
                database.insert_vm(hostname=n)

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
            f.write(f'cloud_init_output_log_group = "{cloud_init_output_log_group}"\n')
            f.write(f'region = "{cfg.app.region}"\n')

        # Apply with the new number of instances
        apply_cmd = [
            "terraform",
            "apply",
            "-auto-approve",
            "-var-file=terraform.runtime.tfvars",
            f"-var=instance_count={total_vms}",
        ]

        logger.debug(f"Running command: {' '.join(apply_cmd)}")

        # Run the Terraform apply command
        result = subprocess.run(
            apply_cmd, cwd=terraform_dir, check=True, capture_output=True, text=True
        )

        # Format the output to remove ANSI escape codes
        clean_output = ANSI_ESCAPE.sub("", result.stdout)

        # Insert the new VMs into the database
        logger.debug("Inserting new VMs into the database...")
        instance_names = get_instance_names(terraform_dir="terraform")
        for name in instance_names:
            # Check if the VM already exists in the database
            if not database.get_vm_by_hostname(name):
                logger.debug(f"Inserting VM: {name}")
                database.insert_vm(hostname=name)

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

        return render_template("delete-dashboard.html", output=clean_output)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error during Terraform destroy: {e}")
        error_output = e.stderr or e.stdout
        clean_output = ANSI_ESCAPE.sub("", error_output or "")
        return render_template("delete-dashboard.html", error=clean_output)


@app.route("/vm_startup", methods=["POST"])
def vm_startup():
    data = request.get_json()
    hostname = data.get("hostname")

    if not hostname:
        return jsonify({"error": "Hostname is required."}), 400

    # Check if the VM exists in the database
    vm = database.get_vm_by_hostname(hostname)
    if not vm:
        return jsonify({"error": "VM not found."}), 404

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
    if gpu_status is None or hostname is None:
        return jsonify({"error": "GPU status and hostname are required."}), 400

    try:
        database.update_health(hostname=hostname, healthy=gpu_status)
        logger.info(f"Updated GPU health status for {hostname} to {gpu_status}")
        return jsonify({"message": "GPU health status updated successfully."}), 200
    except Exception as e:
        logger.error(f"Error updating GPU health status: {e}")
        return jsonify({"error": "Failed to update GPU health status."}), 500


@app.route("/api/vm-status/", methods=["POST"])
def update_vm_status():
    try:
        data = request.get_json()
        hostname = data.get("hostname")
        status = data.get("status")

        if not hostname or status is None:
            return jsonify({"error": "Hostname and status are required."}), 400

        database.update_vm_status(hostname=hostname, status=status)

        return jsonify({"message": "VM status updated successfully."}), 200
    except Exception as e:
        logger.error(f"Error updating VM status: {e}")
        return jsonify({"error": "Failed to update VM status."}), 500


@app.route("/api/vm-status/<hostname>", methods=["GET"])
def get_vm_status(hostname):
    try:
        status = database.get_status_by_hostname(hostname=hostname)
        if status is None:
            return jsonify({"error": "VM not found."}), 404

        return jsonify({"hostname": hostname, "status": status}), 200
    except Exception as e:
        logger.error(f"Error getting VM status: {e}")
        return jsonify({"error": "Failed to get VM status."}), 500


@app.route("/api/vm-status", methods=["GET"])
def get_all_vm_status():
    try:
        vm_status = database.get_all_vm_status()
        if not vm_status:
            return jsonify({"error": "No VM status updates available."}), 404

        return jsonify(vm_status), 200
    except Exception as e:
        logger.error(f"Error getting all VM status: {e}")
        return jsonify({"error": "Failed to get VM status."}), 500


@app.route("/api/vm-logs", methods=["POST"])
def receive_vm_logs():
    try:
        data = request.get_json()
        log_group = data.get("log_group")
        log_stream = data.get("log_stream")
        messages = data.get("messages", [])

        if not log_group or not log_stream or not messages:
            return (
                jsonify({"error": "Log group, stream, and messages are required."}),
                400,
            )

        # Check if the VM exists in the database
        if not database.vm_exists(log_stream):
            logger.error(f"VM with log stream {log_stream} does not exist.")
            return jsonify({"error": "VM not found."}), 404

        # Process the logs (e.g., save to a file, database, etc.)
        logger.info(
            f"Received logs for {log_group}/{log_stream}: {len(messages)} messages"
        )

        # Save the logs to the database
        new_logs = "\n".join(messages)
        vm_log = database.get_vm_logs(hostname=log_stream)
        if vm_log is not None:
            vm_log += "\n" + new_logs
        else:
            vm_log = new_logs
        database.save_logs_by_hostname(hostname=log_stream, logs=vm_log)

        return jsonify({"message": "Logs received successfully."}), 200
    except Exception as e:
        logger.error(f"Error receiving VM logs: {e}")
        return jsonify({"error": "Failed to receive VM logs."}), 500


@app.route("/api/vm-logs/<hostname>", methods=["GET"])
def get_vm_logs_api(hostname):
    try:
        vm = database.get_vm_by_hostname(hostname=hostname)
        logger.debug(f"Fetching logs for VM: {hostname}: {vm}")

        # Check if the VM exists
        if vm is None:
            logger.error(f"VM with hostname {hostname} not found.")
            return jsonify({"error": "VM not found."}), 404

        # If the logs are empty but the vm is initializing, return a 503 status
        logs = database.get_vm_logs(hostname=hostname)
        if logs is None and vm.status == "initializing":
            return jsonify({"error": "VM is installing CloudWatch agent."}), 503

        return jsonify({"hostname": hostname, "logs": logs}), 200
    except Exception as e:
        logger.error(f"Error getting VM logs: {e}")
        return jsonify({"error": "Failed to get VM logs."}), 500


@app.route("/admin/logs/<hostname>", methods=["GET"])
@auth.login_required
def get_vm_logs(hostname):
    """Get the logs for a specific VM."""
    logger.debug(f"Fetching logs for VM: {hostname}")
    return render_template("instance-logs.html", hostname=hostname)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        init_database()

    # Terraform initialization
    terraform_dir = Path("terraform")
    if not (terraform_dir / "terraform.runtime.tfvars").exists():
        logger.info("Initializing Terraform...")
        subprocess.run(["terraform", "init"], cwd=terraform_dir, check=True)
    app.run(host="0.0.0.0", port=5000, threaded=True)
