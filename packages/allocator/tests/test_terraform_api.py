from unittest.mock import patch, MagicMock
import json
import subprocess

POST_ENDPOINT = "/api/launch"
DESTROY_ENDPOINT = "/destroy"

# ---------------------------------------------------------------------------
# Helper: wire a fresh AWSProvider to a given terraform_dir and inject it into
# app.config["LABLINK_PROVIDER"] so the refactored /api/launch route calls
# provision_hosts on the right directory.
# ---------------------------------------------------------------------------

def _wire_aws_provider(monkeypatch, terraform_dir, region="us-west-2"):
    """Replace LABLINK_PROVIDER in app.config with an AWSProvider that uses
    terraform_dir.  Must be called after the monkeypatch for TERRAFORM_DIR
    so the two are in sync."""
    from lablink_allocator_service import main
    from lablink_allocator_service.providers.aws import AWSProvider

    provider = AWSProvider(region=region, terraform_dir=str(terraform_dir))
    monkeypatch.setitem(main.app.config, "LABLINK_PROVIDER", provider)

JSON_ACCEPT = {"Accept": "application/json"}

# JSON plan the SG audit accepts: protected ports :6080 / :7070 are
# allocator-only, :22 is public. The /api/launch handler runs
# `terraform plan -out=...` then `terraform show -json` then audit
# then `terraform apply <planfile>` then `terraform output -json`,
# so subprocess.run side_effect lists must produce four results in
# that order — and the second result's .stdout must be a JSON string
# the audit accepts.
CLEAN_PLAN_JSON = json.dumps({
    "resource_changes": [
        {
            "address": "aws_security_group.lablink_sg",
            "type": "aws_security_group",
            "name": "lablink_sg",
            "change": {
                "actions": ["create"],
                "before": None,
                "after": {
                    "ingress": [
                        {
                            "from_port": 22, "to_port": 22, "protocol": "tcp",
                            "cidr_blocks": ["0.0.0.0/0"],
                            "ipv6_cidr_blocks": [], "security_groups": [],
                        },
                        {
                            "from_port": 6080, "to_port": 6080, "protocol": "tcp",
                            "cidr_blocks": [], "ipv6_cidr_blocks": [],
                            "security_groups": ["sg-allocator"],
                        },
                        {
                            "from_port": 7070, "to_port": 7070, "protocol": "tcp",
                            "cidr_blocks": [], "ipv6_cidr_blocks": [],
                            "security_groups": ["sg-allocator"],
                        },
                    ],
                },
            },
        },
    ],
})


