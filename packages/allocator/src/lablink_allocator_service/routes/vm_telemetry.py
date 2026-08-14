"""VM telemetry: client-VM writes and the operator's read side.

Both directions over the same columns live here on purpose — POST and GET
``/api/vm-status`` are two ends of one column, and splitting them by auth
gate would scatter one concern across two files.

Auth differs per direction, so read the decorators carefully:
``@require_client_secret`` for anything a client VM pushes,
``@auth.login_required`` for anything an operator reads.
"""
import logging

from flask import Blueprint, jsonify, request

from lablink_allocator_service.auth import auth, require_client_secret
from lablink_allocator_service.utils.ansi import strip_ansi
from lablink_allocator_service.utils.log_filter import filter_errors

bp = Blueprint("vm_telemetry", __name__)
logger = logging.getLogger(__name__)

# Cap per log type, enforced in the DB append (see receive_vm_logs).
MAX_LOG_SIZE = 1 * 1024 * 1024  # 1MB


@bp.route("/api/update_inuse_status", methods=["POST"])
@require_client_secret
def update_inuse_status():
    """Update the in-use status of a VM."""
    from lablink_allocator_service import main

    data = request.get_json()
    hostname = data.get("hostname")
    in_use = data.get("status")

    logger.debug(f"Updating in-use status for {hostname} to {in_use}")

    if not hostname:
        return jsonify({"error": "Hostname is required."}), 400

    try:
        main.database.update_vm_in_use(hostname=hostname, in_use=in_use)
        return jsonify({"message": "In-use status updated successfully."}), 200
    except Exception as e:
        logger.error(f"Error updating in-use status: {e}")
        return jsonify({"error": "Failed to update in-use status."}), 500


@bp.route("/api/gpu_health", methods=["POST"])
@require_client_secret
def update_gpu_health():
    """Check the health of the GPU."""
    from lablink_allocator_service import main

    data = request.get_json()
    gpu_status = data.get("gpu_status")
    hostname = data.get("hostname")
    if gpu_status is None or hostname is None:
        return jsonify({"error": "GPU status and hostname are required."}), 400

    try:
        main.database.touch_last_seen(hostname=hostname)
        main.database.update_health(hostname=hostname, healthy=gpu_status)
        logger.debug(f"Updated GPU health status for {hostname} to {gpu_status}")
        return jsonify({"message": "GPU health status updated successfully."}), 200
    except Exception as e:
        logger.error(f"Error updating GPU health status: {e}")
        return jsonify({"error": "Failed to update GPU health status."}), 500


@bp.route("/api/heartbeat", methods=["POST"])
@require_client_secret
def heartbeat():
    """Record a client-VM liveness heartbeat."""
    from lablink_allocator_service import main

    data = request.get_json() or {}
    hostname = data.get("vm_id")
    if not hostname:
        return jsonify({"error": "vm_id is required."}), 400

    boot_id = data.get("boot_id")
    disk_free_pct = data.get("disk_free_pct")

    try:
        ok = main.database.record_heartbeat(
            hostname=hostname,
            boot_id=boot_id,
            disk_free_pct=disk_free_pct,
        )
        if not ok:
            return jsonify({"error": "Unknown hostname."}), 404
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"Error recording heartbeat for {hostname}: {e}")
        return jsonify({"error": "Failed to record heartbeat."}), 500


@bp.route("/api/vm-status", methods=["POST"])
@require_client_secret
def update_vm_status():
    from lablink_allocator_service import main

    try:
        data = request.get_json()
        hostname = data.get("hostname")
        status = data.get("status")

        if not hostname or status is None:
            return jsonify({"error": "Hostname and status are required."}), 400

        main.database.touch_last_seen(hostname=hostname)
        main.database.update_vm_status(hostname=hostname, status=status)

        return jsonify({"message": "VM status updated successfully."}), 200
    except Exception as e:
        logger.error(f"Error updating VM status: {e}")
        return jsonify({"error": "Failed to update VM status."}), 500


