"""AWSProvider.provision_hosts after wiring: should drive the same
boto3/terraform calls /api/launch did, returning a ProvisionResult."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import pytest
from lablink_allocator_service.providers.aws import AWSProvider
from lablink_allocator_service.providers.protocol import (
    ClientHandle,
    ProvisionResult,
)


def _make_spec():
    return {
        "allocator_ip": "1.2.3.4",
        "allocator_url": "https://example",
        "machine_type": "g4dn.xlarge",
        "image_name": "img:tag",
        "repository": "repo",
        "client_ami_id": "ami-abc",
        "subject_software": "sleap",
        "resource_prefix": "sleap-lablink-test",
        "cloud_init_output_log_group": "lg",
        "startup_on_error": "continue",
        "agent_token": "agent-tok",
        "register_token": "reg-tok",
        "deployment_name": "test",
        "bucket_name": "test-bucket",
        "environment": "test",
    }


@pytest.fixture
def aws_provider(tmp_path):
    return AWSProvider(region="us-west-2", terraform_dir=tmp_path)


@pytest.fixture
def all_aws_mocks():
    """Patch every external dep AWSProvider.provision_hosts touches."""
    def fake_subprocess(cmd, **kwargs):
        result = MagicMock()
        if any("show" in str(c) for c in cmd):
            result.stdout = '{"resource_changes": []}'
        else:
            result.stdout = "Apply complete (mocked)"
        result.stderr = ""
        result.returncode = 0
        return result

    patches = {
        "subprocess_run": patch(
            "lablink_allocator_service.providers.aws.subprocess.run",
            side_effect=fake_subprocess,
        ),
        "upload_to_s3": patch(
            "lablink_allocator_service.providers.aws.upload_to_s3"
        ),
        "current_instance_security_group": patch(
            "lablink_allocator_service.providers.aws.current_instance_security_group",
            return_value="sg-foo",
        ),
        "check_support_nvidia": patch(
            "lablink_allocator_service.providers.aws.check_support_nvidia",
            return_value=True,
        ),
        "get_instance_timings": patch(
            "lablink_allocator_service.providers.aws.get_instance_timings",
            return_value={},
        ),
        "get_instance_ids": patch(
            "lablink_allocator_service.providers.aws.get_instance_ids",
            return_value=["i-1"],
        ),
        "get_instance_names": patch(
            "lablink_allocator_service.providers.aws.get_instance_names",
            return_value=["host-1"],
        ),
        "audit_terraform_plan": patch(
            "lablink_allocator_service.providers.aws.audit_terraform_plan",
            return_value=None,
        ),
    }
    started = {k: p.start() for k, p in patches.items()}
    yield started
    for p in patches.values():
        try:
            p.stop()
        except RuntimeError:
            pass


def test_provision_hosts_returns_provision_result(aws_provider, all_aws_mocks):
    result = aws_provider.provision_hosts(count=1, spec=_make_spec())
    assert isinstance(result, ProvisionResult)
    assert all(isinstance(h, ClientHandle) for h in result.handles)
    assert result.handles[0].id == "i-1"
    assert result.handles[0].hostname == "host-1"


def test_provision_hosts_writes_runtime_tfvars(aws_provider, all_aws_mocks, tmp_path):
    aws_provider.provision_hosts(count=2, spec=_make_spec())
    tfvars_path = tmp_path / "terraform.runtime.tfvars"
    assert tfvars_path.exists()
    content = tfvars_path.read_text()
    for key in [
        "allocator_ip", "allocator_url", "machine_type", "image_name",
        "repository", "client_ami_id", "subject_software", "resource_prefix",
        "gpu_support", "cloud_init_output_log_group", "region",
        "startup_on_error", "agent_token", "register_token",
    ]:
        assert f"{key} = " in content, f"missing key {key}"


def test_provision_hosts_runs_terraform_plan_show_apply(
    aws_provider, all_aws_mocks,
):
    aws_provider.provision_hosts(count=1, spec=_make_spec())
    cmds = [list(c.args[0]) for c in all_aws_mocks["subprocess_run"].call_args_list
            if c.args and isinstance(c.args[0], list)]
    def find(verb):
        for i, cmd in enumerate(cmds):
            if cmd and cmd[0] == "terraform" and verb in cmd:
                return i
        return -1
    plan_idx, show_idx, apply_idx = find("plan"), find("show"), find("apply")
    assert -1 not in (plan_idx, show_idx, apply_idx)
    assert plan_idx < show_idx < apply_idx


def test_provision_hosts_uploads_to_s3(aws_provider, all_aws_mocks):
    aws_provider.provision_hosts(count=1, spec=_make_spec())
    all_aws_mocks["upload_to_s3"].assert_called_once()


def test_provision_hosts_passes_count_to_terraform(aws_provider, all_aws_mocks):
    aws_provider.provision_hosts(count=5, spec=_make_spec())
    cmds = [list(c.args[0]) for c in all_aws_mocks["subprocess_run"].call_args_list
            if c.args and isinstance(c.args[0], list)]
    # Find any terraform invocation that has the instance_count var
    has_count = any(
        any("-var=instance_count=5" == arg for arg in cmd)
        for cmd in cmds
    )
    assert has_count, f"-var=instance_count=5 not passed: {cmds}"


def test_provision_hosts_skips_sg_id_off_ec2(aws_provider):
    """When current_instance_security_group raises NotOnEC2Error, the
    -var=allocator_sg_id= flag should NOT be added to terraform commands."""
    from lablink_allocator_service.utils.aws_utils import NotOnEC2Error

    def fake_subprocess(cmd, **kwargs):
        result = MagicMock()
        if any("show" in str(c) for c in cmd):
            result.stdout = '{"resource_changes": []}'
        else:
            result.stdout = "Apply complete"
        result.stderr = ""
        result.returncode = 0
        return result

    with patch(
        "lablink_allocator_service.providers.aws.subprocess.run",
        side_effect=fake_subprocess,
    ) as run_mock, patch(
        "lablink_allocator_service.providers.aws.upload_to_s3"
    ), patch(
        "lablink_allocator_service.providers.aws.current_instance_security_group",
        side_effect=NotOnEC2Error("not on EC2"),
    ), patch(
        "lablink_allocator_service.providers.aws.check_support_nvidia",
        return_value=True,
    ), patch(
        "lablink_allocator_service.providers.aws.get_instance_timings",
        return_value={},
    ), patch(
        "lablink_allocator_service.providers.aws.get_instance_ids",
        return_value=[],
    ), patch(
        "lablink_allocator_service.providers.aws.get_instance_names",
        return_value=[],
    ), patch(
        "lablink_allocator_service.providers.aws.audit_terraform_plan",
        return_value=None,
    ):
        aws_provider.provision_hosts(count=1, spec=_make_spec())

    cmds = [list(c.args[0]) for c in run_mock.call_args_list
            if c.args and isinstance(c.args[0], list)]
    # No -var=allocator_sg_id= flag in any invocation
    assert all(
        all("allocator_sg_id" not in arg for arg in cmd)
        for cmd in cmds
    ), f"allocator_sg_id was passed despite NotOnEC2Error: {cmds}"
