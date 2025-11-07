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

from lablink_allocator_service.get_config import get_config
from lablink_allocator_service.database import PostgresqlDatabase
from lablink_allocator_service.conf.structured_config import DNSConfig
from lablink_allocator_service.utils.aws_utils import (
    check_support_nvidia,
    upload_to_s3,
)
from lablink_allocator_service.utils.config_helpers import get_allocator_url
from lablink_allocator_service.utils.scp import (
    find_files_in_container,
    extract_files_from_docker,
    rsync_files_to_allocator,
)
from lablink_allocator_service.utils.terraform_utils import (
    get_instance_ips,
    get_ssh_private_key,
    get_instance_timings,
)

app = Flask(__name__)
auth = HTTPBasicAuth()

# Define the terraform directory relative to this file (now inside the package)
TERRAFORM_DIR = (Path(__file__).parent / "terraform").resolve()

# Load the configuration
cfg = get_config()

db_uri = f"postgresql://{cfg.db.user}:{cfg.db.password}@{cfg.db.host}:{cfg.db.port}/{cfg.db.dbname}"
os.environ["DATABASE_URL"] = db_uri
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", db_uri)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

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


def generate_dns_name(dns_config: DNSConfig, environment: str) -> str:
    """Generate DNS name based on configuration and environment.

    Args:
        dns_config: DNSConfig object from configuration
        environment: Current environment (prod, test, dev, etc.)

    Returns:
        str: Generated DNS name or empty string if DNS is disabled
    """
    if not dns_config.enabled or not dns_config.domain:
        return ""

    if dns_config.pattern == "auto":
        # prod: {app_name}.{domain}, others: {env}.{app_name}.{domain}
        if environment == "prod":
            return f"{dns_config.app_name}.{dns_config.domain}"
        else:
            return f"{environment}.{dns_config.app_name}.{dns_config.domain}"
    elif dns_config.pattern == "app-only":
        # Always use {app_name}.{domain}
        return f"{dns_config.app_name}.{dns_config.domain}"
    elif dns_config.pattern == "custom":
        # Use custom subdomain
        if dns_config.custom_subdomain:
            return dns_config.custom_subdomain
        else:
            logger.warning(
                "DNS pattern is 'custom' but custom_subdomain is empty. Using IP only."
            )
            return ""
    else:
        logger.warning(f"Unknown DNS pattern '{dns_config.pattern}'. Using IP only.")
        return ""


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
        message_channel=cfg.db.message_channel,
    )


# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


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
    return render_template("admin.html")


@app.route("/admin/instances")
@auth.login_required
def view_instances():
    instances = database.get_all_vms()
    return render_template("instances.html", instances=instances)


@app.route("/admin/instances/delete")
@auth.login_required
def delete_instances():
    return render_template("delete-instances.html", extension=cfg.machine.extension)


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
                error="Invalid CRD command received. "
                "Please ask your instructor for help.",
            )

        # Check if there are any available VMs
        if len(database.get_unassigned_vms()) == 0:
            logger.error("No available VMs found.")
            return render_template(
                "index.html",
                error="No available VMs. Please try again later. Please ask your "
                "instructor for help",
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
            error="An unexpected error occurred while processing your request. "
            "Please ask your instructor for help.",
        )


