# Run Allocator Unit Tests

```bash
cd packages/allocator && PYTHONPATH=src uv run pytest --ignore=tests/terraform
```

`PYTHONPATH=src`, never `PYTHONPATH=.` — inside a git worktree `.` can resolve to
the other checkout's code, silently testing the wrong tree.

`--ignore=tests/terraform` because those shell out to the `terraform` binary and
need AWS credentials; they fail locally (3 failures + 8 errors) regardless of your
changes. CI runs the full `tests` directory.
