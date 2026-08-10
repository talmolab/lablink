# Run CLI Unit Tests

```bash
cd packages/cli && PYTHONPATH=src uv run pytest
```

Integration tests (real network) are deselected by `addopts` in
`packages/cli/pyproject.toml`; run them with `-m integration`.

Typer `--help` output is ANSI-laden in CI — assert against `test_app.py`'s
`_plain()` helper, not the raw string.
