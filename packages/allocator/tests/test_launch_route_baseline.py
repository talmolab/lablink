"""Pre-refactor regression baseline for /api/launch.

These assertions MUST hold byte-identical before AND after the SR-F1 rewire
(Tasks 5–6 of PR D5). If they break, the AWS path's behavior has changed and
the refactor is wrong.

Today's /api/launch route inlines:
- check_support_nvidia (boto3 / AWS metadata)
- current_instance_security_group (IMDSv2)
- terraform.runtime.tfvars writes (14 specific keys)
- terraform plan + show -json + apply (3 subprocess.run calls, plus a 4th
  from get_instance_timings: terraform output -json)
- audit_terraform_plan (SG guard)
- upload_to_s3 (state archival)
- database.update_terraform_timing (DB write per host)

After Tasks 5-6, /api/launch calls provider.provision_hosts(...) which
performs the same effects polymorphically. These tests assert the
behavior, not the exact code shape, so they survive both states.

Post-Task-6 note: all AWS-specific calls (check_support_nvidia,
upload_to_s3, audit_terraform_plan, subprocess.run for terraform) now
execute inside AWSProvider.provision_hosts — patch them in the
providers.aws namespace, not the main namespace.  get_instance_timings,
get_instance_ids, and get_instance_names are also patched in the
providers.aws namespace since that's where they're imported.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal clean plan JSON the SG auditor accepts (same shape as test_terraform_api.py)
# ---------------------------------------------------------------------------
_CLEAN_PLAN_JSON = json.dumps({
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

_TIMING_DATA = {
    "vm-1": {
        "start_time": "2025-10-30T12:00:00Z",
        "end_time": "2025-10-30T12:01:00Z",
        "seconds": 60.0,
    }
}
_TIMING_JSON = json.dumps(_TIMING_DATA)


# ---------------------------------------------------------------------------
# Shared helper: build the three subprocess.run return values the provider needs
# for plan/show/apply (called in providers.aws.subprocess).
# get_instance_timings / get_instance_ids / get_instance_names are patched
# separately since they call terraform_utils.subprocess.
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, stdout="OK", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _provider_subprocess_side_effects(plan_json=_CLEAN_PLAN_JSON):
    """Return FakeResult objects in the order AWSProvider.provision_hosts
    calls subprocess.run:
    1. terraform plan -no-color -out tfplan.binary ...
    2. terraform show -json tfplan.binary
    3. terraform apply -auto-approve tfplan.binary
    """
    return [
        _FakeResult("OK"),             # plan
        _FakeResult(plan_json),        # show -json → SG audit
        _FakeResult("apply success"),  # apply
    ]


# ---------------------------------------------------------------------------
# Context manager: patch all provider-level dependencies for a happy-path launch
# ---------------------------------------------------------------------------

def _provider_happy_path_patches():
    """Return a context manager stack for patching AWSProvider internals.

    Patches (in order, outermost → innermost decorator order):
    - providers.aws.upload_to_s3
    - providers.aws.current_instance_security_group
    - providers.aws.check_support_nvidia
    - providers.aws.subprocess.run  (plan/show/apply only)
    - providers.aws.get_instance_timings
    - providers.aws.get_instance_ids
    - providers.aws.get_instance_names
    """
    import contextlib

    @contextlib.contextmanager
    def _stack():
        with patch("lablink_allocator_service.providers.aws.upload_to_s3", return_value=None) as ms3, \
             patch("lablink_allocator_service.providers.aws.current_instance_security_group",
                   return_value="sg-allocator-test") as msg, \
             patch("lablink_allocator_service.providers.aws.check_support_nvidia",
                   return_value=True) as mnv, \
             patch("lablink_allocator_service.providers.aws.subprocess.run") as mrun, \
             patch("lablink_allocator_service.providers.aws.get_instance_timings",
                   return_value=_TIMING_DATA) as mtimings, \
             patch("lablink_allocator_service.providers.aws.get_instance_ids",
                   return_value=[]) as mids, \
             patch("lablink_allocator_service.providers.aws.get_instance_names",
                   return_value=[]) as mnames:
            mrun.side_effect = _provider_subprocess_side_effects()
            yield {
                "s3": ms3, "sg": msg, "nvidia": mnv,
                "run": mrun, "timings": mtimings,
                "ids": mids, "names": mnames,
            }
    return _stack()


# ---------------------------------------------------------------------------
# Fixture: common monkeypatches every launch baseline test needs
# ---------------------------------------------------------------------------

@pytest.fixture
def launch_setup(app, monkeypatch, tmp_path):
    """Standard monkeypatches for /api/launch baseline tests.

    Depends on `app` so these monkeypatches run after the `app` fixture
    sets up the Flask test context — preventing the `app` fixture's direct
    `main.database = MagicMock()` assignment from overwriting our fake_db.

    Uses the project's existing `client` + `admin_headers` fixture pattern
    (not a custom admin_authed_client) because that's what the project uses.

    Post-Task-6: also replaces LABLINK_PROVIDER in app.config with a fresh
    AWSProvider pointing at tmp_path, so provision_hosts writes tfvars and
    calls terraform in the tmp directory rather than the real TERRAFORM_DIR.
    """
    from lablink_allocator_service import main
    from lablink_allocator_service.providers.aws import AWSProvider

    monkeypatch.setattr(main, "TERRAFORM_DIR", tmp_path)
    monkeypatch.setattr(main, "allocator_ip", "1.2.3.4", raising=False)
    monkeypatch.setattr(main, "key_name", "test-key", raising=False)
    monkeypatch.setattr(main, "ENVIRONMENT", "test", raising=False)

    # Wire a fresh AWSProvider pointing at tmp_path so provision_hosts
    # writes tfvars and runs terraform relative to tmp_path.
    provider = AWSProvider(region="us-west-2", terraform_dir=str(tmp_path))
    monkeypatch.setitem(main.app.config, "LABLINK_PROVIDER", provider)

    fake_db = MagicMock()
    fake_db.get_row_count.return_value = 0
    fake_db.update_terraform_timing = MagicMock()
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    return {"tmp_path": tmp_path, "database": fake_db}


# ---------------------------------------------------------------------------
# Baseline tests
# ---------------------------------------------------------------------------

def test_launch_calls_aws_utils(launch_setup, client, admin_headers):
    """Baseline: check_support_nvidia, current_instance_security_group,
    and upload_to_s3 are all called during a successful /api/launch."""
    with _provider_happy_path_patches() as mocks:
        r = client.post("/api/launch", headers=admin_headers, data={"num_vms": "2"})

        assert r.status_code == 200, (
            f"Expected 200, got {r.status_code}: {r.get_data(as_text=True)[:500]}"
        )
        mocks["nvidia"].assert_called()
        mocks["sg"].assert_called()
        mocks["s3"].assert_called()


def test_launch_writes_runtime_tfvars_with_expected_keys(
    launch_setup, client, admin_headers,
):
    """Baseline: terraform.runtime.tfvars contains the 14 expected keys."""
    with _provider_happy_path_patches():
        client.post("/api/launch", headers=admin_headers, data={"num_vms": "1"})

    tfvars_path = launch_setup["tmp_path"] / "terraform.runtime.tfvars"
    assert tfvars_path.exists(), "runtime tfvars was not written"
    content = tfvars_path.read_text()

    for key in [
        "allocator_ip", "allocator_url", "machine_type", "image_name",
        "repository", "client_ami_id", "subject_software", "resource_prefix",
        "gpu_support", "cloud_init_output_log_group", "region",
        "startup_on_error", "agent_token", "register_token",
    ]:
        assert f"{key} = " in content, (
            f"key '{key}' missing from runtime tfvars; got:\n{content}"
        )


def test_launch_runs_terraform_plan_show_apply_sequence(
    launch_setup, client, admin_headers,
):
    """Baseline: terraform plan → show -json → apply in that order."""
    with _provider_happy_path_patches() as mocks:
        client.post("/api/launch", headers=admin_headers, data={"num_vms": "1"})

        calls = mocks["run"].call_args_list
        # Extract the command list from each call (first positional arg)
        cmds = [
            list(c.args[0])
            for c in calls
            if c.args and isinstance(c.args[0], (list, tuple))
        ]

        def index_of(verb):
            for i, cmd in enumerate(cmds):
                if cmd and cmd[0] == "terraform" and verb in cmd:
                    return i
            return -1

        plan_idx = index_of("plan")
        show_idx = index_of("show")
        apply_idx = index_of("apply")

        assert plan_idx != -1, f"terraform plan not called; cmds: {cmds}"
        assert show_idx != -1, f"terraform show not called; cmds: {cmds}"
        assert apply_idx != -1, f"terraform apply not called; cmds: {cmds}"
        assert plan_idx < show_idx < apply_idx, (
            f"terraform plan/show/apply not in order: "
            f"plan={plan_idx}, show={show_idx}, apply={apply_idx}; cmds: {cmds}"
        )


def test_launch_calls_sg_audit_with_plan_json(launch_setup, client, admin_headers):
    """Baseline: audit_terraform_plan is called with the parsed plan JSON dict."""
    with _provider_happy_path_patches():
        with patch("lablink_allocator_service.providers.aws.audit_terraform_plan") as mock_audit:
            mock_audit.return_value = None
            client.post("/api/launch", headers=admin_headers, data={"num_vms": "1"})
            mock_audit.assert_called_once()
            call_arg = mock_audit.call_args[0][0]
            assert isinstance(call_arg, dict), (
                f"audit_terraform_plan expected a dict, got "
                f"{type(call_arg).__name__}: {call_arg}"
            )


def test_launch_calls_update_terraform_timing_per_host(
    launch_setup, client, admin_headers,
):
    """Baseline: database.update_terraform_timing is called once per host
    returned by get_instance_timings."""
    with _provider_happy_path_patches():
        client.post("/api/launch", headers=admin_headers, data={"num_vms": "1"})

    db = launch_setup["database"]
    # _TIMING_DATA has one host ("vm-1"), so update_terraform_timing must be
    # called exactly once.
    assert db.update_terraform_timing.call_count == 1, (
        f"Expected 1 update_terraform_timing call, "
        f"got {db.update_terraform_timing.call_count}"
    )


def test_launch_returns_405_when_provider_cannot_provision(
    launch_setup, client, admin_headers,
):
    """After Task 6, the route returns 405 when the provider can't provision."""
    from lablink_allocator_service import main

    # Force can_provision_hosts=False via a fake provider in app.config
    fake_provider = type("FakeProvider", (), {
        "can_provision_hosts": False,
        "can_destroy_hosts": True,
        "can_recover_hosts": False,
        "name": "manual",
    })()
    main.app.config["LABLINK_PROVIDER"] = fake_provider

    r = client.post(
        "/api/launch", data={"num_vms": "1"},
        headers={**admin_headers, "Accept": "application/json"},
    )
    assert r.status_code == 405, \
        f"expected 405 when provider can't provision; got {r.status_code}"
