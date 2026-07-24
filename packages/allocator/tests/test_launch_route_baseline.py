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

def test_launch_submits_job_and_returns_202(launch_setup, client, admin_headers):
    """The route no longer blocks on Terraform — it submits a job and
    returns immediately with a job id.

    `main.operations_worker` is patched here (like every other test below)
    because the module-level global is `None` until the real allocator's
    `main()` initializes it at process startup; tests never call `main()`,
    so the route would otherwise hit `AttributeError` on `None.submit`.
    """
    with _provider_happy_path_patches(), patch(
        "lablink_allocator_service.main.operations_worker"
    ) as mock_worker:
        mock_worker.submit.return_value = 42
        r = client.post(
            "/api/launch",
            headers={**admin_headers, "Accept": "application/json"},
            data={"num_vms": "2"},
        )

    assert r.status_code == 202, (
        f"Expected 202, got {r.status_code}: {r.get_data(as_text=True)[:500]}"
    )
    body = r.get_json()
    assert body["status"] == "queued"
    assert isinstance(body["job_id"], int)


def test_launch_redirects_browser_client_with_job_id(
    launch_setup, client, admin_headers,
):
    """A non-JSON (browser form) submit gets a redirect carrying the job id,
    not a rendered terraform-output page."""
    with _provider_happy_path_patches(), patch(
        "lablink_allocator_service.main.operations_worker"
    ) as mock_worker:
        mock_worker.submit.return_value = 7
        r = client.post(
            "/api/launch", headers=admin_headers, data={"num_vms": "1"},
            follow_redirects=False,
        )

    assert r.status_code == 302
    assert r.headers["Location"].startswith("/admin/instances?job=")


def test_launch_closure_calls_aws_utils_and_writes_timings(
    launch_setup, client, admin_headers,
):
    """Capture the closure passed to operations_worker.submit(fn=...) and
    invoke it directly — this is what actually runs on the background
    thread, so it must still do everything the old inline route body did:
    call the AWS utils, run plan/show/apply in order, audit the SG plan,
    and write timing rows per host."""
    from unittest.mock import patch

    with _provider_happy_path_patches() as mocks, patch(
        "lablink_allocator_service.main.operations_worker"
    ) as mock_worker:
        mock_worker.submit.return_value = 42
        r = client.post(
            "/api/launch", headers=admin_headers, data={"num_vms": "1"},
        )
        assert r.status_code == 302

        mock_worker.submit.assert_called_once()
        call_kwargs = mock_worker.submit.call_args.kwargs
        assert call_kwargs["op_type"] == "apply"
        assert call_kwargs["params"] == '{"num_vms": 1}'
        fn = call_kwargs["fn"]

        output = fn()

    mocks["nvidia"].assert_called()
    mocks["sg"].assert_called()
    mocks["s3"].assert_called()
    assert output == "apply success"

    db = launch_setup["database"]
    assert db.update_terraform_timing.call_count == 1


def test_launch_closure_runs_plan_show_apply_in_order(
    launch_setup, client, admin_headers,
):
    """Baseline preserved: terraform plan -> show -json -> apply, in order."""
    from unittest.mock import patch

    with _provider_happy_path_patches() as mocks, patch(
        "lablink_allocator_service.main.operations_worker"
    ) as mock_worker:
        client.post("/api/launch", headers=admin_headers, data={"num_vms": "1"})
        fn = mock_worker.submit.call_args.kwargs["fn"]
        fn()

        calls = mocks["run"].call_args_list
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

        plan_idx, show_idx, apply_idx = (
            index_of("plan"), index_of("show"), index_of("apply"),
        )
        assert plan_idx != -1 and show_idx != -1 and apply_idx != -1
        assert plan_idx < show_idx < apply_idx


def test_launch_closure_wraps_sg_audit_failure(launch_setup, client, admin_headers):
    """SGAuditFailure inside the closure is reformatted into a RuntimeError
    with the same user-facing message the old synchronous route produced,
    so it lands in operations.error with useful detail intact.

    audit_terraform_plan runs between the `show -json` and `apply` calls
    inside provider.provision_hosts, so this must override just that one
    call while every other provider dependency stays mocked to the happy
    path — and the closure must be invoked in the SAME `with` block that
    sets those patches up, not after they've been torn down, or fn() will
    hit unmocked subprocess.run/upload_to_s3/etc. calls."""
    from unittest.mock import patch
    from lablink_allocator_service.utils.sg_audit import SGAuditFailure

    with _provider_happy_path_patches(), patch(
        "lablink_allocator_service.providers.aws.audit_terraform_plan",
        side_effect=SGAuditFailure("port 6080 exposed"),
    ), patch("lablink_allocator_service.main.operations_worker") as mock_worker:
        client.post("/api/launch", headers=admin_headers, data={"num_vms": "1"})
        fn = mock_worker.submit.call_args.kwargs["fn"]

        with pytest.raises(
            RuntimeError, match="Security-group audit refused the plan"
        ):
            fn()


