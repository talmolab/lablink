# Claude Developer Guide

**LabLink** is a cloud-based virtual teaching lab accessible through Chrome browser. It consists of three packages: an **allocator** service (Flask API that orchestrates VM provisioning), a **client** service (runs on GPU VMs for health reporting), and a **CLI** tool (Typer-based command-line interface for deploying and managing infrastructure).

## Key Resources

| Resource | Location |
|----------|----------|
| Architecture, providers, connectivity | `docs/architecture.md` |
| API endpoints | Generated at docs-build time from route docstrings by `docs/scripts/gen_api_endpoints.py` |
| Database schema | `docs/database.md` |
| CI/CD workflows and image tagging | `docs/workflows.md` |
| Configuration reference | `docs/configuration.md` |
| Configuration examples | `docs/configuration.md#full-configuration-examples` |
| CLI reference | `docs/reference/cli.md` |
| Documentation site | https://talmolab.github.io/lablink/ |

## Repository Structure

```
lablink/
├── packages/
│   ├── allocator/          # Allocator service (Flask, Terraform)
│   ├── client/             # Client service (KasmVNC desktop, agent, health reporting)
│   └── cli/                # CLI tool (Typer, deploys infrastructure)
│       └── src/lablink_cli/
│           ├── app.py                  # CLI entry point + Typer command definitions
│           ├── api.py                  # HTTP client for the allocator service
│           ├── terraform_source.py     # Downloads Terraform files from lablink-template releases
│           ├── deployment_metrics.py   # CLI-local cache of deploy metrics (~/.lablink/deployments/)
│           ├── commands/               # Command implementations (deploy, cleanup, status, logs, doctor, setup, launch, export_metrics)
│           ├── config/                 # Config schema and validation
│           └── tui/                    # Interactive TUI (wizard, logs viewer)
├── .claude/commands/       # Slash commands for development
└── docs/                   # MkDocs documentation
```

## Slash Commands

Use these commands for common development tasks:

| Category | Commands |
|----------|----------|
| **Testing** | `/test-allocator`, `/test-client`, `/test-cli`, `/test-coverage`, `/lint`, `/lint-fix` |
| **Docker** | `/docker-build-allocator`, `/docker-build-client`, `/docker-test-allocator`, `/docker-test-client` |
| **CI/CD** | `/trigger-ci`, `/trigger-docker-build`, `/publish-allocator`, `/publish-client` |
| **Git & PR** | `/update-changelog` |
| **Dev** | `/dev-setup`, `/run-allocator-local`, `/validate-terraform` |

Each file under `.claude/commands/` is the command plus only the notes that aren't
obvious from it — this table is the index.

### Workflows
Before implementing changes, present a plan and get user approval. Do not start coding until the approach is confirmed, especially for refactors or multi-file changes.

## Quick Reference

### Environment setup

This repo is a **uv workspace** — the root `pyproject.toml` declares
`[tool.uv.workspace]` with `packages/allocator`, `packages/client`, and
`packages/cli` as members. There is ONE venv, at the repo root, shared by all
three packages. Always sync from the repo root:

```bash
uv sync --all-packages --extra dev
```

Both flags matter. Without `--all-packages` you get only the docs-only root
project — no pytest, and the member packages are *uninstalled* from the venv,
which breaks entry-point tests like
`tests/providers/test_registry.py::test_aws_entry_point_is_registered`.
Without `--extra dev` you get no pytest/ruff. Running a bare `uv sync` from
inside `packages/<name>` does not fix this; it re-resolves the same root venv.

**In a fresh git worktree you must run this before anything else** — a new
worktree has no venv, and the first `uv run` will create a wrong one.

```bash
# Run tests
cd packages/allocator && PYTHONPATH=src uv run pytest --ignore=tests/terraform
cd packages/client    && PYTHONPATH=src uv run pytest
cd packages/cli       && PYTHONPATH=src uv run pytest  # integration: pytest -m integration

# Lint
ruff check packages/allocator packages/client packages/cli

# Build Docker (dev) — context MUST be the package dir, not the repo root:
# Dockerfile.dev's COPY paths (start.sh, lablink-nginx.conf, pg_hba.conf) are
# relative to packages/allocator/, so building from the root fails with
# `"/start.sh": not found`. On Apple Silicon --platform is required too: the
# image pulls an amd64-only kasmvncserver .deb, which aborts a native arm64
# build with apt exit code 100.
cd packages/allocator && docker build --platform linux/amd64 \
  -t lablink-allocator:dev -f Dockerfile.dev .
```

Two things about the allocator test command:

- **`PYTHONPATH=src`, never `PYTHONPATH=.`** — inside a worktree, `.` can
  resolve to the *other* checkout's code, so you silently test the wrong tree.
- **`--ignore=tests/terraform`** — those tests shell out to the `terraform`
  binary and need AWS credentials, so they fail locally (3 failures + 8 errors)
  regardless of your changes. They are not a regression signal. CI runs the
  full `tests` directory, so the 90% coverage gate is CI-only; a local run with
  this flag caps around 86%.

## CLI Architecture

