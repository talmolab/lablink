import logging
from datetime import datetime
import subprocess
import os
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from dateutil import rrule

from lablink_allocator_service.database import PostgresqlDatabase

logger = logging.getLogger(__name__)


# Standalone function for scheduled destruction execution
# This avoids pickling issues with the database connection
def execute_scheduled_destruction_job(
    schedule_id: int,
    dbname: str,
    user: str,
    password: str,
    host: str,
    port: int,
    table_name: str,
    message_channel: str,
    terraform_dir: str,
    max_retries: int = 3,
    retry_delay_minutes: int = 10,
):
    """
    Execute a scheduled destruction job.

    This is a standalone function (not a method) to avoid pickling issues
    with APScheduler's SQLAlchemy job store.

    Args:
        schedule_id: ID of the scheduled destruction
        dbname: Database name
        user: Database user
        password: Database password
        host: Database host
        port: Database port
        table_name: VMs table name
        message_channel: Message channel name
        terraform_dir: Path to Terraform directory
        max_retries: Maximum number of retry attempts
        retry_delay_minutes: Base delay in minutes for retries
    """
    from lablink_allocator_service.database import PostgresqlDatabase

    # Create a fresh database connection for this job
    database = PostgresqlDatabase(
        dbname=dbname,
        user=user,
        password=password,
        host=host,
        port=port,
        table_name=table_name,
        message_channel=message_channel,
    )

    logger.info(f"Executing scheduled destruction ID: {schedule_id}")

    try:
        # Mark as executing
        database.update_scheduled_destruction_status(
            schedule_id=schedule_id,
            status="executing",
        )

        # Run terraform destroy
        logger.info("Running terraform destroy")
        cmd = [
            "terraform",
            "destroy",
            "-auto-approve",
            "-var-file=terraform.runtime.tfvars",
        ]

        subprocess.run(
            cmd,
            cwd=terraform_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min timeout
        )

        # Clear database
        logger.info("Clearing all VMs from database")
        database.clear_database()

        # Mark as completed
        database.update_scheduled_destruction_status(
            schedule_id=schedule_id,
            status="completed",
            execution_result="All VMs destroyed successfully",
        )

        logger.info(f"Scheduled destruction {schedule_id} completed successfully")

    except subprocess.CalledProcessError as e:
        error_msg = f"Terraform destroy failed: {e.stderr}"
        logger.error(error_msg)

        database.update_scheduled_destruction_status(
            schedule_id=schedule_id,
            status="failed",
            execution_result=error_msg,
        )

        # Note: Retry logic would need to be implemented in the scheduler
        # if this fails, as we can't easily schedule retries from here

    except Exception as e:
        error_msg = f"Destruction failed: {str(e)}"
        logger.error(error_msg)

        database.update_scheduled_destruction_status(
            schedule_id=schedule_id,
            status="failed",
            execution_result=error_msg,
        )

    finally:
        # Close the database connection manually
        if hasattr(database, "cursor") and database.cursor:
            database.cursor.close()
        if hasattr(database, "conn") and database.conn:
            database.conn.close()
        logger.debug("Database connection closed.")


