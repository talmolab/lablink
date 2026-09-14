"""Unit tests for the Fig 2 harness (paper/fig2-harness/).

Shared across Fig 2's tasks -- Task 1 covers poll_pool.py's parsing and
preflight. Later tasks (trajectory.py, claim_burst.py, plot_fig2.py) append
their own sections to this same file; do not remove sections you did not
write.

Run: cd paper/fig2-harness && uv run --with pytest pytest test_fig2.py -v
"""

import csv
import subprocess
from datetime import datetime, timezone

import pytest

from protocol import (
    ARM_SIZES,
    DEFAULT_POLL_INTERVAL_S,
    READY_TIMEOUT_S,
    REPLICATE_ORDERS,
    SOAK_SECONDS,
    validate_contract,
)

from poll_pool import (
    OPERATION_COLUMNS,
    POLL_COLUMNS,
    TRAJECTORY_COLUMNS,
    append_operation_snapshot,
    append_poll_observation,
    append_trajectory,
    operation_snapshot_cmd,
    parse_operation_snapshot,
    parse_snapshot,
    preflight_columns,
    snapshot_cmd,
    to_epoch_utc,
)

HEADER = (
    "hostname,status,healthy,reboot_count,tofuapplystarttime,tofuapplyendtime,"
    "cloudinitstarttime,cloudinitendtime,containerstarttime,containerendtime,"
    "totalstartupdurationseconds,createdat,sessionstartedat,last_seen_at,"
    "machine_identity"
)


def test_protocol_contract_is_fixed_and_counterbalanced():
    assert ARM_SIZES == (5, 10, 30, 60)
    assert READY_TIMEOUT_S == 15 * 60
    assert SOAK_SECONDS == 10 * 60
    assert DEFAULT_POLL_INTERVAL_S == 5.0
    assert len(REPLICATE_ORDERS) == 3
    assert all(set(order) == set(ARM_SIZES) for order in REPLICATE_ORDERS)
    validate_contract()


def test_naive_timestamp_is_read_as_utc():
    # The allocator writes phase timestamps without a tzinfo. Read as
    # anything but UTC, June's seat claims land before its VMs were ready.
    assert (
        to_epoch_utc("2026-06-11T08:39:40")
        == datetime(2026, 6, 11, 8, 39, 40, tzinfo=timezone.utc).timestamp()
    )


def test_aware_timestamp_agrees_with_naive():
    assert to_epoch_utc("2026-06-11T08:39:40+00:00") == to_epoch_utc(
        "2026-06-11T08:39:40"
    )


def test_blank_timestamp_is_none():
    assert to_epoch_utc("") is None
    assert to_epoch_utc("   ") is None


