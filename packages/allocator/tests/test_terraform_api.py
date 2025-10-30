from unittest.mock import patch, MagicMock
import subprocess

POST_ENDPOINT = "/api/launch"
DESTROY_ENDPOINT = "/destroy"


@patch("lablink_allocator_service.main.upload_to_s3")
@patch("lablink_allocator_service.main.check_support_nvidia", return_value=True)
@patch("lablink_allocator_service.main.subprocess.run")
def test_launch_vm_success(
    mock_run,
    mock_check_support_nvidia,
    mock_upload_to_s3,
    client,
    admin_headers,
    monkeypatch,
    omega_config,
    tmp_path,
):
    """Test successful VM launch with some VMs already launched before."""
    # Create a fake terraform directory
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)

    # Mock Global Variables in "main.py"
    monkeypatch.setattr(
        "lablink_allocator_service.main.database",
        MagicMock(get_row_count=MagicMock(return_value=3)),
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.allocator_ip", "1.2.3.4", raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.key_name", "my-key", raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.ENVIRONMENT", "test", raising=False
    )

    # Fake terraform calls
    class R:
        def __init__(self, out="OK"):
            self.stdout, self.stderr = out, ""

    timing_json = '{"vm-1": {"start_time": "2025-10-30T12:00:00Z", "end_time": "2025-10-30T12:01:00Z", "seconds": 60.0}}'
    mock_run.side_effect = [
        R("\x1b[32mapply success\x1b[0m"),
        R(timing_json),
    ]

    # Call route
    resp = client.post(POST_ENDPOINT, headers=admin_headers, data={"num_vms": "2"})
    assert resp.status_code == 200
    assert b"Output Dashboard" in resp.data

    # Assert calls
    assert mock_run.call_count == 2

    # Check apply call
    apply_args, apply_kwargs = mock_run.call_args_list[0]
    apply_cmd_list = apply_args[0]
    assert "apply" in apply_cmd_list
    assert "-var=instance_count=5" in apply_cmd_list
    assert apply_kwargs["cwd"] == terraform_dir

    # Check output call
    output_args, output_kwargs = mock_run.call_args_list[1]
    output_cmd_list = output_args[0]
    assert "output" in output_cmd_list
    assert "-json" in output_cmd_list
    assert "instance_terraform_apply_times" in output_cmd_list
    assert output_kwargs["cwd"] == terraform_dir

    expected_lines = [
        'allocator_ip = "1.2.3.4"',
        f'machine_type = "{omega_config.machine.machine_type}"',
        f'image_name = "{omega_config.machine.image}"',
        f'repository = "{omega_config.machine.repository}"',
        f'client_ami_id = "{omega_config.machine.ami_id}"',
        f'subject_software = "{omega_config.machine.software}"',
        'resource_suffix = "test"',
        'gpu_support = "true"',
    ]

    # Assert tf vars
    tfvars = (terraform_dir / "terraform.runtime.tfvars").read_text()
    missing = [line for line in expected_lines if line not in tfvars]
    assert not missing, f"Missing lines in tfvars: {missing}"

    # Assert upload to s3 called once with correct args
    mock_upload_to_s3.assert_called_once_with(
        bucket_name="test-bucket",
        region="us-west-2",
        local_path=terraform_dir / "terraform.runtime.tfvars",
        env="test",
    )


@patch("lablink_allocator_service.main.subprocess.run")
def test_launch_missing_allocator_outputs_returns_error(
    mock_run, client, admin_headers, monkeypatch, tmp_path
):
    """Test VM launch with missing allocator outputs."""
    # Create a fake terraform directory
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)

    monkeypatch.setattr(
        "lablink_allocator_service.main.database",
        MagicMock(get_row_count=lambda: 0),
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.allocator_ip", "", raising=False
    )
    monkeypatch.setattr("lablink_allocator_service.main.key_name", None, raising=False)

    mock_run.return_value = MagicMock(stdout="INIT", stderr="")

    resp = client.post(POST_ENDPOINT, headers=admin_headers, data={"num_vms": "1"})
    assert resp.status_code == 200
    assert b"Allocator outputs not found." in resp.data
    assert not (terraform_dir / "terraform.runtime.tfvars").exists()


