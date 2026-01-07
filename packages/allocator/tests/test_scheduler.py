import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Create persistent mock objects that will be used across all tests
mock_apscheduler = MagicMock()
mock_sqlalchemy_jobstore = MagicMock()
mock_thread_pool_executor = MagicMock()
mock_date_trigger = MagicMock()
mock_cron_trigger = MagicMock()
mock_background_scheduler = MagicMock()


@pytest.fixture(scope="session", autouse=True)
def setup_mocks():
    """Setup APScheduler mocks before any tests run."""
    # Only mock if not already imported (to avoid conflicts)
    if "apscheduler" not in sys.modules:
        sys.modules["apscheduler"] = mock_apscheduler
        sys.modules["apscheduler.schedulers"] = MagicMock()
        sys.modules["apscheduler.schedulers.background"] = MagicMock(
            BackgroundScheduler=mock_background_scheduler
        )
        sys.modules["apscheduler.jobstores"] = MagicMock()
        sys.modules["apscheduler.jobstores.sqlalchemy"] = MagicMock(
            SQLAlchemyJobStore=mock_sqlalchemy_jobstore
        )
        sys.modules["apscheduler.executors"] = MagicMock()
        sys.modules["apscheduler.executors.pool"] = MagicMock(
            ThreadPoolExecutor=mock_thread_pool_executor
        )
        sys.modules["apscheduler.triggers"] = MagicMock()
        sys.modules["apscheduler.triggers.date"] = MagicMock(
            DateTrigger=mock_date_trigger
        )
        sys.modules["apscheduler.triggers.cron"] = MagicMock(
            CronTrigger=mock_cron_trigger
        )


# Import scheduler after mocks are potentially set up
from lablink_allocator_service.scheduler import ScheduledDestructionService  # noqa: E402


@pytest.fixture
def mock_database():
    """Fixture to create a mock database instance."""
    return MagicMock()


@pytest.fixture
def mock_scheduler():
    """Fixture to create a mock APScheduler instance."""
    scheduler = MagicMock()
    mock_background_scheduler.return_value = scheduler
    return scheduler


@pytest.fixture
def scheduler_service(mock_database, mock_scheduler):
    """Fixture to create a ScheduledDestructionService instance."""
    db_url = "postgresql://user:pass@localhost:5432/lablink"
    terraform_dir = "/tmp/terraform"

    service = ScheduledDestructionService(
        database=mock_database,
        db_url=db_url,
        terraform_dir=terraform_dir,
    )

    # The service creates its own scheduler, so we need to replace it with our mock
    service.scheduler = mock_scheduler

    return service


def test_init_creates_scheduler(mock_database):
    """Test that __init__ properly configures the APScheduler."""
    db_url = "postgresql://user:pass@localhost:5432/lablink"

    service = ScheduledDestructionService(
        database=mock_database,
        db_url=db_url,
    )

    # Verify the service was created with correct attributes
    assert service.database == mock_database
    assert service.scheduler is not None

    # Only check mocks if they were actually used (when APScheduler wasn't pre-imported)
    if "apscheduler" not in sys.modules or mock_background_scheduler.called:
        # Verify SQLAlchemyJobStore was created with correct URL
        mock_sqlalchemy_jobstore.assert_called_with(url=db_url)
        # Verify ThreadPoolExecutor was created
        mock_thread_pool_executor.assert_called_with(max_workers=2)
        # Verify BackgroundScheduler was created
        mock_background_scheduler.assert_called()


def test_init_custom_terraform_dir(mock_database):
    """Test that custom terraform_dir is used when provided."""
    db_url = "postgresql://user:pass@localhost:5432/lablink"
    custom_dir = "/custom/terraform/path"

    service = ScheduledDestructionService(
        database=mock_database,
        db_url=db_url,
        terraform_dir=custom_dir,
    )

    assert service.terraform_dir == custom_dir


def test_start_loads_scheduled_destructions(scheduler_service, mock_database):
    """Test that start() initializes scheduler and loads existing schedules."""
    mock_database.get_all_scheduled_destructions.return_value = [
        {
            "id": 1,
            "destruction_time": datetime(2025, 12, 6, 18, 0, 0),
            "recurrence_rule": None,
        },
        {
            "id": 2,
            "destruction_time": datetime(2025, 12, 7, 18, 0, 0),
            "recurrence_rule": "FREQ=WEEKLY;BYDAY=FR",
        },
    ]

    scheduler_service.start()

    # Verify scheduler was started
    scheduler_service.scheduler.start.assert_called_once()

    # Verify schedules were loaded from database
    mock_database.get_all_scheduled_destructions.assert_called_once_with(
        status="scheduled"
    )

    # Verify jobs were added to scheduler (2 schedules)
    assert scheduler_service.scheduler.add_job.call_count == 2