def test_parse_snapshot_stamps_every_row_with_run_identity():
    text = (
        HEADER
        + "\n"
        + (
            "vm-1,running,Healthy,0,2026-06-11T08:39:40,2026-06-11T08:40:10,"
            "2026-06-11T08:40:12,2026-06-11T08:41:53,2026-06-11T08:41:55,"
            "2026-06-11T08:44:50,310,2026-06-11T08:40:10.351570,,"
            "2026-06-11T08:45:00,i-0123456789abcdef0\n"
        )
    )
    rows = parse_snapshot(
        text,
        poll_epoch=1_781_000_000.0,
        arm_n=5,
        replicate=1,
        image_digest="sha256:abc",
        clock_offset_s=0.4,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["hostname"] == "vm-1"
    assert row["arm_n"] == 5
    assert row["replicate"] == 1
    assert row["image_digest"] == "sha256:abc"
    assert row["clock_offset_s"] == 0.4
    assert row["poll_epoch"] == 1_781_000_000.0
    assert row["reboot_count"] == 0
    assert row["session_started_epoch"] is None
    assert row["container_end_epoch"] == to_epoch_utc("2026-06-11T08:44:50")
    assert row["machine_identity"] == "i-0123456789abcdef0"
    assert set(row) == set(TRAJECTORY_COLUMNS)


def test_preflight_names_the_renamed_column():
    # terraformapplystarttime -> tofuapplystarttime. A stale query fails
    # on the VM, mid-arm, after the money is spent.
    stale = HEADER.replace("tofuapplystarttime", "terraformapplystarttime")
    with pytest.raises(RuntimeError, match="tofuapplystarttime"):
        preflight_columns(stale)
    preflight_columns(HEADER)  # current schema passes


def test_append_trajectory_writes_header_once(tmp_path):
    out = tmp_path / "traj.csv"
    text = HEADER + "\nvm-1,running,Healthy,0,,,,,,,,,,\n"
    for poll in (1.0, 2.0):
        append_trajectory(
            parse_snapshot(
                text,
                poll_epoch=poll,
                arm_n=5,
                replicate=1,
                image_digest="sha256:abc",
                clock_offset_s=0.0,
            ),
            out,
        )
    lines = out.read_text().splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("poll_epoch")
    assert [r["poll_epoch"] for r in csv.DictReader(out.open())] == ["1.0", "2.0"]


def test_snapshot_cmd_uses_the_ps_handle_not_a_guessed_name():
    # Postgres runs inside the allocator container, and commands/logs.py:217
    # already resolves it as `docker ps -q | head -1`. A guessed
    # `lablink-db` name does not exist on an AWS deploy.
    cmd = snapshot_cmd("alloc.example.org", "/keys/id_rsa")
    joined = " ".join(cmd)
    assert "docker ps -q | head -1" in joined
    assert "lablink-db" not in joined
    assert "docker exec --user postgres" in joined
    assert "psql -d lablink_db" in joined
    assert "psql -U lablink" not in joined
    assert cmd[0] == "ssh"


def test_empty_poll_is_recorded_instead_of_disappearing(tmp_path):
    out = tmp_path / "polls.csv"
    append_poll_observation(
        out,
        poll_epoch=100.0,
        arm_n=5,
        replicate=1,
        image_digest="sha256:abc",
        observed_hosts=0,
        ok=True,
    )
    rows = list(csv.DictReader(out.open()))
    assert list(rows[0]) == POLL_COLUMNS
    assert rows[0]["observed_hosts"] == "0"
    assert rows[0]["ok"] == "True"


def test_operation_snapshot_records_timing_progress_and_error(tmp_path):
    text = (
        "id,op_type,status,created_at,started_at,finished_at,error,"
        "resources_total,resources_completed\n"
        "7,launch,failed,2026-06-11T08:39:39,2026-06-11T08:39:40,"
        "2026-06-11T08:40:10,capacity unavailable,60,17\n"
    )
    rows = parse_operation_snapshot(
        text,
        poll_epoch=200.0,
        arm_n=60,
        replicate=2,
        image_digest="sha256:abc",
    )
    assert rows[0]["operation_id"] == 7
    assert rows[0]["started_epoch"] == to_epoch_utc("2026-06-11T08:39:40")
    assert rows[0]["finished_epoch"] == to_epoch_utc("2026-06-11T08:40:10")
    assert rows[0]["error"] == "capacity unavailable"
    assert rows[0]["resources_completed"] == 17
    assert set(rows[0]) == set(OPERATION_COLUMNS)

    out = tmp_path / "operations.csv"
    append_operation_snapshot(rows, out)
    assert len(list(csv.DictReader(out.open()))) == 1


def test_operation_query_is_allowlisted_and_omits_sensitive_blobs():
    joined = " ".join(operation_snapshot_cmd("alloc.example.org", "/keys/id_rsa"))
    assert "FROM operations" in joined
    assert "params" not in joined
    assert "output" not in joined
    assert "created_by" not in joined


# --- Task 2: trajectory derivations -------------------------------------

from trajectory import (  # noqa: E402
    arm_summary,
    by_host,
    load_trajectory,
    readiness_epoch,
    retry_events,
    terminal_states,
    time_to_all_ready,
)
from poll_pool import append_trajectory as _append  # noqa: E402


def _traj(tmp_path, snapshots):
    """snapshots: list of (poll_epoch, [row-dict-overrides]) -> written CSV."""
    out = tmp_path / "t.csv"
    for poll_epoch, hosts in snapshots:
        rows = []
        for host in hosts:
            row = {c: None for c in TRAJECTORY_COLUMNS}
            row.update(
                {
                    "poll_epoch": poll_epoch,
                    "arm_n": 5,
                    "replicate": 1,
                    "image_digest": "sha256:abc",
                    "clock_offset_s": 0.0,
                    "status": "running",
                    "healthy": "Healthy",
                    "reboot_count": 0,
                }
            )
            row.update(host)
            rows.append(row)
        _append(rows, out)
    return load_trajectory(out)


def test_readiness_is_first_collector_observation_of_running(tmp_path):
    rows = _traj(
        tmp_path,
        [
            (
                100.0,
                [
                    {
                        "hostname": "vm-1",
                        "status": "initializing",
                        "container_end_epoch": None,
                    }
                ],
            ),
            (
                105.0,
                [
                    {
                        "hostname": "vm-1",
                        "status": "running",
                        "container_end_epoch": 103.0,
                    }
                ],
            ),
        ],
    )
    assert readiness_epoch(by_host(rows)["vm-1"]) == 105.0


def test_a_host_that_never_readies_is_reported_not_dropped(tmp_path):
    rows = _traj(
        tmp_path,
        [
            (100.0, [{"hostname": "vm-1", "status": "pending"}]),
            (105.0, [{"hostname": "vm-1", "status": "failed"}]),
        ],
    )
    assert readiness_epoch(by_host(rows)["vm-1"]) is None
    terminal = terminal_states(rows)["vm-1"]
    assert terminal["ready"] is False
    assert terminal["status"] == "failed"


def test_a_host_that_vanishes_between_polls_is_a_retry_event(tmp_path):
    # The June survivorship lesson: a replaced VM leaves no row at all.
    rows = _traj(
        tmp_path,
        [
            (100.0, [{"hostname": "vm-1"}, {"hostname": "vm-2"}]),
            (105.0, [{"hostname": "vm-2"}]),
        ],
    )
    kinds = [(e["hostname"], e["kind"]) for e in retry_events(rows)]
    assert ("vm-1", "disappeared") in kinds


def test_empty_final_poll_can_prove_every_host_disappeared(tmp_path):
    rows = _traj(tmp_path, [(100.0, [{"hostname": "vm-1"}])])
    kinds = [event["kind"] for event in retry_events(rows, last_poll_epoch=105.0)]
    assert kinds == ["disappeared"]


def test_intermediate_disappearance_is_not_hidden_by_reappearance(tmp_path):
    rows = _traj(
        tmp_path,
        [
            (100.0, [{"hostname": "vm-1"}, {"hostname": "vm-2"}]),
            (105.0, [{"hostname": "vm-2"}]),
            (110.0, [{"hostname": "vm-1"}, {"hostname": "vm-2"}]),
        ],
    )
    events = retry_events(rows, poll_epochs=[100.0, 105.0, 110.0])
    assert {(event["hostname"], event["epoch"], event["kind"]) for event in events} >= {
        ("vm-1", 105.0, "disappeared")
    }


def test_reboot_count_increase_is_one_event(tmp_path):
    rows = _traj(
        tmp_path,
        [
            (100.0, [{"hostname": "vm-1", "reboot_count": 0}]),
            (105.0, [{"hostname": "vm-1", "reboot_count": 1}]),
            (110.0, [{"hostname": "vm-1", "reboot_count": 1}]),
        ],
    )
    events = [e for e in retry_events(rows) if e["kind"] == "reboot"]
    assert len(events) == 1
    assert events[0]["epoch"] == 105.0


def test_unhealthy_transition_is_an_event_and_recovery_is_not(tmp_path):
    rows = _traj(
        tmp_path,
        [
            (100.0, [{"hostname": "vm-1", "healthy": "Healthy"}]),
            (105.0, [{"hostname": "vm-1", "healthy": "Unhealthy"}]),
            (110.0, [{"hostname": "vm-1", "healthy": "Healthy"}]),
        ],
    )
    kinds = [e["kind"] for e in retry_events(rows)]
    assert kinds == ["unhealthy"]


def test_time_to_all_ready_is_set_by_the_last_host(tmp_path):
    rows = _traj(
        tmp_path,
        [
            (
                150.0,
                [
                    {"hostname": "vm-1", "status": "running"},
                    {"hostname": "vm-2", "status": "initializing"},
                ],
            ),
            (
                190.0,
                [
                    {"hostname": "vm-1", "status": "running"},
                    {"hostname": "vm-2", "status": "running"},
                ],
            ),
        ],
    )
    assert time_to_all_ready(rows, launch_epoch=100.0) == 90.0


def test_time_to_all_ready_is_none_when_a_host_never_readies(tmp_path):
    # Reporting the max over the ready subset would quietly reward failure.
    rows = _traj(
        tmp_path,
        [
            (
                200.0,
                [
                    {"hostname": "vm-1", "status": "running"},
                    {"hostname": "vm-2", "status": "failed"},
                ],
            )
        ],
    )
    assert time_to_all_ready(rows, launch_epoch=100.0) is None


def test_time_to_all_ready_requires_every_intended_host(tmp_path):
    rows = _traj(
        tmp_path,
        [(105.0, [{"hostname": "vm-1", "status": "running"}])],
    )
    assert time_to_all_ready(rows, launch_epoch=100.0, expected_n=2) is None


def test_arm_summary_counts_every_host(tmp_path):
    rows = _traj(
        tmp_path,
        [
            (
                200.0,
                [
                    {"hostname": "vm-1", "status": "running", "total_startup_s": 300.0},
                    {"hostname": "vm-2", "status": "running", "total_startup_s": 320.0},
                    {"hostname": "vm-3", "status": "failed"},
                ],
            )
        ],
    )
    summary = arm_summary(rows, launch_epoch=100.0, expected_n=5)
    assert summary["n_hosts"] == 3
    assert summary["n_ready"] == 2
    assert summary["n_missing"] == 2
    assert summary["n_never_ready"] == 3
    assert summary["failure_rate"] == 3 / 5
    assert summary["time_to_all_ready_s"] is None
    assert summary["startup_median_s"] == 310.0


def test_replacement_does_not_rescue_a_failed_intended_vm(tmp_path):
    rows = _traj(
        tmp_path,
        [
            (100.0, [{"hostname": "vm-original", "status": "failed"}]),
            (105.0, [{"hostname": "vm-replacement", "status": "running"}]),
        ],
    )
    summary = arm_summary(rows, launch_epoch=99.0, expected_n=1)
    assert summary["n_hosts"] == 2
    assert summary["n_never_ready"] == 1
    assert summary["failure_rate"] == 1.0
    assert summary["time_to_all_ready_s"] is None


def test_machine_identity_exposes_hostname_reuse(tmp_path):
    rows = _traj(
        tmp_path,
        [
            (100.0, [{"hostname": "seat-1", "machine_identity": "i-old"}]),
            (105.0, [{"hostname": "seat-1", "machine_identity": "i-new"}]),
        ],
    )
    assert set(by_host(rows)) == {"i-old", "i-new"}


def test_identity_registration_does_not_double_count_one_vm(tmp_path):
    rows = _traj(
        tmp_path,
        [
            (
                100.0,
                [{"hostname": "seat-1", "machine_identity": None,
                  "status": "initializing"}],
            ),
            (
                105.0,
                [{"hostname": "seat-1", "machine_identity": "i-01",
                  "status": "running"}],
            ),
        ],
    )
    hosts = by_host(rows)
    assert set(hosts) == {"i-01"}
    assert len(hosts["i-01"]) == 2


def test_post_ready_regression_is_an_instability(tmp_path):
    rows = _traj(
        tmp_path,
        [
            (100.0, [{"hostname": "vm-1", "status": "running"}]),
            (105.0, [{"hostname": "vm-1", "status": "failed"}]),
        ],
    )
    summary = arm_summary(rows, launch_epoch=99.0, expected_n=1)
    assert summary["n_unstable"] == 1
    assert summary["instability_rate"] == 1.0


# --- Task 3: concurrent seat claims ------------------------------------

from claim_burst import (  # noqa: E402
    CLAIM_COLUMNS,
    claim_one,
    classify_claim,
    make_emails,
    write_claims,
)


class _Response:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def test_only_303_is_a_success():
    assert classify_claim(303, "") == "claimed"
    assert classify_claim(200, "unexpected error") == "unexpected_200"
    assert classify_claim(503, "No seats available") == "no_seats"
    assert classify_claim(503, "Couldn't prepare your seat") == "rotation_failed"
    assert classify_claim(500, "boom") == "http_error"


def test_claim_does_not_follow_redirects_and_records_both_clocks():
    calls = []
    ticks = iter((100.0, 100.25))

    def requester(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(303)

    row = claim_one(
        "https://allocator.example.org",
        "fig2@example.org",
        requester=requester,
        clock=lambda: next(ticks),
    )
    assert calls[0][0].endswith("/api/request_vm")
    assert calls[0][1]["allow_redirects"] is False
    assert calls[0][1]["data"] == {"email": "fig2@example.org"}
    assert row["request_epoch"] == 100.0
    assert row["response_epoch"] == 100.25
    assert row["latency_s"] == 0.25
    assert row["outcome"] == "claimed"


def test_claim_exception_is_a_written_failure(tmp_path):
    ticks = iter((100.0, 100.5))

    def requester(*args, **kwargs):
        raise TimeoutError("timed out")

    row = claim_one(
        "https://allocator.example.org",
        "fig2@example.org",
        requester=requester,
        clock=lambda: next(ticks),
    )
    assert row["outcome"] == "request_error"
    assert "timed out" in row["error"]
    out = tmp_path / "claims.csv"
    write_claims([row], out)
    assert list(csv.DictReader(out.open()))[0]["outcome"] == "request_error"
    assert list(csv.DictReader(out.open()))[0].keys() == set(CLAIM_COLUMNS)


def test_claim_emails_are_unique_and_arm_identifiable():
    emails = make_emails(60, arm_n=60, replicate=3, run_id="run42")
    assert len(emails) == len(set(emails)) == 60
    assert all("run42-n60-r3" in email for email in emails)


# --- Task 4: failure-safe arm metadata ---------------------------------

import json  # noqa: E402

from run_arm import (  # noqa: E402
    ArmRecorder,
    _validate_config,
    allocator_clock_probe,
    availability_zones,
    build_parser,
    command_set,
    validate_arm,
)


def test_arm_recorder_preserves_metadata_when_launch_raises(tmp_path):
    meta = tmp_path / "meta.json"
    events = tmp_path / "events.jsonl"
    ticks = iter((10.0, 11.0, 12.0))
    with pytest.raises(RuntimeError, match="launch failed"):
        with ArmRecorder(
            meta,
            events,
            {"arm_n": 5, "replicate": 1},
            clock=lambda: next(ticks),
        ) as recorder:
            recorder.event("launch_requested")
            raise RuntimeError("launch failed")

    saved = json.loads(meta.read_text())
    assert saved["status"] == "failed"
    assert saved["error"] == "RuntimeError: launch failed"
    phases = [json.loads(line)["phase"] for line in events.read_text().splitlines()]
    assert phases == ["arm_started", "launch_requested", "arm_failed"]


def test_arm_validation_requires_fixed_matrix_and_digest():
    validate_arm(30, 1, "ghcr.io/talmolab/client@sha256:" + "a" * 64)
    with pytest.raises(ValueError, match="fixed arm sizes"):
        validate_arm(7, 1, "x@sha256:" + "a" * 64)
    with pytest.raises(ValueError, match="immutable image digest"):
        validate_arm(30, 1, "ghcr.io/talmolab/client:latest")
    with pytest.raises(ValueError, match="replicate must be"):
        validate_arm(30, 4, "x@sha256:" + "a" * 64)


def test_default_runner_records_az_without_enforcing_a_literal():
    args = build_parser().parse_args(
        [
            "--arm-n",
            "5",
            "--replicate",
            "1",
            "--image-digest",
            "x@sha256:" + "a" * 64,
            "--config",
            "/tmp/config.yaml",
            "--template-sha",
            "abc",
            "--instance-type",
            "g4dn.xlarge",
            "--region",
            "us-west-2",
        ]
    )
    assert args.actual_az is None
    assert not hasattr(args, "soak_seconds")


def test_frozen_labels_must_match_structured_config(tmp_path):
    config = tmp_path / "config.yaml"
    digest = "image@sha256:" + "a" * 64
    config.write_text(
        "machine:\n  image: " + digest + "\n  machine_type: g4dn.xlarge\n"
        "app:\n  region: us-west-2\n"
    )
    _validate_config(
        config,
        image_digest=digest,
        instance_type="g4dn.xlarge",
        region="us-west-2",
    )
    with pytest.raises(ValueError, match="machine.machine_type"):
        _validate_config(
            config,
            image_digest=digest,
            instance_type="p3.2xlarge",
            region="us-west-2",
        )


def test_runner_commands_are_noninteractive_and_use_the_config(tmp_path):
    commands = command_set(30, tmp_path / "config.yaml")
    assert commands["launch"] == [
        "lablink",
        "client",
        "launch",
        "--num-vms",
        "30",
        "--config",
        str(tmp_path / "config.yaml"),
        "--verbose",
    ]
    assert "--yes" in commands["destroy"]


def test_runner_records_actual_availability_zones():
    def runner(command, **kwargs):
        assert command[:3] == ["aws", "ec2", "describe-instances"]
        assert "i-01" in command and "i-02" in command
        return subprocess.CompletedProcess(
            command, 0, '["us-west-2a", "us-west-2b"]', ""
        )

    assert availability_zones(["i-01", "i-02"], "us-west-2", runner=runner) == [
        "us-west-2a",
        "us-west-2b",
    ]


def test_allocator_clock_probe_uses_midpoint_offset():
    ticks = iter((100.0, 100.2))

    def runner(command, **kwargs):
        assert command[-1] == "date -u +%s.%N"
        return subprocess.CompletedProcess(command, 0, "100.15\n", "")

    result = allocator_clock_probe(
        "alloc.example.org",
        "/keys/id_rsa",
        runner=runner,
        clock=lambda: next(ticks),
    )
    assert result["round_trip_s"] == pytest.approx(0.2)
    assert result["offset_s"] == pytest.approx(0.05)


# --- Task 5: figure data and rendering ---------------------------------

from plot_fig2 import (  # noqa: E402
    _collector_health,
    _last_successful_poll,
    discover_runs,
    latest_operations,
    provisioning_duration,
    render_figure,
    summarize_run,
    validate_dataset,
)


def test_provisioning_uses_completed_apply_operation_after_launch():
    rows = [
        {
            "operation_id": 1,
            "op_type": "apply",
            "status": "succeeded",
            "created_epoch": 50.0,
            "started_epoch": 60.0,
            "finished_epoch": 80.0,
            "poll_epoch": 81.0,
        },
        {
            "operation_id": 2,
            "op_type": "apply",
            "status": "running",
            "created_epoch": 101.0,
            "started_epoch": 102.0,
            "finished_epoch": None,
            "poll_epoch": 110.0,
        },
        {
            "operation_id": 2,
            "op_type": "apply",
            "status": "succeeded",
            "created_epoch": 101.0,
            "started_epoch": 102.0,
            "finished_epoch": 142.0,
            "poll_epoch": 145.0,
        },
    ]
    latest = latest_operations(rows)
    assert len(latest) == 2
    assert provisioning_duration(latest, launch_epoch=100.0) == 40.0


def test_discovery_refuses_mixed_image_digests(tmp_path):
    for index, digest in enumerate(("sha256:a", "sha256:b"), start=1):
        run = tmp_path / f"run{index}"
        run.mkdir()
        (run / "meta.json").write_text(
            json.dumps(
                {
                    "status": "complete",
                    "arm_n": 5,
                    "replicate": index,
                    "image_digest": digest,
                    "started_epoch": 100.0,
                }
            )
        )
    with pytest.raises(ValueError, match="mixed image digests"):
        discover_runs(tmp_path)


def test_failed_arm_without_rows_keeps_all_intended_failures(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "meta.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "arm_n": 5,
                "replicate": 1,
                "image_digest": "sha256:a",
                "started_epoch": 100.0,
            }
        )
    )
    (run / "events.jsonl").write_text(
        json.dumps({"phase": "launch_requested", "epoch": 101.0}) + "\n"
    )
    summary = summarize_run(run)
    assert summary["n_never_ready"] == 5
    assert summary["failure_rate"] == 1.0
    assert summary["time_to_all_ready_s"] is None


