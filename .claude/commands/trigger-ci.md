# Trigger CI Workflow

`ci.yml` has **no** `workflow_dispatch` — it cannot be started with
`gh workflow run`. It fires only on pull requests touching `packages/**`
(excluding `*.md`) or the workflow file itself.

```bash
# Re-run the checks on an existing PR
gh run list --workflow=ci.yml --limit 5
gh run rerun <run-id> --failed

# Watch the run for the current branch
gh run watch
```

An empty commit (`git commit --allow-empty`) is the other way to re-trigger.

Each package's CI job syncs only its own `pyproject.toml`, so a cross-package
import that works in the local shared venv can still fail in CI.