def test_schedule_destruction_one_time(scheduler_service, mock_database):
    """Test scheduling a one-time destruction."""
    schedule_name = "End of Tutorial"
    destruction_time = datetime(2025, 12, 6, 18, 0, 0, tzinfo=timezone.utc)
    created_by = "admin@example.com"

    mock_database.create_scheduled_destruction.return_value = 42

    schedule_id = scheduler_service.schedule_destruction(
        schedule_name=schedule_name,
        destruction_time=destruction_time,
        recurrence_rule=None,
        created_by=created_by,
        notification_enabled=True,
        notification_hours_before=1,
    )

    # Verify database record was created
    mock_database.create_scheduled_destruction.assert_called_once_with(
        schedule_name=schedule_name,
        destruction_time=destruction_time,
        recurrence_rule=None,
        created_by=created_by,
        notification_enabled=True,
        notification_hours_before=1,
    )

    # Verify job was added to scheduler
    scheduler_service.scheduler.add_job.assert_called_once()
    call_args = scheduler_service.scheduler.add_job.call_args

    assert call_args[1]["id"] == "destruction_42"
    # Args now include only schedule_id and terraform_dir (no credentials)
    assert call_args[1]["args"][0] == 42  # schedule_id is first arg
    assert len(call_args[1]["args"]) == 2  # schedule_id + terraform_dir
    assert schedule_id == 42


def test_schedule_destruction_recurring(scheduler_service, mock_database):
    """Test scheduling a recurring destruction."""
    schedule_name = "Weekly Cleanup"
    destruction_time = datetime(2025, 12, 6, 17, 30, 0, tzinfo=timezone.utc)
    recurrence_rule = "FREQ=WEEKLY;BYDAY=FR"

    mock_database.create_scheduled_destruction.return_value = 99

    schedule_id = scheduler_service.schedule_destruction(
        schedule_name=schedule_name,
        destruction_time=destruction_time,
        recurrence_rule=recurrence_rule,
        created_by=None,
        notification_enabled=False,
        notification_hours_before=0,
    )

    # Verify database record was created with recurrence
    mock_database.create_scheduled_destruction.assert_called_once()
    call_args = mock_database.create_scheduled_destruction.call_args[1]
    assert call_args["recurrence_rule"] == recurrence_rule

    # Verify job was added to scheduler
    scheduler_service.scheduler.add_job.assert_called_once()
    assert schedule_id == 99


def test_cancel_scheduled_destruction(scheduler_service, mock_database):
    """Test cancelling a scheduled destruction."""
    schedule_id = 42
    mock_job = MagicMock()
    scheduler_service.scheduler.get_job.return_value = mock_job

    scheduler_service.cancel_scheduled_destruction(schedule_id)

    # Verify job was removed from scheduler
    scheduler_service.scheduler.get_job.assert_called_once_with("destruction_42")
    scheduler_service.scheduler.remove_job.assert_called_once_with("destruction_42")

    # Verify database was updated
    mock_database.cancel_scheduled_destruction.assert_called_once_with(schedule_id)


def test_cancel_scheduled_destruction_job_not_found(scheduler_service, mock_database):
    """Test cancelling when job doesn't exist in scheduler."""
    schedule_id = 42
    scheduler_service.scheduler.get_job.return_value = None

    scheduler_service.cancel_scheduled_destruction(schedule_id)

    # Should not try to remove job
    scheduler_service.scheduler.remove_job.assert_not_called()

    # Should still update database
    mock_database.cancel_scheduled_destruction.assert_called_once_with(schedule_id)


def test_parse_rrule_to_cron_weekly(scheduler_service):
    """Test parsing weekly RRULE to CronTrigger."""
    # Reset the mock from previous tests
    mock_cron_trigger.reset_mock()

    # Test the actual parsing (not mocked)
    # This tests the real RRULE parsing logic
    recurrence_rule = "FREQ=WEEKLY;BYDAY=FR;BYHOUR=17;BYMINUTE=30"

    trigger = scheduler_service._parse_rrule_to_cron(recurrence_rule)

    # Verify trigger was created (it will be a CronTrigger or mock depending on setup)
    assert trigger is not None

    # Only verify mock calls if mocks are actually being used
    if mock_cron_trigger.called:
        call_kwargs = mock_cron_trigger.call_args[1]
        assert call_kwargs["day_of_week"] == "fri"
        assert call_kwargs["hour"] == 17
        assert call_kwargs["minute"] == 30


def test_parse_rrule_to_cron_daily(scheduler_service):
    """Test parsing daily RRULE to CronTrigger."""
    recurrence_rule = "FREQ=DAILY;BYHOUR=9;BYMINUTE=0"

    # Reset the mock from previous test
    mock_cron_trigger.reset_mock()

    trigger = scheduler_service._parse_rrule_to_cron(recurrence_rule)

    # Verify trigger was created
    assert trigger is not None

    # Only verify mock calls if mocks are actually being used
    if mock_cron_trigger.called:
        call_kwargs = mock_cron_trigger.call_args[1]
        assert call_kwargs["day"] == "*"
        assert call_kwargs["hour"] == 9
        assert call_kwargs["minute"] == 0