def test_unattempted_arm_is_rejected_from_publication(tmp_path):
    with pytest.raises(ValueError, match="analysis-ineligible"):
        validate_dataset(
            [
                {
                    "run_dir": tmp_path / "dry-run",
                    "analysis_eligible": False,
                    "collector_reason": "poll ledger missing",
                    "arm_n": 5,
                    "replicate": 1,
                }
            ],
            allow_incomplete=True,
        )


def test_teardown_polls_are_excluded_from_disappearance_window(tmp_path):
    out = tmp_path / "polls.csv"
    for epoch, hosts in ((105.0, 5), (120.0, 0)):
        append_poll_observation(
            out,
            poll_epoch=epoch,
            arm_n=5,
            replicate=1,
            image_digest="sha256:a",
            observed_hosts=hosts,
            ok=True,
        )
    assert _last_successful_poll(out, before_epoch=110.0) == 105.0


def test_collector_health_rejects_three_consecutive_errors(tmp_path):
    out = tmp_path / "polls.csv"
    for epoch, ok in ((100.0, True), (105.0, False), (110.0, False), (115.0, False)):
        append_poll_observation(
            out,
            poll_epoch=epoch,
            arm_n=5,
            replicate=1,
            image_digest="sha256:a",
            observed_hosts=0,
            ok=ok,
        )
    valid, reason = _collector_health(
        out, launch_epoch=99.0, end_epoch=116.0, poll_interval_s=5.0
    )
    assert valid is False
    assert "consecutive poll errors" in reason


