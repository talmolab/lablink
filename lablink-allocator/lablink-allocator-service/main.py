# lablink_allocator_service/main.py
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
import psycopg2
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql://lablink:lablink@localhost:5432/lablink_db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class vm_requests(db.Model):
    hostname = db.Column(db.String(1024), primary_key=True)
    pin = db.Column(db.String(1024), nullable=False)
    crdcommand = db.Column(db.String(1024), nullable=False)
    useremail = db.Column(db.String(1024), nullable=False)
    inuse = db.Column(db.Boolean, default=False)


def notify_participants():
    """Trigger function to notify participant VMs."""
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cursor = conn.cursor()
    cursor.execute("LISTEN vm_updates;")
    conn.commit()

@app.route('/')
def home():
    return render_template('index.html')

@app.route("/request_vm", methods=["POST"])
def submit_vm_details():
    data = request.form  # If you're sending JSON, use request.json instead
    email = data.get("email")
    crd_command = data.get("crd_command")

    if not email or not crd_command:
        return jsonify({"error": "Email and CRD Command are required"}), 400


    # debugging
    all_vms = vm_requests.query.all()
    for vm in all_vms:
      print(vm.hostname, vm.pin, vm.crdcommand, vm.useremail, vm.inuse)

    # Find an available VM
    available_vm = vm_requests.query.filter_by(inuse=False).first()

    if not all_vms:
        return jsonify({"error": "No available VM"}), 404

    # Update the VM record
    available_vm.useremail = email
    available_vm.crdcommand = crd_command
    available_vm.inuse = True

    db.session.commit()

    return jsonify({"message": "VM assigned", "host": available_vm.hostname})

@app.route('/admin', methods=['GET'])
def admin_panel():
    vms = vm_requests.query.all()
    return render_template('admin.html', vms=vms)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000)
