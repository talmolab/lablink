"""AWSProvider.destroy_hosts after wiring: runs a `terraform plan -destroy`
+ `terraform show -json` + `terraform apply <planfile>` sequence (+
allocator_sg_id var on EC2), returns a DestroyResult with ANSI-stripped
stdout, and reports progress via progress_callback."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock
import pytest
from lablink_allocator_service.providers.aws import AWSProvider
from lablink_allocator_service.providers.protocol import (
    ClientHandle,
    DestroyResult,
)
from lablink_allocator_service.utils.aws_utils import NotOnEC2Error


class _FakeCompletedPopen:
    """Minimal stand-in for subprocess.Popen matching _run_streamed's
    expected surface — see providers/test_run_streamed.py for the
    canonical version."""

    def __init__(self, stdout_text="", stderr_text="", returncode=0):
        import io
        self.stdout = io.StringIO(stdout_text)
        self.stderr = io.StringIO(stderr_text)
        self._returncode = returncode

    def wait(self):
        return self._returncode


@pytest.fixture
def aws_provider_with_tfvars(tmp_path):
    """Provider with a stub runtime tfvars file present (so destroy proceeds)."""
    (tmp_path / "terraform.runtime.tfvars").write_text("# stub\n")
    return AWSProvider(region="us-west-2", terraform_dir=tmp_path)


def _fake_run_factory(show_json='{"resource_changes": []}'):
    """Builds a subprocess.run side_effect that returns valid plan JSON for
    the `terraform show -json ...` call and a generic "OK" stdout for any
    other call (e.g. `terraform plan -destroy ...`)."""

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.stdout = show_json if "show" in cmd else "OK"
        result.stderr = ""
        result.returncode = 0
        return result

    return fake_run


def test_destroy_hosts_returns_destroy_result(aws_provider_with_tfvars):
    handles = [ClientHandle(id="i-1", hostname="h-1")]
    with patch(
        "lablink_allocator_service.providers.aws.subprocess.run",
        side_effect=_fake_run_factory(),
    ), patch(
        "lablink_allocator_service.providers.aws.subprocess.Popen",
        return_value=_FakeCompletedPopen(stdout_text="Destroy complete"),
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
        side_effect=_fake_run_factory(),
    ) as run_mock, patch(
        "lablink_allocator_service.providers.aws.subprocess.Popen",
        return_value=_FakeCompletedPopen(stdout_text="ok"),
    ) as popen_mock, patch(
        "lablink_allocator_service.providers.aws.current_instance_security_group",
        return_value="sg-allocator",
    ):
        aws_provider_with_tfvars.destroy_hosts(handles)

    # plan -destroy carries the var-file and sg var.
    plan_cmd = run_mock.call_args_list[0].args[0]
    assert plan_cmd[:3] == ["tofu", "plan", "-destroy"]
    assert "-var-file=terraform.runtime.tfvars" in plan_cmd
    assert "-var=allocator_sg_id=sg-allocator" in plan_cmd

    # apply (of the saved destroy plan) streams via Popen.
    apply_cmd = popen_mock.call_args.args[0]
    assert apply_cmd[:2] == ["tofu", "apply"]
    assert "-auto-approve" in apply_cmd


def test_destroy_hosts_skips_sg_var_off_ec2(aws_provider_with_tfvars):
    handles = [ClientHandle(id="i-1", hostname="h-1")]
    with patch(
        "lablink_allocator_service.providers.aws.subprocess.run",
        side_effect=_fake_run_factory(),
    ) as run_mock, patch(
        "lablink_allocator_service.providers.aws.subprocess.Popen",
        return_value=_FakeCompletedPopen(stdout_text="ok"),
    ), patch(
        "lablink_allocator_service.providers.aws.current_instance_security_group",
        side_effect=NotOnEC2Error("not on EC2"),
    ):
        aws_provider_with_tfvars.destroy_hosts(handles)
    plan_cmd = run_mock.call_args_list[0].args[0]
    assert all("allocator_sg_id" not in arg for arg in plan_cmd)


def test_destroy_hosts_ansi_strips_stdout(aws_provider_with_tfvars):
    """ANSI escape codes in terraform output should be removed."""
    ansi_output = "\x1b[32mDestroy complete!\x1b[0m"

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.stdout = (
            '{"resource_changes": []}' if "show" in cmd else "OK"
        )
        result.stderr = ""
        result.returncode = 0
        return result

    with patch(
        "lablink_allocator_service.providers.aws.subprocess.run",
        side_effect=fake_run,
    ), patch(
        "lablink_allocator_service.providers.aws.subprocess.Popen",
        return_value=_FakeCompletedPopen(stdout_text=ansi_output),
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


def test_destroy_hosts_reports_progress_via_callback(aws_provider_with_tfvars):
    plan_json = json.dumps({
        "resource_changes": [
            {"type": "aws_instance", "address": "aws_instance.client[0]",
             "change": {"actions": ["delete"]}},
            {"type": "aws_security_group", "address": "aws_security_group.client",
             "change": {"actions": ["delete"]}},
        ]
    })
    destroy_stdout = (
        "aws_instance.client[0]: Destruction complete after 8s\n"
        "aws_security_group.client: Destruction complete after 2s\n"
    )

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        if "show" in cmd:
            result.stdout = plan_json
        else:
            result.stdout = "OK"
        result.stderr = ""
        result.returncode = 0
        return result

    progress_calls = []

    with patch(
        "lablink_allocator_service.providers.aws.subprocess.run",
        side_effect=fake_run,
    ), patch(
        "lablink_allocator_service.providers.aws.subprocess.Popen",
        return_value=_FakeCompletedPopen(stdout_text=destroy_stdout),
    ), patch(
        "lablink_allocator_service.providers.aws.current_instance_security_group",
        return_value="sg-foo",
    ):
        aws_provider_with_tfvars.destroy_hosts(
            [],
            progress_callback=lambda done, total: progress_calls.append(
                (done, total)
            ),
        )

    assert progress_calls[0] == (0, 2)
    assert progress_calls[-1] == (2, 2)
    assert len(progress_calls) == 3