def test_figure_renderer_writes_pdf_and_300dpi_png(tmp_path):
    import matplotlib.pyplot as plt
    import numpy as np

    dashboard = tmp_path / "dashboard.png"
    plt.imsave(dashboard, np.ones((80, 160, 3)) * 0.25)
    summaries = [
        {
            "arm_n": n,
            "replicate": 1,
            "provisioning_time_s": 20.0 + n,
            "ready_times_s": [30.0 + seat for seat in range(n)],
            "time_to_all_ready_s": 30.0 + n,
            "n_never_ready": 0,
            "n_retried": 0,
            "expected_n": n,
            "ready_timeout_s": 900.0,
        }
        for n in ARM_SIZES
    ]
    events = [
        {"phase": "configure_started", "epoch": 0.0},
        {"phase": "configure_finished", "epoch": 10.0},
        {"phase": "deploy_started", "epoch": 10.0},
        {"phase": "deploy_finished", "epoch": 40.0},
        {"phase": "launch_requested", "epoch": 40.0},
        {"phase": "all_vms_ready", "epoch": 100.0},
    ]
    output = tmp_path / "fig2"
    render_figure(summaries, events, dashboard, output)
    assert output.with_suffix(".pdf").stat().st_size > 1_000
    assert output.with_suffix(".png").stat().st_size > 1_000
