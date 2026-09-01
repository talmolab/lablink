# Contributing to LabLink

Thanks for your interest in contributing. This page covers the setup, the
conventions CI enforces, and how to get a change reviewed.

## Code of Conduct

Be respectful and constructive. Welcome newcomers, assume good faith, and keep
discussion focused on the work. Harassment, discrimination, derogatory comments,
and publishing others' private information are not tolerated.

## Ways to contribute

Bug reports, feature proposals, documentation fixes, tests, and code all help.
Before you start:

- **Search the [issues](https://github.com/talmolab/lablink/issues)** — someone may already be on it.
- **Open an issue first for anything substantial**, so the design gets discussed before you write it.
- **Read [CLAUDE.md](https://github.com/talmolab/lablink/blob/main/CLAUDE.md)** — the developer-facing project overview, and the source of truth for repo conventions.

## Development setup

**Requirements:** Python 3.10+, [uv](https://docs.astral.sh/uv/), Docker, Git.
Add the AWS CLI and OpenTofu 1.10+ only if you're touching infrastructure.

This repo is a **uv workspace** — the three packages (`allocator`, `client`,
`cli`) share one venv at the repo root. Always sync from the root, with both
flags:

```bash
git clone https://github.com/YOUR_USERNAME/lablink.git
cd lablink
uv sync --all-packages --extra dev
```

Without `--all-packages` the member packages are *uninstalled* from the venv and
entry-point tests fail; without `--extra dev` you get no pytest or ruff. A bare
`uv sync` from inside a package directory re-resolves the same root venv and
does not fix it.

### Tests and lint

```bash
cd packages/allocator && PYTHONPATH=src uv run pytest --ignore=tests/terraform
cd packages/client    && PYTHONPATH=src uv run pytest
cd packages/cli       && PYTHONPATH=src uv run pytest   # integration: -m integration

ruff check packages/allocator packages/client packages/cli
```

!!! warning "Two gotchas that silently mislead you"
    Use `PYTHONPATH=src`, never `PYTHONPATH=.` — inside a git worktree, `.` can
    resolve to another checkout's code, so you test the wrong tree.

    `--ignore=tests/terraform` skips tests that shell out to the `terraform`
    binary and need AWS credentials. They fail locally regardless of your
    changes and are not a regression signal. CI runs the full directory, so the
    allocator and client 90% coverage gates are CI-only.

### Docker images

The build context must be the **package** directory, not the repo root — the
dev Dockerfiles' `COPY` paths are relative to it. On Apple Silicon
`--platform` is required too, because the client image pulls an amd64-only
`kasmvncserver` package.

```bash
cd packages/allocator && docker build --platform linux/amd64 \
  -t lablink-allocator:dev -f Dockerfile.dev .
```

## Reporting bugs

Check [Troubleshooting](troubleshooting.md) and run `lablink doctor` first, then
open an issue with:

- What you did, what you expected, what happened instead
- The exact error message and relevant logs
- Environment: OS, Python version, Docker version, image tag or package version
- Your `config.yaml` with secrets removed, if the problem is deployment-related

## Suggesting features

Include the use case and motivation, your proposed solution, alternatives you
considered, and the impact on existing behavior — especially backwards
compatibility.

## Contribution workflow

1. Fork, then branch: `feature/`, `fix/`, `docs/`, `refactor/`, or `test/` plus a short description.
2. Make the change. Add tests for new behavior and regression tests for bug fixes.
3. Run the tests and `ruff check` for every package you touched.
4. Commit using [Conventional Commits](https://www.conventionalcommits.org/) — `<type>(<scope>): <description>`, where type is one of `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`:
   ```bash
   git commit -m "feat(allocator): add support for Spot Instances"
   ```
5. Push to your fork and open a pull request against `main`.

## Coding standards

Conventions live in [CLAUDE.md](https://github.com/talmolab/lablink/blob/main/CLAUDE.md#conventions);
the short version:

- **PEP 8** via ruff, 88-character lines. Type hints on public functions, Google-style docstrings.
- `snake_case` functions and modules, `PascalCase` classes, `UPPER_SNAKE_CASE` constants.
- CI runs `ruff check src tests` — lint errors in tests fail the build too. `ruff format` is **not** enforced, so don't reformat files beyond your change.
- **OpenTofu**: descriptive resource names, variables for anything configurable, and `Name` / `Project` / `Environment` tags on every resource. Allocator infrastructure lives in the [`lablink-template`](https://github.com/talmolab/lablink-template) repo, not here.

Follow the patterns in the module you're editing rather than introducing a new
one alongside them.

## Documentation

Update the relevant page under `docs/` whenever behavior changes — `database.md`
for a schema change, `configuration.md` for a new config key. **New API routes
need no page edit**: the API Endpoints page is generated from route docstrings
at build time, and a route without a docstring fails the build.

```bash
uv run --extra docs mkdocs serve     # http://localhost:8000, auto-reloads
uv run --extra docs mkdocs build --strict
```

Write short sentences in the active voice, test every command you document, and
keep terminology consistent (the service is the "allocator"). The Material theme
gives you [admonitions](https://squidfunk.github.io/mkdocs-material/reference/admonitions/),
[content tabs](https://squidfunk.github.io/mkdocs-material/reference/content-tabs/),
and Mermaid diagrams — use them instead of hand-rolled formatting.

## Pull requests

Keep each PR to a single concern, and describe what changed and why. Then:

1. Automated checks run — tests and linting for the affected packages.
2. A maintainer reviews for design and code quality.
3. You address feedback by pushing new commits (avoid force-pushing once review has started).
4. A maintainer squash-merges after approval.

Split large changes into a series of incremental PRs rather than one sprawling
branch, and don't make breaking changes without discussing them first.

## Releases

Maintainers only — see
[Workflows](workflows.md#package-publishing-workflow) for the publish and
production-image process.

## Getting help

- 📖 [Documentation](https://talmolab.github.io/lablink/) and [FAQ](faq.md)
- 🐛 [Issues](https://github.com/talmolab/lablink/issues)
- 💬 [Discussions](https://github.com/talmolab/lablink/discussions)

## License

By contributing, you agree your contributions are licensed under the project's
[BSD-2-Clause License](https://github.com/talmolab/lablink/blob/main/LICENSE).