@patch("lablink_allocator_service.main.check_support_nvidia", return_value=False)
@patch("lablink_allocator_service.main.subprocess.run")
def test_launch_apply_failure(
    mock_run, mock_check_support_nvidia, client, admin_headers, monkeypatch, tmp_path
):
    """Test VM launch failure during apply."""
    # Create a fake terraform directory
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)

    monkeypatch.setattr(
        "lablink_allocator_service.main.database",
        MagicMock(get_row_count=lambda: 1),
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.allocator_ip", "9.9.9.9", raising=False
    )
    monkeypatch.setattr("lablink_allocator_service.main.key_name", "k", raising=False)
    monkeypatch.setattr(
        "lablink_allocator_service.main.ENVIRONMENT", "test", raising=False
    )

    def side_effect(cmd, **kwargs):
        if cmd[1] == "init":
            return MagicMock(stdout="OK", stderr="")
        raise subprocess.CalledProcessError(1, cmd, stderr="\x1b[31mboom\x1b[0m")

    mock_run.side_effect = side_effect

    resp = client.post(POST_ENDPOINT, headers=admin_headers, data={"num_vms": "4"})
    assert resp.status_code == 200
    assert b"boom" in resp.data  # stripped

    tfvars = (terraform_dir / "terraform.runtime.tfvars").read_text()
    assert 'gpu_support = "false"' in tfvars


@patch("lablink_allocator_service.main.subprocess.run")
def test_destroy_success(mock_run, client, admin_headers, monkeypatch, tmp_path):
    """Test successful VM destruction via terraform destroy."""
    # Create a fake terraform directory
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)

    # Mock subprocess.run
    mock_run.return_value = type(
        "R", (), {"stdout": "\x1b[32mresources destroyed\x1b[0m", "stderr": ""}
    )

    # Mock DB and attach to app module via string target
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the destroy endpoint
    resp = client.post(DESTROY_ENDPOINT, headers=admin_headers)
    assert resp.status_code == 200
    assert b"resources destroyed" in resp.data

    # Correct terraform command called with cwd
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0][:2] == ["terraform", "destroy"]
    assert "-auto-approve" in args[0]
    assert "-var-file=terraform.runtime.tfvars" in args[0]
    assert kwargs["cwd"] == terraform_dir
    assert kwargs["check"] is True
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True

    # DB cleared exactly once
    fake_db.clear_database.assert_called_once()


@patch("lablink_allocator_service.main.subprocess.run")
def test_destroy_failure(mock_run, client, admin_headers, monkeypatch, tmp_path):
    # Create a fake terraform directory
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)

    # Mock subprocess.run to raise an error
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd=["terraform", "destroy"], stderr="\x1b[31merror\x1b[0m"
    )

    # Call the destroy endpoint
    resp = client.post(DESTROY_ENDPOINT, headers=admin_headers)
    assert b"error" in resp.data

    # Ensure run was called correctly
    mock_run.assert_called_once()


def test_launch_invalid_num_vms(client, admin_headers):
    """Test that providing an invalid number of VMs returns an error."""
    resp = client.post(POST_ENDPOINT, headers=admin_headers, data={"num_vms": "0"})
    assert resp.status_code == 200
    assert b"Number of VMs must be greater than 0." in resp.data

    resp = client.post(POST_ENDPOINT, headers=admin_headers, data={"num_vms": "-1"})
    assert resp.status_code == 200
    assert b"Number of VMs must be greater than 0." in resp.data

    resp = client.post(POST_ENDPOINT, headers=admin_headers, data={"num_vms": "abc"})
    assert resp.status_code == 200
    assert b"Invalid number of VMs. Please enter a valid integer." in resp.data


def test_launch_missing_num_vms(client, admin_headers):
    """Test that not providing the number of VMs returns an error."""
    resp = client.post(POST_ENDPOINT, headers=admin_headers, data={})
    assert resp.status_code == 200
    assert b"Number of VMs is required." in resp.data
