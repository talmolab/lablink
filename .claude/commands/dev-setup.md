# Development Environment Setup

This repo is a **uv workspace** — one venv at the repo root, shared by all three
packages. Always sync from the root:

```bash
uv sync --all-packages --extra dev
```

Both flags matter. Without `--all-packages` you get only the docs-only root
project — no pytest, and the member packages are *uninstalled* from the venv,
breaking entry-point tests like
`tests/providers/test_registry.py::test_aws_entry_point_is_registered`. Without
`--extra dev` you get no pytest/ruff. A bare `uv sync` from inside
`packages/<name>` does not fix this; it re-resolves the same root venv.

**In a fresh git worktree, run this before anything else** — a new worktree has no
venv, and the first `uv run` will create a wrong one.

Verify:

```bash
cd packages/allocator && PYTHONPATH=src uv run pytest --ignore=tests/terraform
cd packages/client    && PYTHONPATH=src uv run pytest
cd packages/cli       && PYTHONPATH=src uv run pytest
```

Local venv is Python 3.12; CI runs 3.10.
