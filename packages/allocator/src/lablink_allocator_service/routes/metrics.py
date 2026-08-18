"""Session metrics: client push, operator summary, and full export.

``_session_metrics_view_model`` is shared by the HTML page and the JSON
summary endpoint so the two cannot disagree on monitoring-enabled state,
subject-software label, or summary numbers.
"""
import csv
import io
import logging
from datetime import datetime

from flask import Blueprint, Response, jsonify, render_template, request

from lablink_allocator_service.auth import auth, require_client_secret

bp = Blueprint("metrics", __name__)
logger = logging.getLogger(__name__)


@bp.route("/api/session-metrics/<hostname>", methods=["POST"])
@require_client_secret
def post_session_metrics(hostname):
    """Report session metrics.

    The client's monitoring sampler posts its accumulated per-session
    counters (time-in-software, GPU activity, training progress).

    **Error Response:**

    - **Code:** `400 Bad Request` if `counters` is missing.
    - **Code:** `404 Not Found` if the VM does not exist.
    - **Code:** `409 Conflict` if the session's row is already sealed.
    """
    from lablink_allocator_service import main

    try:
        data = request.get_json(silent=True) or {}
        if "counters" not in data:
            return jsonify({"error": "Missing 'counters' in payload."}), 400
        main.metrics_db.update_session_metrics(hostname=hostname, payload=data)
        return jsonify({"message": "Session metrics updated."}), 200
    except LookupError:
        return jsonify({"error": "VM not found."}), 404
    except ValueError as e:
        # Sealed row — refuse update.
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        logger.error(
            f"Error in /api/session-metrics/{hostname}: {e}", exc_info=True
        )
        return jsonify({"error": "Failed to update session metrics."}), 500


def _session_metrics_view_model() -> dict:
    """Return the shared cohort-summary view model.

    Used by both /admin/session-metrics (HTML) and
    /api/session-metrics/summary (JSON) so the two routes cannot
    disagree on monitoring-enabled state, subject-software label, or
    summary numbers. Per-VM rows are NOT included here — the admin
    HTML route fetches those separately for its per-VM table.
    """
    from lablink_allocator_service import main

    cfg = main.cfg
    monitoring_enabled = bool(
        getattr(cfg, "monitoring", None) and cfg.monitoring.enabled
    )
    patterns = list(
        getattr(getattr(cfg, "monitoring", None), "subject_window_patterns", []) or []
    )
    subject_software_label = (
        patterns[0]
        if patterns
        else getattr(getattr(cfg, "machine", None), "software", "")
        or "subject"
    )
    summary = (
        main.metrics_db.get_session_metrics_summary() if monitoring_enabled else None
    )
    return {
        "enabled": monitoring_enabled,
        "subject_software_label": subject_software_label,
        "summary": summary,
    }


@bp.route("/admin/session-metrics", methods=["GET"])
@auth.login_required
def admin_session_metrics():
    """Render the cohort summary + per-VM table for Tier 1 monitoring."""
    from lablink_allocator_service import main

    vm = _session_metrics_view_model()
    if not vm["enabled"]:
        return render_template(
            "session-metrics.html",
            monitoring_enabled=False,
            summary=None,
            vms=[],
            subject_software_label=vm["subject_software_label"],
        )

    vms = main.database.get_all_vms_for_export(include_logs=False)
    for row in vms:
        for key, value in row.items():
            if hasattr(value, "isoformat"):
                row[key] = value.isoformat()
    return render_template(
        "session-metrics.html",
        monitoring_enabled=True,
        summary=vm["summary"],
        vms=vms,
        subject_software_label=vm["subject_software_label"],
    )


@bp.route("/api/session-metrics/summary", methods=["GET"])
@auth.login_required
def get_session_metrics_summary_json():
    """Get the cohort summary.

    Returns the aggregate view model — participation funnel plus cohort
    totals. Both the admin **Session Metrics** page and `lablink stats`
    render this same payload, so the two can never disagree.
    """
    return jsonify(_session_metrics_view_model()), 200


@bp.route("/api/export-metrics", methods=["GET"])
@auth.login_required
def export_metrics():
    """Export metrics.

    Per-VM metrics as CSV or JSON (controlled by `?format=`). Backs
    `lablink export-metrics --client`.
    """
    from lablink_allocator_service import main

    try:
        include_logs = request.args.get("include_logs", "false").lower() == "true"
        fmt = request.args.get("format", "json").lower()
        vms = main.database.get_all_vms_for_export(include_logs=include_logs)

        # Serialize datetime objects to ISO format strings
        for vm in vms:
            for key, value in vm.items():
                if hasattr(value, "isoformat"):
                    vm[key] = value.isoformat()

        if fmt == "csv":
            buf = io.StringIO()
            if vms:
                # IMPORTANT: fieldnames are auto-discovered from every key
                # present on any row. Any column added to the `vms` table
                # is therefore auto-exported via this endpoint, regardless
                # of whether the operator intended it to be downloadable.
                # If you add a new column carrying sensitive data
                # (credentials, tokens, raw secrets), filter it explicitly
                # here OR drop it from `get_all_vms_for_export` first.
                fieldnames: list[str] = []
                seen: set[str] = set()
                for vm in vms:
                    for k in vm:
                        if k not in seen:
                            seen.add(k)
                            fieldnames.append(k)
                writer = csv.DictWriter(buf, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(vms)
            deploy = getattr(main.cfg, "deployment_name", "lablink") or "lablink"
            stamp = datetime.utcnow().strftime("%Y%m%d")
            filename = f"lablink-session-metrics-{deploy}-{stamp}.csv"
            resp = Response(buf.getvalue(), mimetype="text/csv")
            resp.headers["Content-Disposition"] = (
                f'attachment; filename="{filename}"'
            )
            return resp

        return jsonify({"vms": vms, "count": len(vms)}), 200
    except Exception as e:
        logger.error(f"Error exporting metrics: {e}")
        return jsonify({"error": "Failed to export metrics."}), 500