@patch("lablink_allocator_service.providers.aws.upload_to_s3")
@patch("lablink_allocator_service.providers.aws.check_support_nvidia", return_value=True)
@patch("lablink_allocator_service.providers.aws.get_instance_timings",
       return_value={"vm-1": {"start_time": "2025-10-30T12:00:00Z",
                              "end_time": "2025-10-30T12:01:00Z",
                              "seconds": 60.0}})
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_launch_vm_success(
    mock_run,
    mock_get_names,
    mock_get_ids,
    mock_get_timings,
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
    _wire_aws_provider(monkeypatch, terraform_dir)

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

    # Fake terraform calls (plan + show + apply; get_instance_* are patched)
    class R:
        def __init__(self, out="OK"):
            self.stdout, self.stderr = out, ""
            self.returncode = 0

    mock_run.side_effect = [
        R("OK"),                             # terraform plan -out (writes plan file)
        R(CLEAN_PLAN_JSON),                  # terraform show -json (feeds the SG audit)
        R("\x1b[32mapply success\x1b[0m"),   # terraform apply <planfile>
    ]

    # Call route
    resp = client.post(POST_ENDPOINT, headers=admin_headers, data={"num_vms": "2"})
    assert resp.status_code == 200
    assert b"Output Dashboard" in resp.data

    # Assert calls (plan + show -json + apply = 3; terraform output calls
    # are handled by patched get_instance_* functions)
    assert mock_run.call_count == 3

    # Check plan call (must come first; writes the plan file)
    plan_args, plan_kwargs = mock_run.call_args_list[0]
    plan_cmd_list = plan_args[0]
    assert "plan" in plan_cmd_list
    assert "-no-color" in plan_cmd_list
    assert "-out" in plan_cmd_list
    assert "-var=instance_count=5" in plan_cmd_list
    assert plan_kwargs["cwd"] == terraform_dir

    # Check show -json call (reads the plan back for the audit)
    show_args, show_kwargs = mock_run.call_args_list[1]
    show_cmd_list = show_args[0]
    assert show_cmd_list[1] == "show"
    assert "-json" in show_cmd_list
    assert show_kwargs["cwd"] == terraform_dir

    # Check apply call (applies the saved plan file; vars are baked in)
    apply_args, apply_kwargs = mock_run.call_args_list[2]
    apply_cmd_list = apply_args[0]
    assert "apply" in apply_cmd_list
    # apply consumes a saved plan file rather than fresh -var flags
    assert not any(a.startswith("-var=") for a in apply_cmd_list)
    assert apply_kwargs["cwd"] == terraform_dir

    expected_lines = [
        'allocator_ip = "1.2.3.4"',
        f'machine_type = "{omega_config.machine.machine_type}"',
        f'image_name = "{omega_config.machine.image}"',
        f'repository = "{omega_config.machine.repository}"',
        f'client_ami_id = "{omega_config.machine.ami_id}"',
        f'subject_software = "{omega_config.machine.software}"',
        'resource_prefix = "sleap-lablink-client-test"',
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
        deployment_name="test-lablink",
    )


@patch("lablink_allocator_service.providers.aws.current_instance_security_group",
       return_value="sg-fake-allocator")
@patch("lablink_allocator_service.providers.aws.upload_to_s3")
@patch("lablink_allocator_service.providers.aws.check_support_nvidia", return_value=True)
@patch("lablink_allocator_service.providers.aws.get_instance_timings",
       return_value={"vm-1": {"start_time": "2025-10-30T12:00:00Z",
                              "end_time": "2025-10-30T12:01:00Z",
                              "seconds": 60.0}})
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_launch_vm_appends_allocator_sg_id_var(
    mock_run,
    mock_get_names,
    mock_get_ids,
    mock_get_timings,
    mock_check_support_nvidia,
    mock_upload_to_s3,
    mock_current_sg,
    client,
    admin_headers,
    monkeypatch,
    omega_config,
    tmp_path,
):
    """When running on EC2, the allocator's own SG id is appended as a
    -var to terraform apply so client SG ingress can lock down to it."""
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR",
                        terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database",
        MagicMock(get_row_count=MagicMock(return_value=0)),
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.allocator_ip", "1.2.3.4",
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.key_name", "my-key", raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.ENVIRONMENT", "test", raising=False,
    )

    class R:
        def __init__(self, out="OK"):
            self.stdout, self.stderr, self.returncode = out, "", 0

    mock_run.side_effect = [
        R("OK"),               # terraform plan -out
        R(CLEAN_PLAN_JSON),    # terraform show -json
        R("apply ok"),         # terraform apply <planfile>
    ]

    resp = client.post(POST_ENDPOINT, headers=admin_headers,
                        data={"num_vms": "1"})
    assert resp.status_code == 200

    # The allocator-SG var is supplied via terraform plan; apply runs
    # off the saved plan file and never sees -var flags directly.
    plan_args, _ = mock_run.call_args_list[0]
    plan_cmd_list = plan_args[0]
    assert "plan" in plan_cmd_list
    assert "-var=allocator_sg_id=sg-fake-allocator" in plan_cmd_list

    apply_args, _ = mock_run.call_args_list[2]
    apply_cmd_list = apply_args[0]
    assert "apply" in apply_cmd_list
    assert not any(a.startswith("-var=") for a in apply_cmd_list)
    mock_current_sg.assert_called_once()


