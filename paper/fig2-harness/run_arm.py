#!/usr/bin/env python3
"""Run one Fig. 2 scaling arm with failure-safe evidence and teardown."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

from claim_burst import collect_claims, write_claims
from poll_pool import (
    append_operation_snapshot,
    parse_operation_snapshot,
    parse_snapshot,
    poll_once,
    poll_operations_once,
)
from protocol import (
    ARM_SIZES,
    DEFAULT_POLL_INTERVAL_S,
    READY_TIMEOUT_S,
    REPLICATE_ORDERS,
    SOAK_SECONDS,
)
from trajectory import by_host, load_trajectory, readiness_epoch


def validate_arm(arm_n: int, replicate: int, image_digest: str) -> None:
    if arm_n not in ARM_SIZES:
        raise ValueError(f"N must be one of the fixed arm sizes {ARM_SIZES}")
    if replicate not in range(1, len(REPLICATE_ORDERS) + 1):
        raise ValueError(f"replicate must be 1..{len(REPLICATE_ORDERS)}")
    if not re.search(r"@sha256:[0-9a-fA-F]{64}$", image_digest):
        raise ValueError("client image must be pinned by immutable image digest")


def command_set(arm_n: int, config: Path) -> dict[str, list[str]]:
    common = ["--config", str(config)]
    return {
        "launch": [
            "lablink",
            "client",
            "launch",
            "--num-vms",
            str(arm_n),
            *common,
            "--verbose",
        ],
        "destroy": [
            "lablink",
            "client",
            "destroy",
            *common,
            "--yes",
            "--verbose",
        ],
    }


def availability_zones(
    instance_ids: list[str],
    region: str,
    *,
    runner: Callable = subprocess.run,
) -> list[str]:
    """Resolve and retain the actual AZs used by this arm."""
    if not instance_ids:
        raise RuntimeError("no AWS instance identities were collected")
    command = [
        "aws",
        "ec2",
        "describe-instances",
        "--region",
        region,
        "--instance-ids",
        *sorted(set(instance_ids)),
        "--query",
        "Reservations[].Instances[].Placement.AvailabilityZone",
        "--output",
        "json",
    ]
    result = runner(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(
            f"AWS availability-zone query failed: {result.stderr.strip()}"
        )
    zones = sorted(set(json.loads(result.stdout)))
    if not zones:
        raise RuntimeError("AWS returned no availability zones for the arm")
    return zones


def allocator_clock_probe(
    host: str,
    ssh_key: str,
    *,
    runner: Callable = subprocess.run,
    clock: Callable[[], float] = time.time,
) -> dict[str, float]:
    """Estimate allocator-minus-collector clock offset at the SSH midpoint."""
    command = [
        "ssh",
        "-i",
        ssh_key,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=10",
        f"ubuntu@{host}",
        "date -u +%s.%N",
    ]
    before = clock()
    result = runner(command, capture_output=True, text=True, timeout=30)
    after = clock()
    if result.returncode:
        raise RuntimeError(f"allocator clock probe failed: {result.stderr.strip()}")
    remote_epoch = float(result.stdout.strip())
    return {
        "offset_s": remote_epoch - ((before + after) / 2),
        "round_trip_s": after - before,
    }


class ArmRecorder:
    """Persist metadata after every event, including exception exits."""

    def __init__(
        self,
        meta_path: Path,
        events_path: Path,
        metadata: dict,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.meta_path = Path(meta_path)
        self.events_path = Path(events_path)
        self.metadata = dict(metadata)
        self.clock = clock

    def _write_meta(self) -> None:
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.meta_path.with_suffix(self.meta_path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.metadata, indent=2, sort_keys=True) + "\n")
        temporary.replace(self.meta_path)

    def event(
        self,
        phase: str,
        *,
        epoch: float | None = None,
        **details,
    ) -> dict:
        event = {"phase": phase, "epoch": self.clock() if epoch is None else epoch}
        event.update(details)
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        self.metadata["last_event"] = event
        self._write_meta()
        return event

    def __enter__(self) -> ArmRecorder:
        self.metadata["status"] = "running"
        event = self.event("arm_started")
        self.metadata["started_epoch"] = event["epoch"]
        self._write_meta()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc is None:
            event = self.event("arm_completed")
            self.metadata["status"] = "complete"
            self.metadata["error"] = ""
        else:
            event = self.event("arm_failed", error=f"{exc_type.__name__}: {exc}")
            self.metadata["status"] = "failed"
            self.metadata["error"] = f"{exc_type.__name__}: {exc}"
        self.metadata["finished_epoch"] = event["epoch"]
        self._write_meta()
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _preflight_empty(
    host: str,
    ssh_key: str,
    *,
    arm_n: int,
    replicate: int,
    image_digest: str,
) -> None:
    now = time.time()
    rows = parse_snapshot(
        poll_once(host, ssh_key),
        poll_epoch=now,
        arm_n=arm_n,
        replicate=replicate,
        image_digest=image_digest,
        clock_offset_s=0.0,
    )
    if rows:
        raise RuntimeError(
            f"preflight requires an empty pool; observed {len(rows)} VMs"
        )
    operations = parse_operation_snapshot(
        poll_operations_once(host, ssh_key),
        poll_epoch=now,
        arm_n=arm_n,
        replicate=replicate,
        image_digest=image_digest,
    )
    active = [row for row in operations if row["status"] in {"queued", "running"}]
    if active:
        raise RuntimeError("preflight found a queued or running allocator operation")


def _run_logged(
    command: list[str], phase: str, recorder: ArmRecorder, log_path: Path
) -> None:
    recorder.event(f"{phase}_started", command=command)
    with log_path.open("a") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    recorder.event(f"{phase}_finished", exit_code=result.returncode)
    if result.returncode:
        raise RuntimeError(f"{phase} failed with exit code {result.returncode}")


def _wait_until_ready(
    trajectory_path: Path,
    expected_n: int,
    timeout_s: float,
    *,
    interval_s: float = 1.0,
    poller: subprocess.Popen | None = None,
) -> tuple[float, float]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if poller is not None and poller.poll() is not None:
            raise RuntimeError(f"trajectory collector exited with {poller.returncode}")
        if trajectory_path.exists():
            rows = load_trajectory(trajectory_path)
            hosts = by_host(rows)
            ready = [readiness_epoch(host_rows) for host_rows in hosts.values()]
            if len(hosts) == expected_n and all(value is not None for value in ready):
                ready_epochs = [value for value in ready if value is not None]
                return min(ready_epochs), max(ready_epochs)
        time.sleep(interval_s)
    raise TimeoutError(f"{expected_n} seats did not become ready within {timeout_s}s")


def _wait_for_fresh_file(path: Path, timeout_s: float, not_before_epoch: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if (
            path.is_file()
            and path.stat().st_size > 0
            and path.stat().st_mtime >= not_before_epoch
        ):
            return
        time.sleep(1.0)
    raise TimeoutError(
        f"dashboard screenshot was not captured within {timeout_s}s: {path}"
    )


def _metadata(args, run_id: str) -> dict:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "arm_n": args.arm_n,
        "replicate": args.replicate,
        "image_digest": args.image_digest,
        "lablink_sha": _git_sha(),
        "template_sha": args.template_sha,
        "config_path": str(args.config.resolve()),
        "config_sha256": _sha256(args.config),
        "instance_type": args.instance_type,
        "region": args.region,
        "expected_az": args.actual_az,
        "actual_azs": [],
        "poll_interval_s": DEFAULT_POLL_INTERVAL_S,
        "ready_timeout_s": READY_TIMEOUT_S,
        "soak_seconds": SOAK_SECONDS,
        "attempted": False,
    }


def _validate_config(
    path: Path, *, image_digest: str, instance_type: str, region: str
) -> None:
    import yaml

    config = yaml.safe_load(path.read_text()) or {}
    actual_image = (config.get("machine") or {}).get("image")
    actual_instance = (config.get("machine") or {}).get("machine_type")
    actual_region = (config.get("app") or {}).get("region")
    expected = {
        "machine.image": (actual_image, image_digest),
        "machine.machine_type": (actual_instance, instance_type),
        "app.region": (actual_region, region),
    }
    mismatches = [
        f"{field}={actual!r}, expected {wanted!r}"
        for field, (actual, wanted) in expected.items()
        if actual != wanted
    ]
    if mismatches:
        raise ValueError(
            "config does not match frozen run metadata: " + "; ".join(mismatches)
        )


def _record_actual_zones(
    recorder: ArmRecorder,
    trajectory_path: Path,
    region: str,
    expected_az: str | None,
) -> None:
    if recorder.metadata.get("actual_azs") or not trajectory_path.exists():
        return
    identities = sorted(
        {
            row["machine_identity"]
            for row in load_trajectory(trajectory_path)
            if row.get("machine_identity")
        }
    )
    if not identities:
        return
    zones = availability_zones(identities, region)
    if expected_az and any(zone != expected_az for zone in zones):
        raise RuntimeError(f"arm used AZs {zones}, expected only {expected_az}")
    recorder.metadata["actual_azs"] = zones
    recorder.event("availability_zones_recorded", zones=zones)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm-n", type=int, required=True)
    parser.add_argument("--replicate", type=int, required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--template-sha", required=True)
    parser.add_argument("--instance-type", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--actual-az")
    parser.add_argument("--data-dir", type=Path, default=Path("paper/fig2-harness/data"))
    parser.add_argument("--screenshot-path", type=Path)
    parser.add_argument("--screenshot-timeout", type=float, default=180.0)
    parser.add_argument("--skip-claims", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    validate_arm(args.arm_n, args.replicate, args.image_digest)
    if not args.config.is_file():
        parser.error(f"config file does not exist: {args.config}")
    try:
        _validate_config(
            args.config,
            image_digest=args.image_digest,
            instance_type=args.instance_type,
            region=args.region,
        )
    except ValueError as exc:
        parser.error(str(exc))

    os.umask(0o077)
    run_id = uuid.uuid4().hex[:10]
    arm_dir = args.data_dir / f"n{args.arm_n:03d}-r{args.replicate}-{run_id}"
    arm_dir.mkdir(parents=True, exist_ok=False)
    meta_path = arm_dir / "meta.json"
    events_path = arm_dir / "events.jsonl"
    trajectory_path = arm_dir / "trajectory.csv"
    polls_path = arm_dir / "polls.csv"
    operations_path = arm_dir / "operations.csv"
    claims_path = arm_dir / "claims.csv"
    log_path = arm_dir / "commands.log"
    commands = command_set(args.arm_n, args.config)

    try:
        with ArmRecorder(meta_path, events_path, _metadata(args, run_id)) as recorder:
            if args.dry_run:
                recorder.metadata["run_kind"] = "dry_run"
                recorder.event("dry_run", commands=commands)
                return 0

            host = os.environ["ALLOCATOR_HOST"]
            ssh_key = os.environ["SSH_KEY"]
            base_url = os.environ["ALLOCATOR_URL"]
            recorder.event("preflight_started")
            _preflight_empty(
                host,
                ssh_key,
                arm_n=args.arm_n,
                replicate=args.replicate,
                image_digest=args.image_digest,
            )
            recorder.event("preflight_finished")
            clock_start = allocator_clock_probe(host, ssh_key)
            recorder.metadata["allocator_clock_probe_start"] = clock_start
            recorder.event("allocator_clock_probed_start", **clock_start)

            poller_log = (arm_dir / "poller.log").open("a")
            poller = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).with_name("poll_pool.py")),
                    "--arm-n",
                    str(args.arm_n),
                    "--replicate",
                    str(args.replicate),
                    "--image-digest",
                    args.image_digest,
                    "--out",
                    str(trajectory_path),
                    "--polls-out",
                    str(polls_path),
                    "--operations-out",
                    str(operations_path),
                    "--clock-offset-s",
                    str(clock_start["offset_s"]),
                    "--interval",
                    str(DEFAULT_POLL_INTERVAL_S),
                ],
                stdout=poller_log,
                stderr=subprocess.STDOUT,
            )
            primary_error: BaseException | None = None
            try:
                recorder.metadata["attempted"] = True
                recorder.event("launch_requested", intended_n=args.arm_n)
                _run_logged(commands["launch"], "launch", recorder, log_path)
                first_ready, all_ready = _wait_until_ready(
                    trajectory_path, args.arm_n, READY_TIMEOUT_S, poller=poller
                )
                recorder.event("first_vm_ready", epoch=first_ready)
                recorder.event("all_vms_ready", epoch=all_ready)
                _record_actual_zones(
                    recorder, trajectory_path, args.region, args.actual_az
                )

                if not args.skip_claims:
                    recorder.event("claim_burst_started")
                    claims = collect_claims(
                        base_url,
                        count=args.arm_n,
                        arm_n=args.arm_n,
                        replicate=args.replicate,
                        run_id=run_id,
                    )
                    write_claims(claims, claims_path)
                    successes = sum(row["outcome"] == "claimed" for row in claims)
                    recorder.event(
                        "claim_burst_finished",
                        claimed=successes,
                        intended=args.arm_n,
                    )
                    if successes != args.arm_n:
                        raise RuntimeError(
                            f"claim burst granted {successes}/{args.arm_n} seats"
                        )

                if args.screenshot_path:
                    recorder.event(
                        "dashboard_screenshot_requested",
                        path=str(args.screenshot_path),
                    )
                    _wait_for_fresh_file(
                        args.screenshot_path,
                        args.screenshot_timeout,
                        recorder.metadata["started_epoch"],
                    )
                    retained_screenshot = arm_dir / "dashboard.png"
                    shutil.copy2(args.screenshot_path, retained_screenshot)
                    recorder.metadata["screenshot_path"] = str(retained_screenshot)
                    recorder.metadata["screenshot_sha256"] = _sha256(
                        retained_screenshot
                    )
                    recorder.event(
                        "dashboard_screenshot_captured",
                        sha256=recorder.metadata["screenshot_sha256"],
                    )

                recorder.event("soak_started")
                time.sleep(SOAK_SECONDS)
                recorder.event("soak_finished")
            except BaseException as exc:
                primary_error = exc
                recorder.event(
                    "arm_workload_error", error=f"{type(exc).__name__}: {exc}"
                )
            finally:
                try:
                    _record_actual_zones(
                        recorder, trajectory_path, args.region, args.actual_az
                    )
                except BaseException as exc:
                    recorder.event(
                        "availability_zone_error",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    if primary_error is None:
                        primary_error = exc
                try:
                    _run_logged(
                        commands["destroy"], "client_destroy", recorder, log_path
                    )
                except BaseException as exc:
                    recorder.event(
                        "teardown_error", error=f"{type(exc).__name__}: {exc}"
                    )
                    if primary_error is None:
                        primary_error = exc
                finally:
                    try:
                        final_operation_epoch = time.time()
                        append_operation_snapshot(
                            parse_operation_snapshot(
                                poll_operations_once(host, ssh_key),
                                poll_epoch=final_operation_epoch,
                                arm_n=args.arm_n,
                                replicate=args.replicate,
                                image_digest=args.image_digest,
                            ),
                            operations_path,
                        )
                        recorder.event(
                            "final_operation_snapshot_captured",
                            epoch=final_operation_epoch,
                        )
                    except BaseException as exc:
                        recorder.event(
                            "operation_snapshot_error",
                            error=f"{type(exc).__name__}: {exc}",
                        )
                        if primary_error is None:
                            primary_error = exc
                    try:
                        clock_end = allocator_clock_probe(host, ssh_key)
                        recorder.metadata["allocator_clock_probe_end"] = clock_end
                        recorder.event("allocator_clock_probed_end", **clock_end)
                    except BaseException as exc:
                        recorder.event(
                            "clock_probe_error",
                            error=f"{type(exc).__name__}: {exc}",
                        )
                        if primary_error is None:
                            primary_error = exc
                    poller.terminate()
                    try:
                        poller.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        poller.kill()
                        poller.wait()
                    poller_log.close()
                    recorder.event("collector_stopped", exit_code=poller.returncode)
            if primary_error is not None:
                raise primary_error
    except BaseException as exc:
        print(f"arm failed; evidence retained in {arm_dir}: {exc}", file=sys.stderr)
        return 1

    print(f"arm complete: {arm_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
