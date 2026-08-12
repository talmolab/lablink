"""Host provisioning and destruction, plus operation-job status reads.

``/api/launch`` and ``/destroy`` do not run terraform inline — they submit a
job to ``OperationsWorker`` and return 202 (or a redirect), and the admin
dashboard polls ``/api/operations`` for progress. Both are capability-gated
on the provider (``can_provision_hosts`` / ``can_destroy_hosts``) rather than
on provider type.

Every handler answers twice: JSON when the caller prefers it (the CLI), a
redirect back to /admin/instances otherwise (the dashboard's HTML forms).
"""
import base64
import json
import logging
import subprocess
from datetime import datetime
from typing import Callable, Optional

from flask import Blueprint, current_app, jsonify, redirect, request

from lablink_allocator_service.auth import auth
from lablink_allocator_service.db.operations import OperationInProgress
from lablink_allocator_service.utils.ansi import strip_ansi
from lablink_allocator_service.utils.config_helpers import get_allocator_url
from lablink_allocator_service.utils.sg_audit import SGAuditFailure

bp = Blueprint("provisioning", __name__)
logger = logging.getLogger(__name__)


def _wants_json():
    """Return True if the client prefers a JSON response."""
    return request.accept_mimetypes.best == "application/json"


@bp.route("/api/launch", methods=["POST"])
@auth.login_required
def launch():
    from lablink_allocator_service import main

    provider = current_app.config["LABLINK_PROVIDER"]
    if not provider.can_provision_hosts:
        error_msg = "Provider does not support host provisioning."
        if _wants_json():
            return jsonify({"status": "error", "error": error_msg}), 405
        return redirect("/admin/instances?error=launch_unsupported")

    # Validate num_vms input (unchanged)
    try:
        num_vms_str = request.form.get("num_vms")
        if not num_vms_str:
            if _wants_json():
                return jsonify(
                    {"status": "error", "error": "Number of VMs is required."}
                ), 400
            return redirect("/admin/instances?error=num_vms_required")
        num_vms = int(num_vms_str)
        if num_vms <= 0:
            if _wants_json():
                return jsonify({
                    "status": "error",
                    "error": "Number of VMs must be greater than 0.",
                }), 400
            return redirect("/admin/instances?error=num_vms_invalid")
    except ValueError:
        if _wants_json():
            return jsonify({
                "status": "error",
                "error": "Invalid number of VMs. Please enter a valid integer.",
            }), 400
        return redirect("/admin/instances?error=num_vms_invalid")

    if not main.allocator_ip or not main.key_name:
        logger.error("Missing allocator outputs.")
        if _wants_json():
            return jsonify(
                {"status": "error", "error": "Allocator outputs not found."}
            ), 500
        return redirect("/admin/instances?error=allocator_outputs_missing")

    total_vms = num_vms + main.database.get_row_count()
    allocator_url, scheme = get_allocator_url(main.cfg, main.allocator_ip)
    logger.info(f"Using allocator URL: {allocator_url} (protocol: {scheme})")

    spec = {
        "allocator_ip": main.allocator_ip,
        "allocator_url": allocator_url,
        "machine_type": main.cfg.machine.machine_type,
        "image_name": main.cfg.machine.image,
        "repository": main.cfg.machine.repository,
        "client_ami_id": main.cfg.machine.ami_id,
        "subject_software": main.cfg.machine.software,
        "resource_prefix": (
            f"{main.cfg.machine.software}-lablink-client-{main.ENVIRONMENT}"
        ),
        "cloud_init_output_log_group": main.cloud_init_output_log_group,
        "startup_on_error": main.cfg.startup_script.on_error,
        "startup_max_attempts": main.cfg.startup_script.max_attempts,
        "startup_base_delay_seconds": main.cfg.startup_script.base_delay_seconds,
        "startup_success_check_b64": (
            base64.b64encode(
                main.cfg.startup_script.success_check.encode()
            ).decode()
            if main.cfg.startup_script.success_check
            else ""
        ),
        "agent_token": main.AGENT_TOKEN,
        "register_token": main.REGISTER_TOKEN,
        "environment": main.ENVIRONMENT,
        "bucket_name": main.cfg.bucket_name,
        "deployment_name": getattr(main.cfg, "deployment_name", "lablink"),
    }

    def _run_launch(
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> str:
        """Runs on OperationsWorker's background thread, not the request
        thread. Reformats known failure types into RuntimeError with the
        same user-facing text the old synchronous route used, so that
        text ends up in the operation's `error` column."""
        try:
            result = provider.provision_hosts(
                count=total_vms, spec=spec, progress_callback=progress_callback,
            )
        except SGAuditFailure as exc:
            raise RuntimeError(
                f"Security-group audit refused the plan: {exc}"
            ) from exc
        except subprocess.CalledProcessError as e:
            clean_err = strip_ansi(e.stderr or "").strip()
            raise RuntimeError(f"OpenTofu failed: {clean_err}") from e

        for hostname, times in result.timings.items():
            start_time = datetime.fromisoformat(
                times["start_time"].replace("Z", "+00:00")
            )
            end_time = datetime.fromisoformat(
                times["end_time"].replace("Z", "+00:00")
            )
            main.database.update_terraform_timing(
                hostname=hostname,
                per_instance_seconds=float(times["seconds"]),
                per_instance_start_time=start_time,
                per_instance_end_time=end_time,
            )
        return result.apply_stdout

    try:
        job_id = main.operations_worker.submit(
            op_type="apply",
            fn=_run_launch,
            params=json.dumps({"num_vms": num_vms}),
            created_by=auth.current_user(),
        )
    except OperationInProgress as exc:
        error_msg = f"An operation is already in progress (job #{exc.job_id})"
        if _wants_json():
            return jsonify({
                "status": "error", "error": error_msg, "job_id": exc.job_id,
            }), 409
        return redirect(
            f"/admin/instances?error=already_in_progress&job_id={exc.job_id}"
        )

    if _wants_json():
        return jsonify({"job_id": job_id, "status": "queued"}), 202
    return redirect(f"/admin/instances?job={job_id}")


@bp.route("/destroy", methods=["POST"])
@auth.login_required
def destroy():
    from lablink_allocator_service import main

    provider = current_app.config["LABLINK_PROVIDER"]
    if not provider.can_destroy_hosts:
        error_msg = "Provider does not support host destruction."
        if _wants_json():
            return jsonify({"status": "error", "error": error_msg}), 405
        return redirect("/admin/instances?error=destroy_unsupported")

    def _run_destroy(
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> str:
        """Runs on OperationsWorker's background thread, not the request
        thread."""
        # Seal any open session-metrics rows before tearing down VMs, so the
        # final sessions get a duration even though the client agents are
        # about to be killed. Best-effort: never block destroy on a seal
        # failure.
        try:
            sealed = main.metrics_db.bulk_seal_session_metrics()
            logger.info("Sealed %d session-metrics rows before destroy", sealed)
        except Exception as e:
            logger.warning("Could not bulk-seal session metrics: %s", e)

        # destroy_hosts ignores the handles arg (terraform destroy operates
        # on the whole workspace); skip the list_hosts() call.
        try:
            result = provider.destroy_hosts(
                [], progress_callback=progress_callback,
            )
        except FileNotFoundError as e:
            # No terraform.runtime.tfvars → no client VMs were ever launched.
            raise RuntimeError(str(e)) from e
        except subprocess.CalledProcessError as e:
            error_output = strip_ansi(e.stderr or e.stdout or "")
            raise RuntimeError(error_output) from e

        logger.debug("Clearing the database...")
        main.database.clear_database()
        logger.debug("Database cleared successfully.")
        return result.stdout

    try:
        job_id = main.operations_worker.submit(
            op_type="destroy",
            fn=_run_destroy,
            params=None,
            created_by=auth.current_user(),
        )
    except OperationInProgress as exc:
        error_msg = f"An operation is already in progress (job #{exc.job_id})"
        if _wants_json():
            return jsonify({
                "status": "error", "error": error_msg, "job_id": exc.job_id,
            }), 409
        return redirect(
            f"/admin/instances?error=already_in_progress&job_id={exc.job_id}"
        )

    if _wants_json():
        return jsonify({"job_id": job_id, "status": "queued"}), 202
    return redirect(f"/admin/instances?job={job_id}")


@bp.route("/api/operations", methods=["GET"])
@auth.login_required
def list_operations():
    from lablink_allocator_service import main

    if request.args.get("status") == "in_progress":
        return jsonify(main.operations_db.get_in_progress_operation())
    return jsonify(main.operations_db.list_operations(limit=50))


@bp.route("/api/operations/<int:operation_id>", methods=["GET"])
@auth.login_required
def get_operation(operation_id):
    from lablink_allocator_service import main

    operation = main.operations_db.get_operation(operation_id)
    if operation is None:
        return jsonify({"error": "Operation not found"}), 404
    return jsonify(operation)