@patch(
    "lablink_allocator_service.providers.aws.current_instance_security_group",
)
@patch("lablink_allocator_service.providers.aws.upload_to_s3")
@patch("lablink_allocator_service.providers.aws.check_support_nvidia", return_value=True)
@patch("lablink_allocator_service.providers.aws.get_instance_timings",
       return_value={"vm-1": {"start_time": "2025-10-30T12:00:00Z",
                              "end_time": "2025-10-30T12:01:00Z",
                              "seconds": 60.0}})
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_launch_vm_skips_sg_var_when_not_on_ec2(
    mock_run,
    mock_get_names,
    mock_get_ids,
    mock_get_timings,
    mock_check_support_nvidia,
    mock_upload_to_s3,
    mock_current_sg,
    client,
    admin_headers,
    monkeypatch,
    tmp_path,
):
    """Outside EC2 (IMDSv2 unreachable), the allocator_sg_id var is
    skipped — the apply command still goes through. Terraform itself
    will fail with a missing-variable error in that case, which is the
    correct signal that the deploy is mis-configured for dev."""
    from lablink_allocator_service.utils.aws_utils import NotOnEC2Error

    mock_current_sg.side_effect = NotOnEC2Error("no IMDS")

    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR",
                        terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database",
        MagicMock(get_row_count=MagicMock(return_value=0)),
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.allocator_ip", "1.2.3.4",
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.key_name", "my-key", raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.ENVIRONMENT", "test", raising=False,
    )

    class R:
        def __init__(self, out="OK"):
            self.stdout, self.stderr, self.returncode = out, "", 0

    mock_run.side_effect = [
        R("OK"),               # terraform plan -out
        R(CLEAN_PLAN_JSON),    # terraform show -json
        R("apply ok"),         # terraform apply <planfile>
    ]

    resp = client.post(POST_ENDPOINT, headers=admin_headers,
                        data={"num_vms": "1"})
    assert resp.status_code == 200

    # When IMDSv2 was unreachable, the plan must not include the
    # allocator-SG var. apply runs off the saved plan file and has
    # no -var flags at all.
    plan_args, _ = mock_run.call_args_list[0]
    plan_cmd_list = plan_args[0]
    assert "plan" in plan_cmd_list
    assert not any(
        a.startswith("-var=allocator_sg_id=") for a in plan_cmd_list
    )

    apply_args, _ = mock_run.call_args_list[2]
    apply_cmd_list = apply_args[0]
    assert "apply" in apply_cmd_list
    assert not any(a.startswith("-var=") for a in apply_cmd_list)


def test_launch_missing_allocator_outputs_returns_error(
    client, admin_headers, monkeypatch, tmp_path
):
    """Test VM launch with missing allocator outputs."""
    # Create a fake terraform directory
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)

    monkeypatch.setattr(
        "lablink_allocator_service.main.database",
        MagicMock(get_row_count=lambda: 0),
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.allocator_ip", "", raising=False
    )
    monkeypatch.setattr("lablink_allocator_service.main.key_name", None, raising=False)

    resp = client.post(POST_ENDPOINT, headers=admin_headers, data={"num_vms": "1"})
    assert resp.status_code == 200
    assert b"Allocator outputs not found." in resp.data
    assert not (terraform_dir / "terraform.runtime.tfvars").exists()


