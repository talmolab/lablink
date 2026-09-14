#!/usr/bin/env python3
"""Claim N LabLink seats concurrently and preserve every outcome.

Success is deliberately narrow: the participant endpoint grants a seat with
303 See Other. Its unexpected-error path can return 200, so generic 2xx logic
would turn real failures into successes.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

CLAIM_COLUMNS = [
    "email",
    "request_epoch",
    "response_epoch",
    "latency_s",
    "status_code",
    "outcome",
    "error",
]


def classify_claim(status_code: int, body: str) -> str:
    """Map the endpoint's actual response contract to a stable outcome."""
    if status_code == 303:
        return "claimed"
    if status_code == 200:
        return "unexpected_200"
    if status_code == 503 and "No seats available" in body:
        return "no_seats"
    if status_code == 503 and "Couldn't prepare your seat" in body:
        return "rotation_failed"
    return "http_error"


def make_emails(count: int, *, arm_n: int, replicate: int, run_id: str) -> list[str]:
    """Create unique, arm-identifiable addresses to avoid idempotent rejoins."""
    return [
        f"fig2+{run_id}-n{arm_n}-r{replicate}-seat{seat:03d}@example.invalid"
        for seat in range(1, count + 1)
    ]


def claim_one(
    base_url: str,
    email: str,
    *,
    requester: Callable | None = None,
    clock: Callable[[], float] = time.time,
    timeout_s: float = 60.0,
) -> dict:
    """Make one claim without following the success redirect."""
    if requester is None:
        import requests

        requester = requests.post

    request_epoch = clock()
    try:
        response = requester(
            f"{base_url.rstrip('/')}/api/request_vm",
            data={"email": email},
            allow_redirects=False,
            timeout=timeout_s,
        )
        response_epoch = clock()
        status_code = int(response.status_code)
        outcome = classify_claim(status_code, response.text)
        error = "" if outcome == "claimed" else outcome
    except Exception as exc:  # every attempted seat must remain in the CSV
        response_epoch = clock()
        status_code = None
        outcome = "request_error"
        error = f"{type(exc).__name__}: {exc}"

    return {
        "email": email,
        "request_epoch": request_epoch,
        "response_epoch": response_epoch,
        "latency_s": response_epoch - request_epoch,
        "status_code": status_code,
        "outcome": outcome,
        "error": error,
    }


def write_claims(rows: list[dict], out: Path) -> None:
    """Atomically-shaped output: one row for every intended request."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CLAIM_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def collect_claims(
    base_url: str,
    *,
    count: int,
    arm_n: int,
    replicate: int,
    run_id: str,
    workers: int | None = None,
) -> list[dict]:
    """Release the claim requests together and return them in seat order."""
    emails = make_emails(count, arm_n=arm_n, replicate=replicate, run_id=run_id)
    with ThreadPoolExecutor(max_workers=workers or count) as pool:
        rows = list(pool.map(lambda email: claim_one(base_url, email), emails))
    return rows


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--arm-n", type=int, required=True)
    parser.add_argument("--replicate", type=int, required=True)
    parser.add_argument("--run-id", default=uuid.uuid4().hex[:10])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows = collect_claims(
        args.base_url,
        count=args.count,
        arm_n=args.arm_n,
        replicate=args.replicate,
        run_id=args.run_id,
    )
    write_claims(rows, args.out)
    successes = sum(row["outcome"] == "claimed" for row in rows)
    print(f"claimed {successes}/{args.count} seats -> {args.out}")
    return 0 if successes == args.count else 2


if __name__ == "__main__":
    sys.exit(main())
