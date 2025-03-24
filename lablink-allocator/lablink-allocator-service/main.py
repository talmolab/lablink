# lablink_allocator_service/main.py
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
import psycopg2
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql://lablink:password@db/lablink_db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class VM(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.String(80), nullable=True)
    status = db.Column(db.String(20), default='available')

def notify_participants():
    """Trigger function to notify participant VMs."""
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cursor = conn.cursor()
    cursor.execute("LISTEN vm_updates;")
    conn.commit()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/request_vm', methods=['POST'])
def request_vm():
    participant_id = request.json.get('participant_id')
    vm = VM.query.filter_by(status='available').first()
    if vm:
        vm.participant_id = participant_id
        vm.status = 'allocated'
        db.session.commit()
        return jsonify({'message': 'VM allocated', 'vm_id': vm.id})
    return jsonify({'message': 'No available VMs'}), 400

@app.route('/admin', methods=['GET'])
def admin_panel():
    vms = VM.query.all()
    return render_template('admin.html', vms=vms)

@app.route('/remote_command', methods=['POST'])
def remote_command():
    command = request.form.get('command')
    return jsonify({'message': 'Command received', 'command': command})

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000)