@patch("lablink_allocator_service.providers.aws.check_support_nvidia", return_value=False)
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_launch_apply_failure(
    mock_run, mock_check_support_nvidia, client, admin_headers, monkeypatch, tmp_path
):
    """Test VM launch failure during apply."""
    # Create a fake terraform directory
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)

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
        if cmd[1] == "plan":
            # plan writes the plan file; stdout is ignored.
            return MagicMock(stdout="OK", stderr="", returncode=0)
        if cmd[1] == "show":
            # SG audit must pass; otherwise apply never runs.
            return MagicMock(stdout=CLEAN_PLAN_JSON, stderr="", returncode=0)
        raise subprocess.CalledProcessError(1, cmd, stderr="\x1b[31mboom\x1b[0m")

    mock_run.side_effect = side_effect

    resp = client.post(POST_ENDPOINT, headers=admin_headers, data={"num_vms": "4"})
    assert resp.status_code == 200
    assert b"boom" in resp.data  # stripped

    tfvars = (terraform_dir / "terraform.runtime.tfvars").read_text()
    assert 'gpu_support = "false"' in tfvars


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.current_instance_security_group",
       return_value="sg-test")
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_destroy_success(mock_run, mock_sg, mock_ids, mock_names,
                         client, admin_headers, monkeypatch, tmp_path):
    """Test successful VM destruction via terraform destroy."""
    # Create a fake terraform directory with tfvars
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    (terraform_dir / "terraform.runtime.tfvars").write_text("num_vms = 2")
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)

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


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.current_instance_security_group",
       return_value="sg-test")
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_destroy_failure(mock_run, mock_sg, mock_ids, mock_names,
                         client, admin_headers, monkeypatch, tmp_path):
    # Create a fake terraform directory with tfvars
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    (terraform_dir / "terraform.runtime.tfvars").write_text("num_vms = 2")
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)

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


# ------------------------------------------------------------------
# JSON response tests (Accept: application/json)
# ------------------------------------------------------------------


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.current_instance_security_group",
       return_value="sg-test")
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_destroy_json_success(mock_run, mock_sg, mock_ids, mock_names,
                               client, admin_headers, monkeypatch, tmp_path):
    """Test successful destroy returns JSON when Accept header is set."""
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    (terraform_dir / "terraform.runtime.tfvars").write_text("num_vms = 2")
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)

    mock_run.return_value = type(
        "R", (), {"stdout": "\x1b[32mresources destroyed\x1b[0m", "stderr": ""}
    )

    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    headers = {**admin_headers, **JSON_ACCEPT}
    resp = client.post(DESTROY_ENDPOINT, headers=headers)

    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["status"] == "success"
    assert "resources destroyed" in body["output"]

    fake_db.clear_database.assert_called_once()


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.current_instance_security_group",
       return_value="sg-test")
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_destroy_json_failure(mock_run, mock_sg, mock_ids, mock_names,
                               client, admin_headers, monkeypatch, tmp_path):
    """Test terraform destroy failure returns JSON 500 when Accept header is set."""
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    (terraform_dir / "terraform.runtime.tfvars").write_text("num_vms = 2")
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)

    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["terraform", "destroy"],
        stderr="\x1b[31mfailed to destroy\x1b[0m",
    )

    headers = {**admin_headers, **JSON_ACCEPT}
    resp = client.post(DESTROY_ENDPOINT, headers=headers)

    assert resp.status_code == 500
    body = json.loads(resp.data)
    assert body["status"] == "error"
    assert "failed to destroy" in body["error"]


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
def test_destroy_no_tfvars(mock_ids, mock_names,
                            client, admin_headers, monkeypatch, tmp_path):
    """Test destroy returns 404 when tfvars does not exist (no VMs launched)."""
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    # Do NOT create terraform.runtime.tfvars
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)

    resp = client.post(DESTROY_ENDPOINT, headers=admin_headers)
    assert resp.status_code == 404


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
def test_destroy_no_tfvars_json(mock_ids, mock_names,
                                 client, admin_headers, monkeypatch, tmp_path):
    """Test destroy returns JSON 404 when tfvars does not exist."""
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)

    headers = {**admin_headers, **JSON_ACCEPT}
    resp = client.post(DESTROY_ENDPOINT, headers=headers)

    assert resp.status_code == 404
    body = json.loads(resp.data)
    assert body["status"] == "error"
    assert "tfvars does not exist" in body["error"]


