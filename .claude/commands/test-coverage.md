# Run Tests with Coverage

```bash
cd packages/allocator && PYTHONPATH=src uv run pytest --ignore=tests/terraform \
  --cov=lablink_allocator_service --cov-report=term-missing
cd packages/client && PYTHONPATH=src uv run pytest \
  --cov=lablink_client_service --cov-report=term-missing
cd packages/cli && PYTHONPATH=src uv run pytest \
  --cov=lablink_cli --cov-report=term-missing
```

The allocator's 90% gate is **CI-only** — CI runs the full `tests` directory with
no terraform ignore. A local run with `--ignore=tests/terraform` caps around 86%;
that gap is not a regression.