The CLI (`lablink` command) downloads Terraform files from tagged GitHub releases of `talmolab/lablink-template` instead of bundling copies. This keeps the template repo as the single source of truth.

- **Template version**: Pinned in `packages/cli/src/lablink_cli/__init__.py` (`TEMPLATE_VERSION`, `TEMPLATE_SHA256`)
- **Cache**: Downloaded templates are cached at `~/.lablink/cache/terraform/{version}/`
- **Override flags**: `--template-version v0.2.0` (custom version, skips checksum) and `--terraform-bundle ./file.tar.gz` (offline mode)
- **Region**: Passed as `-var=region=` to Terraform (not string-replaced in `.tf` files)
- **Template repo**: `talmolab/lablink-template` — allocator infrastructure Terraform configs

## Conventions

Salvaged from the retired `openspec/project.md`, minus the parts that had gone
stale or that `docs/` already covers.

### Code style
- **PEP 8** via ruff. Max line length 88 (ruff default).
- **Type hints** required for public functions; **Google-style docstrings**.
- f-strings for formatting. Import order stdlib → third-party → local (ruff handles).
- `snake_case.py` files and functions, `PascalCase` classes,
  `UPPER_SNAKE_CASE` constants, `_leading_underscore` for private members.

### Allocator database layer

All allocator persistence lives in `packages/allocator/src/lablink_allocator_service/db/`.
Each class owns one concern and they **share a single connection pool** rather than
each opening their own — `POOL_MAX_SIZE` is tuned for the service's total
connection budget, so a second pool would silently double it.

```
db/
├── __init__.py     # Docstring only, NO re-exports — read it before adding any
├── pool.py         # PooledCursor, make_pool, validate_pool_sizes, POOL_* sizing
├── vms.py          # VmDatabase — VM rows, registration/auth, seats, logs, health
├── schedules.py    # ScheduleDatabase — scheduled_destructions table
├── metrics.py      # MetricsDatabase — session-metrics columns on the VM table
└── operations.py   # OperationsDatabase — operations table (async apply/destroy jobs)
```

Two non-obvious rules here:

- **`db/__init__.py` re-exports nothing.** If it did, importing *any* submodule —
  including the dependency-free `db.pool` — would eagerly execute `db/vms.py` and
  its top-level `import psycopg2` as a side effect, coupling every consumer to the
  heaviest module in the package.
- **A class that constructs a pool must do so in its own module.** `VmDatabase`
  builds its pool inline rather than calling `make_pool`, so its own `import
  psycopg2` binding is the one used. `make_pool` is for callers needing only a bare
  pool (e.g. the APScheduler job in `scheduler.py`). `VmDatabase` also accepts an
  injected `pool=` and tracks ownership, so it will not close a pool it was handed.

Related: new `database.py`-adjacent modules must **lazy-import psycopg2**, not
import it at module level, or pytest collection order can poison the mocking
guards in `test_database.py` / `test_reboot.py`.

### Docker strategy
- Two Dockerfiles per package: `Dockerfile.dev` builds local code with `uv sync`
  (CI/testing); `Dockerfile` installs the published PyPI package (production).
- Explicit venv paths: `/app/.venv` (allocator), `/home/client/.venv` (client).
- Console scripts are declared in each `pyproject.toml`.

## Notes for Claude

### When Making Changes
1. Read existing code before editing
2. Follow the conventions below
3. Add tests for new functionality
4. Update the relevant page under `docs/` if behavior changes

### When Adding Features
1. Add to structured config if user-facing
2. Document in the relevant `docs/` page — `docs/database.md` for a schema
   change, `docs/configuration.md` for a new config key. A new route needs no
   docs page edit: write its docstring — the API Endpoints page is generated
   from route docstrings at docs-build time (`docs/scripts/gen_api_endpoints.py`),
   and a route without a docstring fails the docs build. Keep relative
   `docs/` links out of docstrings (they also render under `reference/`);
   an `Auth:` line in the docstring overrides decorator-inferred auth

### Code Review Checklist
- [ ] Follows existing patterns
- [ ] Tests added/updated
- [ ] No secrets committed
- [ ] Backwards compatible (or documented)

## Cross-Repo Dependencies

LabLink spans two repositories:
- **`talmolab/lablink`** (this repo): Python packages (allocator, client, CLI), CI/CD, docs
- **`talmolab/lablink-template`**: Terraform configs for allocator infrastructure deployment. The CLI downloads from tagged releases of this repo. Changes to Terraform (IAM policies, provider config, resource definitions) must be made in the template repo and released with a new tag. Then update `TEMPLATE_VERSION` and `TEMPLATE_SHA256` in the CLI's `__init__.py`.

## Debugging / Investigation
When investigating issues, explore the full codebase before concluding something is unimplemented or dead code. Check all packages/modules — implementations may exist in unexpected locations (e.g., Terraform configs in a different package or in the `lablink-template` repo).

### Testing
When fixing bugs or adding features, always update existing tests to account for new behavior (e.g., new validation checks, changed function signatures). Run the full test suite before considering a task complete.