@patch("lablink_allocator_service.providers.aws.upload_to_s3")
@patch("lablink_allocator_service.providers.aws.check_support_nvidia", return_value=True)
@patch("lablink_allocator_service.providers.aws.get_instance_timings",
       return_value={"vm-1": {"start_time": "2025-10-30T12:00:00Z",
                              "end_time": "2025-10-30T12:01:00Z",
                              "seconds": 60.0}})
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_launch_json_success(
    mock_run,
    mock_get_names,
    mock_get_ids,
    mock_get_timings,
    mock_check_support_nvidia,
    mock_upload_to_s3,
    client,
    admin_headers,
    monkeypatch,
    tmp_path,
):
    """Test successful VM launch returns JSON when Accept header is set."""
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database",
        MagicMock(get_row_count=MagicMock(return_value=0)),
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.allocator_ip", "1.2.3.4", raising=False
    )
    monkeypatch.setattr("lablink_allocator_service.main.key_name", "k", raising=False)
    monkeypatch.setattr(
        "lablink_allocator_service.main.ENVIRONMENT", "test", raising=False
    )

    class R:
        def __init__(self, out="OK"):
            self.stdout, self.stderr = out, ""
            self.returncode = 0

    mock_run.side_effect = [
        R("OK"),               # terraform plan -out
        R(CLEAN_PLAN_JSON),    # terraform show -json
        R("apply success"),    # terraform apply <planfile>
    ]

    headers = {**admin_headers, **JSON_ACCEPT}
    resp = client.post(POST_ENDPOINT, headers=headers, data={"num_vms": "2"})

    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["status"] == "success"
    assert "apply success" in body["output"]


def test_launch_json_missing_num_vms(client, admin_headers):
    """Test missing num_vms returns JSON 400 when Accept header is set."""
    headers = {**admin_headers, **JSON_ACCEPT}
    resp = client.post(POST_ENDPOINT, headers=headers, data={})

    assert resp.status_code == 400
    body = json.loads(resp.data)
    assert body["status"] == "error"
    assert "required" in body["error"].lower()


def test_launch_json_invalid_num_vms(client, admin_headers):
    """Test invalid num_vms returns JSON 400 when Accept header is set."""
    headers = {**admin_headers, **JSON_ACCEPT}

    resp = client.post(POST_ENDPOINT, headers=headers, data={"num_vms": "0"})
    assert resp.status_code == 400
    body = json.loads(resp.data)
    assert body["status"] == "error"
    assert "greater than 0" in body["error"]

    resp = client.post(POST_ENDPOINT, headers=headers, data={"num_vms": "abc"})
    assert resp.status_code == 400
    body = json.loads(resp.data)
    assert body["status"] == "error"
    assert "valid integer" in body["error"].lower()


def test_launch_json_missing_allocator_outputs(
    client, admin_headers, monkeypatch, tmp_path
):
    """Test missing allocator outputs returns JSON 500."""
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database",
        MagicMock(get_row_count=lambda: 0),
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.allocator_ip", "", raising=False
    )
    monkeypatch.setattr("lablink_allocator_service.main.key_name", None, raising=False)

    headers = {**admin_headers, **JSON_ACCEPT}
    resp = client.post(POST_ENDPOINT, headers=headers, data={"num_vms": "1"})

    assert resp.status_code == 500
    body = json.loads(resp.data)
    assert body["status"] == "error"
    assert "Allocator outputs not found" in body["error"]