@bp.route("/api/vm-status", methods=["GET"])
@auth.login_required
def get_all_vm_status():
    from lablink_allocator_service import main

    try:
        vm_status = main.database.get_all_vm_status()
        if not vm_status:
            return jsonify({"error": "No VMs found."}), 404

        return jsonify(vm_status), 200
    except Exception as e:
        logger.error(f"Error getting all VM status: {e}")
        return jsonify({"error": "Failed to get VM status."}), 500


@bp.route("/api/vm-logs/<hostname>", methods=["POST"])
@require_client_secret
def receive_vm_logs(hostname):
    from lablink_allocator_service import main

    try:
        data = request.get_json()
        log_group = data.get("log_group")
        messages = data.get("messages", [])

        if not log_group or not messages:
            return (
                jsonify({"error": "Log group and messages are required."}),
                400,
            )

        # Check if the VM exists in the database
        if not main.database.vm_exists(hostname):
            logger.error(f"VM with hostname {hostname} does not exist.")
            return jsonify({"error": "VM not found."}), 404

        logger.debug(
            f"Received logs for {log_group}/{hostname}: {len(messages)} messages"
        )

        # Strip ANSI escape codes and drop empty lines
        messages = [strip_ansi(m) for m in messages]
        messages = [m for m in messages if m.strip()]

        if not messages:
            return jsonify({"message": "No log messages after filtering."}), 200

        # Determine log type from log_group
        log_type = "docker" if log_group.endswith("-docker") else "cloud_init"

        # Save the logs to the database atomically (cap at 1MB per log type)
        new_logs = "\n".join(messages)
        main.database.append_logs_by_hostname(
            hostname=hostname,
            new_logs=new_logs,
            log_type=log_type,
            max_size=MAX_LOG_SIZE,
        )

        return jsonify({"message": "VM logs posted successfully."}), 200
    except Exception as e:
        logger.error(f"Error receiving VM logs: {e}")
        return jsonify({"error": "Failed to post VM logs."}), 500


@bp.route("/api/vm-logs/<hostname>", methods=["GET"])
@auth.login_required
def get_vm_logs_by_hostname(hostname):
    from lablink_allocator_service import main

    try:
        if not main.database.vm_exists(hostname):
            logger.error(f"VM with hostname {hostname} not found.")
            return jsonify({"error": "VM not found."}), 404

        # If the logs are empty but the vm is initializing, return a 503 status
        logs_data = main.database.get_vm_logs(hostname=hostname)
        status = main.database.get_status_by_hostname(hostname)
        if logs_data is None and status == "initializing":
            return jsonify({"error": "VM is initializing."}), 503

        cloud_init_logs = (logs_data or {}).get("cloud_init_logs")
        docker_logs = (logs_data or {}).get("docker_logs")

        # Same spelling as routes/metrics.py:122's include_logs flag.
        if request.args.get("errors_only", "false").lower() == "true":
            cloud_init_logs = filter_errors(cloud_init_logs)
            docker_logs = filter_errors(docker_logs)

        return jsonify({
            "hostname": hostname,
            "cloud_init_logs": cloud_init_logs,
            "docker_logs": docker_logs,
            "logs": "\n".join(filter(None, [cloud_init_logs, docker_logs])) or None,
        }), 200
    except Exception as e:
        logger.error(f"Error getting VM logs: {e}")
        return jsonify({"error": "Failed to get VM logs."}), 500


@bp.route("/api/vm-metrics/<hostname>", methods=["POST"])
@require_client_secret
def receive_vm_metrics(hostname):
    """Receive and store VM Cloud init metrics."""
    from lablink_allocator_service import main

    try:
        data = request.get_json()

        if not main.database.vm_exists(hostname=hostname):
            logger.error(f"VM with hostname {hostname} does not exist.")
            return jsonify({"error": "VM not found."}), 404

        main.database.touch_last_seen(hostname=hostname)
        # Update VM metrics and calculate total startup time atomically
        # This combines two database operations into one for better performance
        main.database.update_vm_metrics_atomic(hostname=hostname, metrics=data)

        logger.debug(f"Received metrics for {hostname}")
        return jsonify({"message": "VM metrics posted successfully."}), 200

    except Exception as e:
        logger.error(f"Error receiving VM metrics for {hostname}: {e}", exc_info=True)
        return jsonify({"error": "Failed to post VM metrics."}), 500
