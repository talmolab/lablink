from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
import psycopg2
import subprocess
import os

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "postgresql://lablink:lablink@localhost:5432/lablink_db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


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


@app.route("/admin/instances")
def view_instances():
    instances = vms.query.all()
    return render_template("instances.html", instances=instances)


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

        # Apply with the new number of instances
        apply_cmd = [
            "terraform",
            "apply",
            "-auto-approve",
            f"-var=instance_count={num_vms}",
        ]

        result = subprocess.run(
            apply_cmd, cwd=terraform_dir, check=True, capture_output=True, text=True
        )

        return render_template("dashboard.html", output=result.stdout)

    except subprocess.CalledProcessError as e:
        return render_template("dashboard.html", error=e.stderr or e.stdout)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000)