@patch("lablink_allocator_service.providers.aws.check_support_nvidia", return_value=False)
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_launch_json_apply_failure(
    mock_run, mock_check_support_nvidia, client, admin_headers, monkeypatch, tmp_path
):
    """Test Terraform apply failure returns JSON 500."""
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database",
        MagicMock(get_row_count=lambda: 0),
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.allocator_ip", "1.2.3.4", raising=False
    )
    monkeypatch.setattr("lablink_allocator_service.main.key_name", "k", raising=False)
    monkeypatch.setattr(
        "lablink_allocator_service.main.ENVIRONMENT", "test", raising=False
    )

    def side_effect(cmd, **kwargs):
        if cmd[1] == "plan":
            return MagicMock(stdout="OK", stderr="", returncode=0)
        if cmd[1] == "show":
            # SG audit must pass so the flow reaches apply.
            return MagicMock(stdout=CLEAN_PLAN_JSON, stderr="", returncode=0)
        raise subprocess.CalledProcessError(
            1, cmd, stderr="Error: resource already exists"
        )

    mock_run.side_effect = side_effect

    headers = {**admin_headers, **JSON_ACCEPT}
    resp = client.post(POST_ENDPOINT, headers=headers, data={"num_vms": "1"})

    assert resp.status_code == 500
    body = json.loads(resp.data)
    assert body["status"] == "error"
    assert "resource already exists" in body["error"]


@patch("lablink_allocator_service.providers.aws.upload_to_s3")
@patch("lablink_allocator_service.providers.aws.check_support_nvidia", return_value=True)
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_launch_json_unexpected_error(
    mock_run,
    mock_check_support_nvidia,
    mock_upload_to_s3,
    client,
    admin_headers,
    monkeypatch,
    tmp_path,
):
    """Test unexpected error (e.g. S3 failure) returns JSON 500."""
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database",
        MagicMock(get_row_count=MagicMock(return_value=0)),
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.allocator_ip", "1.2.3.4", raising=False
    )
    monkeypatch.setattr("lablink_allocator_service.main.key_name", "k", raising=False)
    monkeypatch.setattr(
        "lablink_allocator_service.main.ENVIRONMENT", "test", raising=False
    )

    class R:
        def __init__(self, out="OK"):
            self.stdout, self.stderr = out, ""
            self.returncode = 0

    # plan + show return a clean (audit-passing) plan; apply succeeds;
    # the S3 upload then blows up with AccessDenied (the path under test).
    mock_run.side_effect = [
        R("OK"),               # terraform plan -out
        R(CLEAN_PLAN_JSON),    # terraform show -json
        R("apply success"),    # terraform apply <planfile>
    ]
    mock_upload_to_s3.side_effect = Exception("AccessDenied: s3:PutObject")

    headers = {**admin_headers, **JSON_ACCEPT}
    resp = client.post(POST_ENDPOINT, headers=headers, data={"num_vms": "1"})

    assert resp.status_code == 500
    body = json.loads(resp.data)
    assert body["status"] == "error"
    assert "AccessDenied" in body["error"]


# ------------------------------------------------------------------
# Pre-apply SG audit gate
# ------------------------------------------------------------------

VIOLATING_PLAN_JSON = json.dumps({
    "resource_changes": [
        {
            "address": "aws_security_group.lablink_sg",
            "type": "aws_security_group",
            "name": "lablink_sg",
            "change": {
                "actions": ["create"],
                "before": None,
                "after": {
                    "ingress": [
                        {
                            "from_port": 6080, "to_port": 6080, "protocol": "tcp",
                            "cidr_blocks": ["0.0.0.0/0"],
                            "ipv6_cidr_blocks": [],
                        },
                    ],
                },
            },
        },
    ],
})