class ScheduledDestructionService:
    # Hardcoded configuration constants
    MAX_RETRIES = 3
    RETRY_DELAY_MINUTES = 10

    def __init__(
        self,
        database: PostgresqlDatabase,
        db_url: str,
        terraform_dir: Optional[str] = None,
    ):
        """Initialize the scheduler service.

        Args:
            database: PostgresqlDatabase instance
            db_url: PostgreSQL connection URL for APScheduler job store
            terraform_dir: Path to Terraform directory (optional, auto-detected if None)
        """
        self.database: PostgresqlDatabase = database
        self.db_url = db_url

        # Store database config for job execution
        self.db_config = {
            "dbname": database.dbname,
            "user": database.user,
            "password": database.password,
            "host": database.host,
            "port": database.port,
            "table_name": database.table_name,
            "message_channel": database.message_channel,
        }

        self.terraform_dir = terraform_dir or os.path.join(
            os.path.dirname(__file__), "terraform"
        )

        # Configure APScheduler with SQLAlchemy job store
        jobstores = {"default": SQLAlchemyJobStore(url=db_url)}

        executors = {"default": ThreadPoolExecutor(max_workers=2)}

        job_defaults = {
            "coalesce": False,
            "max_instances": 1,
            "misfire_grace_time": 300,
        }

        self.scheduler = BackgroundScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone="UTC",
        )

    def start(self):
        """Start the scheduler and load existing schedules"""
        logger.info("Starting Scheduled Destruction Service...")
        self.scheduler.start()

        # Load existing schedules from the database
        self._load_scheduled_destructions()

    def stop(self):
        """Stop the scheduler."""
        logger.info("Stopping scheduled destruction service")
        self.scheduler.shutdown(wait=True)

    def schedule_destruction(
        self,
        schedule_name: str,
        destruction_time: datetime,
        recurrence_rule: Optional[str] = None,
        created_by: Optional[str] = None,
        notification_enabled: bool = True,
        notification_hours_before: int = 1,
    ) -> int:
        """Schedule a new destruction job.

        Args:
            schedule_name: Unique name for the schedule
            destruction_time: Initial destruction time (UTC)
            recurrence_rule: Optional recurrence rule in RRULE format
            created_by: User who created the schedule
            notification_enabled: Whether to enable notifications
            notification_hours_before: Hours before destruction to notify

        Returns:
            ID of the created schedule in the database
        """
        # Create database record
        schedule_id = self.database.create_scheduled_destruction(
            schedule_name=schedule_name,
            destruction_time=destruction_time,
            recurrence_rule=recurrence_rule,
            created_by=created_by,
            notification_enabled=notification_enabled,
            notification_hours_before=notification_hours_before,
        )

        if schedule_id is None:
            error_msg = f"Failed to create scheduled destruction '{schedule_name}'"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        # Add job to APScheduler
        self._add_scheduler_job(
            schedule_id=schedule_id,
            destruction_time=destruction_time,
            recurrence_rule=recurrence_rule,
        )

        logger.info(
            f"Scheduled destruction '{schedule_name}' (ID: {schedule_id}) "
            f"for {destruction_time}"
        )
        return schedule_id

    def cancel_scheduled_destruction(self, schedule_id: int) -> None:
        """Cancel a scheduled destruction."""

        # Remove from APScheduler
        job_id = f"destruction_{schedule_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        # Update database
        self.database.cancel_scheduled_destruction(schedule_id)

        logger.info(f"Cancelled scheduled destruction ID: {schedule_id}")

    def _add_scheduler_job(
        self,
        schedule_id: int,
        destruction_time: datetime,
        recurrence_rule: Optional[str] = None,
    ) -> None:
        """Add job to APScheduler."""

        job_id = f"destruction_{schedule_id}"

        if recurrence_rule:
            # Parse RRULE string to cron trigger
            # Example: "FREQ=WEEKLY;BYDAY=FR;BYHOUR=17;BYMINUTE=30"
            # Converts to: day_of_week='fri', hour=17, minute=30
            trigger = self._parse_rrule_to_cron(recurrence_rule)
        else:
            # One-time job
            trigger = DateTrigger(run_date=destruction_time)

        self.scheduler.add_job(
            func=execute_scheduled_destruction_job,
            trigger=trigger,
            args=[
                schedule_id,
                self.db_config["dbname"],
                self.db_config["user"],
                self.db_config["password"],
                self.db_config["host"],
                self.db_config["port"],
                self.db_config["table_name"],
                self.db_config["message_channel"],
                self.terraform_dir,
            ],
            id=job_id,
            name=f"Scheduled Destruction {schedule_id}",
            replace_existing=True,
        )

        logger.debug(f"Added APScheduler job: {job_id}")

    def _parse_rrule_to_cron(self, recurrence_rule: str) -> CronTrigger:
        """
        Parse RRULE string to CronTrigger.

        Example:
            FREQ=WEEKLY;BYDAY=FR;BYHOUR=17;BYMINUTE=30
            -> CronTrigger(day_of_week='fri', hour=17, minute=30)
        """
        # Parse with dateutil.rrule
        rule = rrule.rrulestr(recurrence_rule)

        # Extract components
        freq = rule._freq
        byday = rule._byweekday
        byhour = rule._byhour
        byminute = rule._byminute

        # Map to CronTrigger parameters
        kwargs = {}

        if freq == rrule.DAILY:
            kwargs["day"] = "*"
        elif freq == rrule.WEEKLY and byday:
            # Map to day names
            day_map = {
                0: "mon",
                1: "tue",
                2: "wed",
                3: "thu",
                4: "fri",
                5: "sat",
                6: "sun",
            }
            kwargs["day_of_week"] = ",".join([day_map[d] for d in byday])

        if byhour:
            byhour_list = list(byhour) if isinstance(byhour, set) else byhour
            if len(byhour_list) == 1:
                kwargs["hour"] = byhour_list[0]
            else:
                kwargs["hour"] = ",".join(map(str, byhour_list))
        if byminute:
            byminute_list = list(byminute) if isinstance(byminute, set) else byminute
            if len(byminute_list) == 1:
                kwargs["minute"] = byminute_list[0]
            else:
                kwargs["minute"] = ",".join(map(str, byminute_list))

        return CronTrigger(**kwargs)

    def _load_scheduled_destructions(self) -> None:
        """Load existing scheduled destructions from database on startup."""

        pending_schedules = self.database.get_all_scheduled_destructions(
            status="scheduled"
        )

        for schedule in pending_schedules:
            self._add_scheduler_job(
                schedule_id=schedule["id"],
                destruction_time=schedule["destruction_time"],
                recurrence_rule=schedule.get("recurrence_rule"),
            )

        logger.info(f"Loaded {len(pending_schedules)} scheduled destructions")
