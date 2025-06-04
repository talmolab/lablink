import os
import logging
import subprocess

from flask import Flask, request, jsonify, render_template
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
import psycopg2
import requests

from get_cofig import get_config
from database import PostgresqlDatabase
from utils.available_instances import get_all_instance_types

app = Flask(__name__)
auth = HTTPBasicAuth()
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "postgresql://lablink:lablink@localhost:5432/lablink_db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Load the configuration
cfg = get_config()

# Check if the machine type is valid
valid_types = get_all_instance_types()
if cfg.machine.machine_type not in valid_types:
    raise ValueError(
        f"Invalid machine type '{cfg.machine.machine_type}'. "
        f"Available types: {', '.join(valid_types)}"
    )

# Initialize variables
PIN = "123456"
MESSAGE_CHANNEL = cfg.db.message_channel
users = {cfg.app.admin_user: generate_password_hash(cfg.app.admin_password)}

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


@app.route("/api/admin/set-aws-credentials", methods=["POST"])
@auth.login_required
def set_aws_credentials():
    aws_access_key = request.form.get("aws_access_key_id", "").strip()
    aws_secret_key = request.form.get("aws_secret_access_key", "").strip()
    aws_token = request.form.get("aws_token", "").strip()

    if not aws_access_key or not aws_secret_key:
        return jsonify({"error": "AWS Access Key and Secret Key are required"}), 400

    # Save the credentials to a file or environment variable
    terraform_dir = "terraform/"

    with open(os.path.join(terraform_dir, "terraform.credentials.tfvars"), "w") as f:
        f.write(f'aws_access_key = "{aws_access_key}"\n')
        f.write(f'aws_secret_key = "{aws_secret_key}"\n')
        f.write(f'aws_session_token = "{aws_token}"\n')

    # also set the environment variables
    os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key  # public identifier
    os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_key  # secret key
    os.environ["AWS_SESSION_TOKEN"] = aws_token  # session token

    return jsonify({"message": "AWS credentials set successfully"}), 200


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
    num_vms = request.form.get("num_vms")
    terraform_dir = "terraform/"

    try:
        # Init Terraform (optional if already initialized)
        subprocess.run(["terraform", "init"], cwd=terraform_dir, check=True)

        # Fetch the IP address of the allocator
        allocator_ip = requests.get("http://checkip.amazonaws.com").text.strip()

        # Write the IP address to the terraform.tfvars file
        # with open(os.path.join(terraform_dir, "terraform.runtime.tfvars"), "w") as f:
        #     f.write(f'allocator_ip = "{allocator_ip}"\n')

        # Apply with the new number of instances
        apply_cmd = [
            "terraform",
            "apply",
            "-auto-approve",
            # "-var-file=terraform.runtime.tfvars",
            "-var-file=terraform.credentials.tfvars",
            f"-var=instance_count={num_vms}",
            f"-var=machine_type={cfg.machine.machine_type}",
            f"-var=allocator_ip={allocator_ip}",
        ]

        # Run the Terraform apply command
        result = subprocess.run(
            apply_cmd, cwd=terraform_dir, check=True, capture_output=True, text=True
        )

        return render_template("dashboard.html", output=result.stdout)

    except subprocess.CalledProcessError as e:
        return render_template("dashboard.html", error=e.stderr or e.stdout)


@app.route("/destroy", methods=["POST"])
@auth.login_required
def destroy():
    terraform_dir = "terraform/"
    try:
        # Destroy Terraform resources
        apply_cmd = [
            "terraform",
            "destroy",
            "-auto-approve",
            # "-var-file=terraform.runtime.tfvars",
            "-var-file=terraform.credentials.tfvars",
        ]
        result = subprocess.run(
            apply_cmd, cwd=terraform_dir, check=True, capture_output=True, text=True
        )

        # Clear the database
        logger.debug("Clearing the database...")
        database.clear_database()
        logger.debug("Database cleared successfully.")

        return render_template("dashboard.html", output=result.stdout)
    except subprocess.CalledProcessError as e:
        return render_template("dashboard.html", error=e.stderr or e.stdout)


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


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000, threaded=True)
