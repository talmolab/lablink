# Run Client Unit Tests

```bash
cd packages/client && PYTHONPATH=src uv run pytest
```

CI runs these twice: once on the repo, once *inside* the built image — so a test
that reads a repo-only file passes here and fails there.