def test_launch_closure_wraps_terraform_failure(launch_setup, client, admin_headers):
    """CalledProcessError inside the closure is reformatted with the
    ANSI-stripped stderr, matching the old synchronous route's error text."""
    import subprocess
    from unittest.mock import patch

    with patch(
        "lablink_allocator_service.providers.aws.upload_to_s3", return_value=None,
    ), patch(
        "lablink_allocator_service.providers.aws.current_instance_security_group",
        return_value="sg-allocator-test",
    ), patch(
        "lablink_allocator_service.providers.aws.check_support_nvidia",
        return_value=True,
    ), patch(
        "lablink_allocator_service.providers.aws.subprocess.run",
        side_effect=subprocess.CalledProcessError(
            1, ["terraform", "apply"], stderr="\x1b[31mError: boom\x1b[0m",
        ),
    ), patch(
        "lablink_allocator_service.main.operations_worker"
    ) as mock_worker:
        client.post("/api/launch", headers=admin_headers, data={"num_vms": "1"})
        fn = mock_worker.submit.call_args.kwargs["fn"]

        # fn() must be invoked while the subprocess.run/upload_to_s3/etc.
        # patches above are still active — calling it after this `with`
        # block exits would hit real, unmocked subprocess/AWS calls.
        with pytest.raises(RuntimeError, match="Terraform failed: Error: boom"):
            fn()


def test_launch_returns_409_when_operation_in_progress(
    launch_setup, client, admin_headers,
):
    from unittest.mock import patch
    from lablink_allocator_service.operations_db import OperationInProgress

    with patch(
        "lablink_allocator_service.main.operations_worker"
    ) as mock_worker:
        mock_worker.submit.side_effect = OperationInProgress(job_id=3)
        r = client.post(
            "/api/launch",
            headers={**admin_headers, "Accept": "application/json"},
            data={"num_vms": "1"},
        )

    assert r.status_code == 409
    body = r.get_json()
    assert body["job_id"] == 3
    assert "already in progress" in body["error"]


def test_launch_returns_405_when_provider_cannot_provision(
    launch_setup, client, admin_headers,
):
    """After Task 6, the route returns 405 when the provider can't provision."""
    from lablink_allocator_service import main

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


def test_launch_redirects_with_error_code_when_provider_cannot_provision(
    launch_setup, client, admin_headers,
):
    """A browser (non-JSON) submit against a provider that can't provision
    hosts must get a plain redirect (no status-code override) so a real
    browser actually follows it — not a 405 dashboard.html render."""
    from lablink_allocator_service import main

    fake_provider = type("FakeProvider", (), {
        "can_provision_hosts": False,
        "can_destroy_hosts": True,
        "can_recover_hosts": False,
        "name": "manual",
    })()
    main.app.config["LABLINK_PROVIDER"] = fake_provider

    r = client.post(
        "/api/launch", headers=admin_headers, data={"num_vms": "1"},
        follow_redirects=False,
    )

    assert r.status_code == 302
    assert r.headers["Location"] == "/admin/instances?error=launch_unsupported"


def test_launch_redirects_with_error_code_when_operation_in_progress(
    launch_setup, client, admin_headers,
):
    """A browser (non-JSON) submit that races an in-progress operation must
    get a plain redirect (no status-code override) so a real browser
    actually follows it — not a 409 dashboard.html render."""
    from lablink_allocator_service.operations_db import OperationInProgress

    with patch(
        "lablink_allocator_service.main.operations_worker"
    ) as mock_worker:
        mock_worker.submit.side_effect = OperationInProgress(job_id=3)
        r = client.post(
            "/api/launch", headers=admin_headers, data={"num_vms": "1"},
            follow_redirects=False,
        )

    assert r.status_code == 302
    assert (
        r.headers["Location"]
        == "/admin/instances?error=already_in_progress&job_id=3"
    )


def test_launch_closure_base64_encodes_success_check(
    launch_setup, client, admin_headers, monkeypatch,
):
    """main.py's launch() must base64-encode a non-empty success_check into
    the spec dict, the same way routes/registration.py already does for the
    BYO path (test_registration_api.py::test_register_response_includes_startup_script_when_enabled)
    — this closes the asymmetric coverage the final review flagged.

    Rather than reusing `_provider_happy_path_patches()` (which mocks
    AWSProvider's internals so provision_hosts's real implementation can
    run), this test swaps the whole provider for a minimal fake. `spec` is
    built by `launch()` itself before `provider.provision_hosts(...)` is
    even called, so a fake provider that just records its `spec` kwarg is
    enough to verify main.py's own encoding line — no need to also exercise
    AWSProvider's terraform/AWS plumbing.
    """
    import base64

    from lablink_allocator_service import main
    from lablink_allocator_service.providers.protocol import ProvisionResult

    monkeypatch.setattr(
        main.cfg.startup_script, "success_check", "sleap --version", raising=False
    )

    captured = {}

    class _FakeProvider:
        can_provision_hosts = True

        def provision_hosts(self, count, spec):
            captured["spec"] = spec
            return ProvisionResult(handles=[], timings={}, apply_stdout="ok")

    monkeypatch.setitem(main.app.config, "LABLINK_PROVIDER", _FakeProvider())

    with patch("lablink_allocator_service.main.operations_worker") as mock_worker:
        client.post("/api/launch", headers=admin_headers, data={"num_vms": "1"})
        fn = mock_worker.submit.call_args.kwargs["fn"]
        fn()

    assert "spec" in captured, "provision_hosts was never called"
    assert (
        base64.b64decode(captured["spec"]["startup_success_check_b64"])
        == b"sleap --version"
    )
