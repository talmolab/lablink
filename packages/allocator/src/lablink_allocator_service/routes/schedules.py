"""Scheduled destruction CRUD.

Writes go through ``ScheduledDestructionService`` (it owns the APScheduler
job registration alongside the DB row); reads go straight to
``ScheduleDatabase``. Both are initialized in ``main()``, so every handler
guards on the service being non-None.
"""
import logging
from datetime import datetime

from flask import Blueprint, Response, jsonify, request

from lablink_allocator_service.auth import auth

bp = Blueprint("schedules", __name__)
logger = logging.getLogger(__name__)

VALID_STATUS_FILTERS = [
    "scheduled",
    "executing",
    "completed",
    "failed",
    "cancelled",
]


@bp.route("/api/schedule-destruction", methods=["POST"])
@auth.login_required
def create_scheduled_destruction() -> Response | tuple[Response, int]:
    """
    Create a new scheduled destruction.

    Request JSON:
    {
        "schedule_name": "Friday Tutorial End",
        "destruction_time": "2025-12-05T17:30:00Z",
        "recurrence_rule": null  // or "FREQ=WEEKLY;BYDAY=FR;BYHOUR=17;BYMINUTE=30"
    }

    Returns:
        Response: JSON with schedule_id and success status, or error with status code.
    """
    from lablink_allocator_service import main

    data = request.get_json()

    # Validation
    if not data.get("schedule_name"):
        return jsonify({"success": False, "message": "schedule_name is required"}), 400

    if not data.get("destruction_time"):
        return jsonify(
            {"success": False, "message": "destruction_time is required"}
        ), 400

    try:
        destruction_time = datetime.fromisoformat(
            data["destruction_time"].replace("Z", "+00:00")
        )

        # Ensure time is in future
        if destruction_time <= datetime.now(destruction_time.tzinfo):
            return jsonify(
                {"success": False, "message": "destruction_time must be in the future"}
            ), 400

        if main.scheduler_service is None:
            return jsonify(
                {"success": False, "message": "Scheduler service not initialized"}
            ), 500

        try:
            schedule_id = main.scheduler_service.schedule_destruction(
                schedule_name=data["schedule_name"],
                destruction_time=destruction_time,
                recurrence_rule=data.get("recurrence_rule"),
                created_by=auth.current_user(),
                notification_enabled=data.get("notification_enabled", False),
                notification_hours_before=data.get("notification_hours_before", 1),
            )
        except ValueError as e:
            # Duplicate schedule name (from database unique constraint)
            return jsonify({"success": False, "message": str(e)}), 409
        except RuntimeError as e:
            # Database or scheduler error
            logger.error(f"Failed to create scheduled destruction: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

        return jsonify(
            {
                "success": True,
                "schedule_id": schedule_id,
                "message": "Scheduled destruction created successfully",
            }
        ), 200

    except ValueError as e:
        return jsonify(
            {"success": False, "message": f"Invalid destruction_time format: {str(e)}"}
        ), 400
    except Exception as e:
        logger.error(f"Failed to create scheduled destruction: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@bp.route("/api/schedule-destruction/<int:schedule_id>", methods=["GET"])
@auth.login_required
def get_scheduled_destruction(schedule_id: int):
    """Get details of a scheduled destruction."""
    from lablink_allocator_service import main

    schedule = main.schedule_db.get_scheduled_destruction(schedule_id)

    if not schedule:
        return jsonify({"success": False, "message": "Schedule not found"}), 404

    return jsonify({"success": True, "schedule": schedule})


@bp.route("/api/schedule-destruction", methods=["GET"])
@auth.login_required
def list_scheduled_destructions() -> Response | tuple[Response, int]:
    """
    List all scheduled destructions.

    Query parameters:
        status (optional): Filter by status (scheduled, executing, completed,
            failed, cancelled)

    Returns:
        Response: JSON with list of schedules, or error with status code.
    """
    from lablink_allocator_service import main

    status_filter = request.args.get("status")

    if status_filter and status_filter not in VALID_STATUS_FILTERS:
        return jsonify(
            {"success": False, "message": f"Invalid status filter: {status_filter}"}
        ), 400

    schedules = main.schedule_db.get_all_scheduled_destructions(status=status_filter)

    return jsonify({"success": True, "schedules": schedules, "count": len(schedules)})


@bp.route("/api/schedule-destruction/<int:schedule_id>", methods=["DELETE"])
@auth.login_required
def cancel_scheduled_destruction(schedule_id: int):
    """Cancel a scheduled destruction."""
    from lablink_allocator_service import main

    # Check if schedule exists
    schedule = main.schedule_db.get_scheduled_destruction(schedule_id)
    if not schedule:
        return jsonify({"success": False, "message": "Schedule not found"}), 404

    # Check if already cancelled or completed
    if schedule["status"] in ["cancelled", "completed"]:
        return jsonify(
            {
                "success": False,
                "message": f"Cannot cancel schedule with status '{schedule['status']}'",
            }
        ), 400

    if main.scheduler_service is None:
        return jsonify(
            {"success": False, "message": "Scheduler service not initialized"}
        ), 500

    try:
        main.scheduler_service.cancel_scheduled_destruction(schedule_id)

        return jsonify(
            {
                "success": True,
                "message": (
                    f"Scheduled destruction {schedule_id} cancelled successfully"
                ),
            }
        )

    except Exception as e:
        logger.error(f"Failed to cancel scheduled destruction: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