@app.route("/api/launch", methods=["POST"])
@auth.login_required
def launch():
    # Get and validate num_vms input
    try:
        num_vms_str = request.form.get("num_vms")
        if not num_vms_str:
            return render_template("dashboard.html", error="Number of VMs is required.")
        num_vms = int(num_vms_str)
        if num_vms <= 0:
            return render_template(
                "dashboard.html", error="Number of VMs must be greater than 0."
            )
    except ValueError:
        return render_template(
            "dashboard.html",
            error="Invalid number of VMs. Please enter a valid integer.",
        )

    runtime_file = TERRAFORM_DIR / "terraform.runtime.tfvars"

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

        # Generate allocator URL based on DNS and SSL configuration
        allocator_url, protocol = get_allocator_url(cfg, allocator_ip)
        logger.info(f"Using allocator URL: {allocator_url} (protocol: {protocol})")

        # Write the runtime variables to the file
        with runtime_file.open("w") as f:
            f.write(f'allocator_ip = "{allocator_ip}"\n')
            f.write(f'allocator_url = "{allocator_url}"\n')
            f.write(f'machine_type = "{cfg.machine.machine_type}"\n')
            f.write(f'image_name = "{cfg.machine.image}"\n')
            f.write(f'repository = "{cfg.machine.repository}"\n')
            f.write(f'client_ami_id = "{cfg.machine.ami_id}"\n')
            f.write(f'subject_software = "{cfg.machine.software}"\n')
            f.write(f'resource_suffix = "{ENVIRONMENT}"\n')
            f.write(f'gpu_support = "{gpu_support}"\n')
            f.write(f'cloud_init_output_log_group = "{cloud_init_output_log_group}"\n')
            f.write(f'region = "{cfg.app.region}"\n')
            f.write(f'startup_on_error = "{cfg.startup_script.on_error}"\n')

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
            apply_cmd, cwd=TERRAFORM_DIR, check=True, capture_output=True, text=True
        )

        # Format the output to remove ANSI escape codes
        clean_output = ANSI_ESCAPE.sub("", result.stdout)

        # Upload the runtime file to S3
        logger.debug(f"Uploading runtime file to S3 bucket: {cfg.bucket_name}...")
        upload_to_s3(
            local_path=runtime_file,
            env=ENVIRONMENT,
            bucket_name=cfg.bucket_name,
            region=cfg.app.region,
        )

        # Store timing outputs in the database
        timing_data = get_instance_timings(terraform_dir=TERRAFORM_DIR)
        logger.debug(f"Timing data: {timing_data}")

        for hostname, times in timing_data.items():
            start_time = datetime.fromisoformat(
                times["start_time"].replace("Z", "+00:00")
            )
            end_time = datetime.fromisoformat(times["end_time"].replace("Z", "+00:00"))
            database.upsert_time_for_terraform_apply(
                hostname=hostname,
                per_instance_seconds=float(times["seconds"]),
                per_instance_start_time=start_time,
                per_instance_end_time=end_time,
            )

        return render_template("dashboard.html", output=clean_output)

    except subprocess.CalledProcessError as e:
        logger.error(f"Error during Terraform apply: {e}")
        error_output = e.stderr or e.stdout
        clean_output = ANSI_ESCAPE.sub("", error_output or "")
        return render_template("dashboard.html", error=clean_output)


