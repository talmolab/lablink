"""Admin HTML pages, all behind HTTP Basic auth.

Rendering only — every state change these pages trigger is posted to a JSON
endpoint in another blueprint (provisioning, admin_sessions, schedules).
"""
import logging

from flask import Blueprint, current_app, jsonify, render_template, request

from lablink_allocator_service.auth import auth
from lablink_allocator_service.utils.config_helpers import (
    canonical_base_url,
    is_self_signed_ssl,
)

bp = Blueprint("admin_pages", __name__)
logger = logging.getLogger(__name__)


@bp.route("/admin/create")
@auth.login_required
def create_instances():
    return render_template("create-instances.html")


@bp.route("/admin")
@auth.login_required
def admin():
    from lablink_allocator_service import main

    provider = current_app.config["LABLINK_PROVIDER"]
    monitoring_enabled = bool(
        getattr(main.cfg, "monitoring", None) and main.cfg.monitoring.enabled
    )
    return render_template(
        "admin.html",
        can_provision_hosts=provider.can_provision_hosts,
        can_destroy_hosts=provider.can_destroy_hosts,
        monitoring_enabled=monitoring_enabled,
    )


@bp.route("/admin/byo-onboarding")
@auth.login_required
def byo_onboarding():
    """Render the ready-to-copy `lablink client register` command for BYO clients.

    The register token rotates on each allocator restart, so this page is
    dynamic — re-render to get the current token. Behind admin Basic auth
    (same gate as the rest of /admin); no new privilege boundary.
    """
    from lablink_allocator_service import main

    return render_template(
        "byo-onboarding.html",
        allocator_url=canonical_base_url(request),
        register_token=main.REGISTER_TOKEN,
        show_insecure=is_self_signed_ssl(main.cfg),
    )


@bp.route("/admin/instances")
@auth.login_required
def view_instances():
    from lablink_allocator_service import main

    instances = main.database.get_all_vms()
    return render_template("instances.html", instances=instances, fragment=False)


@bp.route("/admin/instances/fragment")
@auth.login_required
def view_instances_fragment():
    from lablink_allocator_service import main

    instances = main.database.get_all_vms()
    return render_template("instances.html", instances=instances, fragment=True)


@bp.route("/admin/instances/delete")
@auth.login_required
def delete_instances():
    return render_template("delete-instances.html")


@bp.route("/admin/logs/<hostname>", methods=["GET"])
@auth.login_required
def get_vm_logs(hostname):
    """Get the logs for a specific VM."""
    from lablink_allocator_service import main

    logger.debug(f"Fetching logs for VM: {hostname}")
    if not main.database.vm_exists(hostname=hostname):
        logger.error(f"VM with hostname {hostname} not found.")
        return jsonify({"error": "VM not found."}), 404
    # Non-AWS providers (manual/BYO) have no cloud-init concept; the
    # template hides that section when provider != "aws".
    return render_template(
        "instance-logs.html",
        hostname=hostname,
        provider=main.cfg.provider,
    )


@bp.route("/admin/scheduled-destruction", methods=["GET"])
@auth.login_required
def scheduled_destruction_page():
    """Render scheduled destruction management page."""
    return render_template("scheduled-destruction.html")
