#!/usr/bin/env python3
"""Wrap configure/deploy/destroy commands with append-only timeline events."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def append_event(path: Path, phase: str, **details) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {"phase": phase, "epoch": time.time(), **details}
    with path.open("a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")
    append_event(args.events, f"{args.phase}_started", command=command)
    try:
        result = subprocess.run(command)
    except BaseException as exc:
        append_event(
            args.events,
            f"{args.phase}_finished",
            exit_code=None,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    append_event(args.events, f"{args.phase}_finished", exit_code=result.returncode)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