@patch("lablink_allocator_service.providers.aws.upload_to_s3")
@patch("lablink_allocator_service.providers.aws.check_support_nvidia", return_value=True)
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_launch_aborts_on_sg_audit_failure(
    mock_run,
    mock_check_support_nvidia,
    mock_upload_to_s3,
    client,
    admin_headers,
    monkeypatch,
    tmp_path,
):
    """If terraform plan shows a violating ingress on a protected
    port, /api/launch aborts with 400 and never invokes terraform
    apply. The gate is the whole point of Task 19."""
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr(
        "lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir
    )
    _wire_aws_provider(monkeypatch, terraform_dir)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database",
        MagicMock(get_row_count=MagicMock(return_value=0)),
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.allocator_ip", "1.2.3.4",
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.key_name", "my-key", raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.ENVIRONMENT", "test", raising=False,
    )

    class R:
        def __init__(self, out="OK"):
            self.stdout, self.stderr, self.returncode = out, "", 0

    # Plan succeeds (writes the file); show returns the violating JSON;
    # the audit then aborts the flow before apply is ever invoked.
    mock_run.side_effect = [
        R("OK"),                  # terraform plan -out
        R(VIOLATING_PLAN_JSON),   # terraform show -json (fed to audit)
    ]

    headers = {**admin_headers, **JSON_ACCEPT}
    resp = client.post(
        POST_ENDPOINT, headers=headers, data={"num_vms": "1"}
    )

    assert resp.status_code == 400
    body = json.loads(resp.data)
    assert body["status"] == "error"
    assert "6080" in body["error"]  # error mentions the offending port

    # Confirm apply was not invoked — only plan + show ran.
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[0][0][0][1] == "plan"
    assert mock_run.call_args_list[1][0][0][1] == "show"
    # S3 upload also must not have been called when apply was skipped.
    mock_upload_to_s3.assert_not_called()


@patch("lablink_allocator_service.providers.aws.upload_to_s3")
@patch("lablink_allocator_service.providers.aws.check_support_nvidia", return_value=True)
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_launch_aborts_on_sg_audit_failure_html(
    mock_run,
    mock_check_support_nvidia,
    mock_upload_to_s3,
    client,
    admin_headers,
    monkeypatch,
    tmp_path,
):
    """Same gate, browser path: a violating plan returns 400 with an
    HTML error message that names the offending port."""
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr(
        "lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir
    )
    _wire_aws_provider(monkeypatch, terraform_dir)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database",
        MagicMock(get_row_count=MagicMock(return_value=0)),
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.allocator_ip", "1.2.3.4",
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.key_name", "my-key", raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.ENVIRONMENT", "test", raising=False,
    )

    class R:
        def __init__(self, out="OK"):
            self.stdout, self.stderr, self.returncode = out, "", 0

    mock_run.side_effect = [
        R("OK"),                  # terraform plan -out
        R(VIOLATING_PLAN_JSON),   # terraform show -json (fed to audit)
    ]

    resp = client.post(
        POST_ENDPOINT, headers=admin_headers, data={"num_vms": "1"}
    )
    assert resp.status_code == 400
    assert b"6080" in resp.data
    # Plan + show ran; apply did not.
    assert mock_run.call_count == 2
    mock_upload_to_s3.assert_not_called()


@patch("lablink_allocator_service.providers.aws.upload_to_s3")
@patch("lablink_allocator_service.providers.aws.check_support_nvidia", return_value=True)
@patch("lablink_allocator_service.providers.aws.get_instance_timings",
       return_value={"vm-1": {"start_time": "2025-10-30T12:00:00Z",
                              "end_time": "2025-10-30T12:01:00Z",
                              "seconds": 60.0}})
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_launch_writes_register_token_to_tfvars(
    mock_run,
    mock_get_names,
    mock_get_ids,
    mock_get_timings,
    mock_check_support_nvidia,
    mock_upload_to_s3,
    client,
    admin_headers,
    monkeypatch,
    tmp_path,
):
    """launch() must write register_token = "..." into terraform.runtime.tfvars."""
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database",
        MagicMock(get_row_count=MagicMock(return_value=0)),
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
    monkeypatch.setattr(
        "lablink_allocator_service.main.REGISTER_TOKEN", "test-register-token-value", raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.AGENT_TOKEN", "test-agent-token-value", raising=False
    )

    class R:
        def __init__(self, out="OK"):
            self.stdout, self.stderr, self.returncode = out, "", 0

    mock_run.side_effect = [
        R("OK"),
        R(CLEAN_PLAN_JSON),
        R("\x1b[32mapply success\x1b[0m"),
    ]

    resp = client.post(POST_ENDPOINT, headers=admin_headers, data={"num_vms": "1"})
    assert resp.status_code == 200

    tfvars = (terraform_dir / "terraform.runtime.tfvars").read_text()
    assert 'register_token = "test-register-token-value"' in tfvars
    assert 'agent_token = "test-agent-token-value"' in tfvars


