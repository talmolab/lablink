"""AWSProvider.destroy_hosts after wiring: runs `terraform destroy
-auto-approve -var-file=...` (+ allocator_sg_id var on EC2), returns
a DestroyResult with ANSI-stripped stdout."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import pytest
from lablink_allocator_service.providers.aws import AWSProvider
from lablink_allocator_service.providers.protocol import (
    ClientHandle,
    DestroyResult,
)
from lablink_allocator_service.utils.aws_utils import NotOnEC2Error


@pytest.fixture
def aws_provider_with_tfvars(tmp_path):
    """Provider with a stub runtime tfvars file present (so destroy proceeds)."""
    (tmp_path / "terraform.runtime.tfvars").write_text("# stub\n")
    return AWSProvider(region="us-west-2", terraform_dir=tmp_path)


def test_destroy_hosts_returns_destroy_result(aws_provider_with_tfvars):
    handles = [ClientHandle(id="i-1", hostname="h-1")]
    with patch(
        "lablink_allocator_service.providers.aws.subprocess.run",
        return_value=MagicMock(stdout="Destroy complete", stderr="", returncode=0),
    ), patch(
        "lablink_allocator_service.providers.aws.current_instance_security_group",
        return_value="sg-allocator",
    ):
        result = aws_provider_with_tfvars.destroy_hosts(handles)
    assert isinstance(result, DestroyResult)
    assert "Destroy complete" in result.stdout


def test_destroy_hosts_runs_terraform_destroy_with_sg_var_on_ec2(
    aws_provider_with_tfvars,
):
    handles = [ClientHandle(id="i-1", hostname="h-1")]
    with patch(
        "lablink_allocator_service.providers.aws.subprocess.run",
        return_value=MagicMock(stdout="ok", stderr="", returncode=0),
    ) as run_mock, patch(
        "lablink_allocator_service.providers.aws.current_instance_security_group",
        return_value="sg-allocator",
    ):
        aws_provider_with_tfvars.destroy_hosts(handles)
    cmd = run_mock.call_args_list[0].args[0]
    assert cmd[:3] == ["terraform", "destroy", "-auto-approve"]
    assert "-var-file=terraform.runtime.tfvars" in cmd
    assert "-var=allocator_sg_id=sg-allocator" in cmd


def test_destroy_hosts_skips_sg_var_off_ec2(aws_provider_with_tfvars):
    handles = [ClientHandle(id="i-1", hostname="h-1")]
    with patch(
        "lablink_allocator_service.providers.aws.subprocess.run",
        return_value=MagicMock(stdout="ok", stderr="", returncode=0),
    ) as run_mock, patch(
        "lablink_allocator_service.providers.aws.current_instance_security_group",
        side_effect=NotOnEC2Error("not on EC2"),
    ):
        aws_provider_with_tfvars.destroy_hosts(handles)
    cmd = run_mock.call_args_list[0].args[0]
    assert all("allocator_sg_id" not in arg for arg in cmd)


def test_destroy_hosts_ansi_strips_stdout(aws_provider_with_tfvars):
    """ANSI escape codes in terraform output should be removed."""
    ansi_output = "\x1b[32mDestroy complete!\x1b[0m"
    with patch(
        "lablink_allocator_service.providers.aws.subprocess.run",
        return_value=MagicMock(stdout=ansi_output, stderr="", returncode=0),
    ), patch(
        "lablink_allocator_service.providers.aws.current_instance_security_group",
        return_value="sg-foo",
    ):
        result = aws_provider_with_tfvars.destroy_hosts([])
    assert "\x1b[" not in result.stdout
    assert "Destroy complete!" in result.stdout


def test_destroy_hosts_raises_filenotfound_when_no_tfvars(tmp_path):
    """Provider raises FileNotFoundError when runtime tfvars is missing —
    the route's pre-refactor `has_runtime_tfvars` check maps to this."""
    # tmp_path is empty — no terraform.runtime.tfvars
    p = AWSProvider(region="us-west-2", terraform_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        p.destroy_hosts([])
