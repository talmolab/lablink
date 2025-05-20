from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
import psycopg2
import subprocess
import os
from get_cofig import get_config
from database import PostgresqlDatabase
import requests

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "postgresql://lablink:lablink@localhost:5432/lablink_db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Load the configuration
cfg = get_config()

# Initialize the database connection
database = PostgresqlDatabase(
    dbname=cfg.db.dbname,
    user=cfg.db.user,
    password=cfg.db.password,
    host=cfg.db.host,
    port=cfg.db.port,
    table_name=cfg.db.table_name,
)


class vms(db.Model):
    hostname = db.Column(db.String(1024), primary_key=True)
    pin = db.Column(db.String(1024), nullable=True)
    crdcommand = db.Column(db.String(1024), nullable=True)
    useremail = db.Column(db.String(1024), nullable=True)
    inuse = db.Column(db.Boolean, nullable=False, default=False, server_default="false")


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
def create_instances():
    return render_template("create-instances.html")


@app.route("/admin")
def admin():
    return render_template("admin.html")

@app.route("/admin/set-aws-credentials", methods=["POST"])
def set_aws_credentials():
    aws_access_key = request.form.get("aws_access_key_id", "").strip()
    aws_secret_key = request.form.get("aws_secret_access_key", "").strip()
    aws_token = request.form.get("aws_token", "").strip()

    if not aws_access_key or not aws_secret_key:
        return jsonify({"error": "AWS Access Key and Secret Key are required"}), 400

    # Save the credentials to a file or environment variable
    terraform_dir = "terraform/"  
    
    with open(os.path.join(terraform_dir, "terraform.tfvars"), "w") as f:
        f.write(f'aws_access_key = "{aws_access_key}"\n')
        f.write(f'aws_secret_key = "{aws_secret_key}"\n')
        f.write(f'aws_session_token = "{aws_token}"\n')
        
    

    return jsonify({"message": "AWS credentials set successfully"}), 200


@app.route("/admin/instances")
def view_instances():
    instances = vms.query.all()
    return render_template("instances.html", instances=instances)


@app.route('/admin/instances/delete')
def delete_instances():
    instances = vms.query.all()
    return render_template('delete-instances.html', instances=instances)

@app.route("/request_vm", methods=["POST"])
def submit_vm_details():
    data = request.form  # If you're sending JSON, use request.json instead
    email = data.get("email")
    crd_command = data.get("crd_command")

    if not email or not crd_command:
        return jsonify({"error": "Email and CRD Command are required"}), 400

    # debugging
    all_vms = vms.query.all()
    for vm in all_vms:
        print(vm.hostname, vm.pin, vm.crdcommand, vm.useremail, vm.inuse)

    # Find an available VM
    available_vm = vms.query.filter_by(inuse=False).first()

    if not all_vms:
        return jsonify({"error": "No available VM"}), 404

    # Update the VM record
    available_vm.useremail = email
    available_vm.crdcommand = crd_command
    available_vm.pin = "123456"
    available_vm.inuse = True

    db.session.commit()

    return render_template(
        "success.html", host=available_vm.hostname, pin=available_vm.pin
    )


@app.route("/launch", methods=["POST"])
def launch():
    num_vms = request.form.get("num_vms")
    terraform_dir = "terraform/"  # adjust this if your TF files are elsewhere

    try:
        # Init Terraform (optional if already initialized)
        subprocess.run(["terraform", "init"], cwd=terraform_dir, check=True)
        
        # Fetch the IP address of the allocator
        allocator_ip = requests.get("http://checkip.amazonaws.com").text.strip()
        
        # Write the IP address to the terraform.tfvars file
        with open(os.path.join(terraform_dir, "terraform.tfvars"), "a") as f:
            f.write(f'allocator_ip = "{allocator_ip}"\n')

        # Apply with the new number of instances
        apply_cmd = [
            "terraform",
            "apply",
            "-auto-approve",
            "-var-file=terraform.tfvars",
            f"-var=instance_count={num_vms}",
        ]

        result = subprocess.run(
            apply_cmd, cwd=terraform_dir, check=True, capture_output=True, text=True
        )

        return render_template("dashboard.html", output=result.stdout)

    except subprocess.CalledProcessError as e:
        return render_template("dashboard.html", error=e.stderr or e.stdout)

@app.route("/destroy", methods=["POST"])
def destroy():
    terraform_dir = "terraform/"
    try:
        # Destroy Terraform resources
        apply_cmd = [
            "terraform", "destroy",
            "-auto-approve"
        ]
        result = subprocess.run(apply_cmd, cwd=terraform_dir, check=True, capture_output=True, text=True)
        
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
    print (f"Adding VM {hostname} to database...")
    database.insert_vm(hostname)
    
    result = database.listen_for_notifications(channel="vm_updates", target_hostname=hostname)
    return jsonify(result), 200

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000)