@patch("lablink_allocator_service.providers.aws.upload_to_s3")
@patch("lablink_allocator_service.providers.aws.check_support_nvidia", return_value=True)
@patch("lablink_allocator_service.providers.aws.get_instance_timings",
       return_value={"vm-1": {"start_time": "2025-10-30T12:00:00Z",
                              "end_time": "2025-10-30T12:01:00Z",
                              "seconds": 60.0}})
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_launch_writes_agent_token_to_tfvars_additively(
    mock_run,
    mock_get_names,
    mock_get_ids,
    mock_get_timings,
    mock_check_support_nvidia,
    mock_upload_to_s3,
    client,
    admin_headers,
    monkeypatch,
    tmp_path,
):
    """Regression: launch() must write agent_token = "<main.AGENT_TOKEN>" into
    terraform.runtime.tfvars so the client agent receives AGENT_TOKEN env via
    the bundled user_data. Guards the D1 shipping-blocker wiring: if the
    AGENT_TOKEN tfvars thread is ever removed, every /api/session/start 500s.
    """
    terraform_dir = tmp_path / "terraform"
    terraform_dir.mkdir()
    monkeypatch.setattr("lablink_allocator_service.main.TERRAFORM_DIR", terraform_dir)
    _wire_aws_provider(monkeypatch, terraform_dir)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database",
        MagicMock(get_row_count=MagicMock(return_value=0)),
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
    monkeypatch.setattr(
        "lablink_allocator_service.main.AGENT_TOKEN", "test-agent-token-value", raising=False
    )

    class R:
        def __init__(self, out="OK"):
            self.stdout, self.stderr, self.returncode = out, "", 0

    mock_run.side_effect = [
        R("OK"),
        R(CLEAN_PLAN_JSON),
        R("\x1b[32mapply success\x1b[0m"),
    ]

    resp = client.post(POST_ENDPOINT, headers=admin_headers, data={"num_vms": "1"})
    assert resp.status_code == 200

    from lablink_allocator_service import main

    tfvars = (terraform_dir / "terraform.runtime.tfvars").read_text()
    # agent_token carries main.AGENT_TOKEN ...
    assert f'agent_token = "{main.AGENT_TOKEN}"' in tfvars
    assert 'agent_token = "test-agent-token-value"' in tfvars
    # api_token is retired (PR D4) — must NOT appear in tfvars.
    assert "api_token" not in tfvars


def test_terraform_threads_agent_token_through_user_data():
    """Static-content guard for the AGENT_TOKEN Terraform wiring.

    Catches typos/renames in the templatefile var name, variables.tf,
    or user_data.sh's docker-run `-e` line that would slip past both
    `terraform validate` (HCL only) and the runtime tfvars-write test
    above (which only pins the .tfvars line). After PR D4, api_token is
    retired from the terraform template — only agent_token remains.
    """
    import re
    from pathlib import Path

    tf_dir = (
        Path(__file__).resolve().parents[1]
        / "src" / "lablink_allocator_service" / "terraform"
    )
    variables = (tf_dir / "variables.tf").read_text()
    main_tf = (tf_dir / "main.tf").read_text()
    user_data = (tf_dir / "user_data.sh").read_text()

    # variable declared
    assert 'variable "agent_token"' in variables
    # passed into the user_data templatefile vars map (HCL aligns the =;
    # match whitespace-tolerantly so an alignment touch-up does not fail).
    assert re.search(r"agent_token\s*=\s*var\.agent_token", main_tf)
    # injected on the client docker run
    assert '-e AGENT_TOKEN="${agent_token}"' in user_data
    # After PR D4, api_token is retired from the bundled terraform template.
    assert '-e API_TOKEN="${api_token}"' not in user_data