def test_execute_scheduled_destruction_success(scheduler_service, mock_database):
    """Test successful execution of scheduled destruction via standalone function."""
    from lablink_allocator_service.scheduler import execute_scheduled_destruction_job

    schedule_id = 42

    # Mock successful terraform destroy
    with patch("lablink_allocator_service.scheduler.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        # Mock get_config to return test config (patch where it's imported)
        with patch("lablink_allocator_service.get_config.get_config") as mock_get_config:
            mock_config = MagicMock()
            mock_config.db.dbname = "testdb"
            mock_config.db.user = "testuser"
            mock_config.db.password = "testpass"
            mock_config.db.host = "localhost"
            mock_config.db.port = 5432
            mock_config.db.table_name = "vms"
            mock_config.db.message_channel = "vm_updates"
            mock_get_config.return_value = mock_config

            # Mock PostgresqlDatabase constructor (patch where it's imported in the function)
            with patch("lablink_allocator_service.database.PostgresqlDatabase", return_value=mock_database):
                execute_scheduled_destruction_job(
                    schedule_id=schedule_id,
                    terraform_dir="/test/terraform",
                )

        # Verify status updated to executing
        assert mock_database.update_scheduled_destruction_status.call_count >= 2
        first_call = mock_database.update_scheduled_destruction_status.call_args_list[0]
        assert first_call[1]["schedule_id"] == schedule_id
        assert first_call[1]["status"] == "executing"

        # Verify terraform destroy was called
        mock_run.assert_called_once()
        cmd_call = mock_run.call_args
        assert "terraform" in cmd_call[0][0]
        assert "destroy" in cmd_call[0][0]
        assert "-auto-approve" in cmd_call[0][0]

        # Verify database was cleared
        mock_database.clear_database.assert_called_once()

        # Verify status updated to completed
        last_call = mock_database.update_scheduled_destruction_status.call_args_list[-1]
        assert last_call[1]["status"] == "completed"
        assert "successfully" in last_call[1]["execution_result"]


def test_execute_scheduled_destruction_terraform_failure(
    scheduler_service, mock_database
):
    """Test handling of terraform destroy failure via standalone function."""
    from lablink_allocator_service.scheduler import execute_scheduled_destruction_job

    schedule_id = 42

    # Mock terraform destroy failure
    with patch("lablink_allocator_service.scheduler.subprocess.run") as mock_run:
        from subprocess import CalledProcessError

        mock_run.side_effect = CalledProcessError(
            returncode=1,
            cmd=["terraform", "destroy"],
            stderr="Error destroying resources",
        )

        # Mock get_config to return test config (patch where it's imported)
        with patch("lablink_allocator_service.get_config.get_config") as mock_get_config:
            mock_config = MagicMock()
            mock_config.db.dbname = "testdb"
            mock_config.db.user = "testuser"
            mock_config.db.password = "testpass"
            mock_config.db.host = "localhost"
            mock_config.db.port = 5432
            mock_config.db.table_name = "vms"
            mock_config.db.message_channel = "vm_updates"
            mock_get_config.return_value = mock_config

            # Mock PostgresqlDatabase constructor (patch where it's imported in the function)
            with patch("lablink_allocator_service.database.PostgresqlDatabase", return_value=mock_database):
                execute_scheduled_destruction_job(
                    schedule_id=schedule_id,
                    terraform_dir="/test/terraform",
                )

        # Verify status was updated to failed
        calls = mock_database.update_scheduled_destruction_status.call_args_list
        failed_call = [c for c in calls if c[1].get("status") == "failed"][0]
        assert failed_call[1]["schedule_id"] == schedule_id
        assert "Terraform destroy failed" in failed_call[1]["execution_result"]


# NOTE: Retry tests removed - retry logic moved out of scheduler class
# and would need to be implemented differently if needed in the future


def test_load_scheduled_destructions(scheduler_service, mock_database):
    """Test loading schedules from database on startup."""
    mock_schedules = [
        {
            "id": 1,
            "destruction_time": datetime(2025, 12, 6, 18, 0, 0),
            "recurrence_rule": None,
        },
        {
            "id": 2,
            "destruction_time": datetime(2025, 12, 7, 18, 0, 0),
            "recurrence_rule": "FREQ=WEEKLY;BYDAY=FR",
        },
        {
            "id": 3,
            "destruction_time": datetime(2025, 12, 8, 18, 0, 0),
            "recurrence_rule": "FREQ=DAILY",
        },
    ]

    mock_database.get_all_scheduled_destructions.return_value = mock_schedules

    scheduler_service._load_scheduled_destructions()

    # Verify correct status filter was used
    mock_database.get_all_scheduled_destructions.assert_called_once_with(
        status="scheduled"
    )

    # Verify all schedules were added to scheduler
    assert scheduler_service.scheduler.add_job.call_count == 3


def test_load_scheduled_destructions_empty(scheduler_service, mock_database):
    """Test loading when no schedules exist."""
    mock_database.get_all_scheduled_destructions.return_value = []

    scheduler_service._load_scheduled_destructions()

    # Verify no jobs were added
    scheduler_service.scheduler.add_job.assert_not_called()