@app.route("/destroy", methods=["POST"])
@auth.login_required
def destroy():
    try:
        # Destroy Terraform resources
        apply_cmd = [
            "terraform",
            "destroy",
            "-auto-approve",
            "-var-file=terraform.runtime.tfvars",
        ]
        result = subprocess.run(
            apply_cmd, cwd=TERRAFORM_DIR, check=True, capture_output=True, text=True
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
        instance_ips = get_instance_ips(terraform_dir=TERRAFORM_DIR)
        key_path = get_ssh_private_key(terraform_dir=TERRAFORM_DIR)
        empty_data = True

        with tempfile.TemporaryDirectory() as temp_dir:
            for i, ip in enumerate(instance_ips):
                # Make temporary directory for each VM
                logger.debug(f"Downloading data from VM {i + 1} at {ip}...")
                vm_dir = Path(temp_dir) / f"vm_{i + 1}"
                vm_dir.mkdir(parents=True, exist_ok=True)

                logger.info(
                    f"Extracting {cfg.machine.extension} files "
                    f"from container on {ip}..."
                )

                # Find files from the Docker container
                files = find_files_in_container(
                    ip=ip, key_path=key_path, extension=cfg.machine.extension
                )

                # If no files are found, log a warning and continue to the next VM
                if len(files) == 0:
                    logger.warning(
                        f"No {cfg.machine.extension} files found in container on {ip}."
                    )
                    continue
                else:
                    logger.debug(
                        f"Found {len(files)} {cfg.machine.extension} "
                        f"files in container on {ip}."
                    )
                    # Extract files from the Docker container
                    extract_files_from_docker(
                        ip=ip,
                        key_path=key_path,
                        files=files,
                    )
                    empty_data = False
                logger.info(
                    f"Copying {cfg.machine.extension} files from {ip} to {vm_dir}..."
                )

                # Copy the extracted files to the allocator container's local
                rsync_files_to_allocator(
                    ip=ip,
                    key_path=key_path,
                    local_dir=vm_dir.as_posix(),
                    extension=cfg.machine.extension,
                )

            if empty_data:
                logger.warning(f"No {cfg.machine.extension} files found in any VMs.")
                return (
                    jsonify(
                        {"error": f"No {cfg.machine.extension} files found in any VMs."}
                    ),
                    404,
                )

            logger.info(f"All files copied to {temp_dir}.")

            # Create a zip file of the downloaded data with a timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_file = Path(tempfile.gettempdir()) / f"lablink_data{timestamp}.zip"

            with ZipFile(zip_file, "w") as archive:
                for vm_dir in Path(temp_dir).iterdir():
                    if vm_dir.is_dir():
                        logger.debug(f"Zipping data for VM: {vm_dir.name}")
                        for file in vm_dir.rglob(f"*.{cfg.machine.extension}"):
                            logger.debug(f"Adding {file.name} to zip archive.")
                            # Add with relative path inside zip
                            archive.write(file, arcname=file.relative_to(temp_dir))
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


@app.route("/api/vm-status", methods=["POST"])
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
            return jsonify({"error": "No VMs found."}), 404

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

        return jsonify({"message": "VM logs posted successfully."}), 200
    except Exception as e:
        logger.error(f"Error receiving VM logs: {e}")
        return jsonify({"error": "Failed to post VM logs."}), 500


@app.route("/api/vm-logs/<hostname>", methods=["GET"])
def get_vm_logs_by_hostname(hostname):
    try:
        vm = database.get_vm_by_hostname(hostname=hostname)
        logger.debug(f"Fetching logs for VM: {hostname}: {vm}")

        # Check if the VM exists
        if vm is None:
            logger.error(f"VM with hostname {hostname} not found.")
            return jsonify({"error": "VM not found."}), 404

        # If the logs are empty but the vm is initializing, return a 503 status
        logs = database.get_vm_logs(hostname=hostname)
        status = vm.get("status")
        if logs is None and status == "initializing":
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
    if not database.vm_exists(hostname=hostname):
        logger.error(f"VM with hostname {hostname} not found.")
        return jsonify({"error": "VM not found."}), 404
    return render_template("instance-logs.html", hostname=hostname)


@app.route("/api/vm-metrics/<hostname>", methods=["POST"])
def receive_vm_metrics(hostname):
    """Receive and store VM Cloud init metrics."""
    try:
        data = request.get_json()

        if not database.vm_exists(hostname=hostname):
            logger.error(f"VM with hostname {hostname} does not exist.")
            return jsonify({"error": "VM not found."}), 404

        # Update the VM metrics in the database
        database.update_vm_metrics(hostname=hostname, metrics=data)

        # Calculate the total startup time
        database.calculate_total_startup_time(hostname=hostname)

        logger.info(f"Received metrics for {hostname}: {data}")
        return jsonify({"message": "VM metrics posted successfully."}), 200

    except Exception as e:
        logger.error(f"Error receiving VM metrics: {e}")
        return jsonify({"error": "Failed to post VM metrics."}), 500


def main():
    """Main entry point for the allocator service."""
    with app.app_context():
        db.create_all()
        init_database()

    # Terraform initialization
    if not (TERRAFORM_DIR / "terraform.runtime.tfvars").exists():
        logger.info("Initializing Terraform...")
        if ENVIRONMENT not in ["prod", "test", "ci-test"]:
            (TERRAFORM_DIR / "backend.tf").unlink(missing_ok=True)
            subprocess.run(
                ["terraform", "init"],
                cwd=TERRAFORM_DIR,
                check=True,
            )
        else:
            # Use bucket_name from config for client VM terraform state
            default_bucket = "tf-state-lablink-allocator-bucket"
            bucket_name = (
                cfg.bucket_name if hasattr(cfg, "bucket_name") else default_bucket
            )
            logger.info(f"Initializing Terraform with S3 backend: {bucket_name}")
            subprocess.run(
                [
                    "terraform",
                    "init",
                    f"-backend-config=backend-client-{ENVIRONMENT}.hcl",
                    f"-backend-config=bucket={bucket_name}",
                    f"-backend-config=region={cfg.app.region}",
                ],
                cwd=TERRAFORM_DIR,
                check=True,
            )

    app.run(host="0.0.0.0", port=5000, threaded=True)


if __name__ == "__main__":
    main()
