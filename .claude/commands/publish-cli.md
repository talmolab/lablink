# Publish CLI to PyPI

Tag-triggered:

```bash
git tag lablink-cli_v0.1.0a1
git push origin lablink-cli_v0.1.0a1
gh run watch
```

Or dispatch manually (`dry_run` defaults to **true**):

```bash
gh workflow run publish-pip.yml \
  -f package=lablink-cli -f dry_run=false
```

The version comes from `packages/cli/pyproject.toml` and the tag suffix must
match it exactly, or guardrail 2 fails the run.

Two things specific to this package:

- **Release the allocator first.** `lablink-cli` depends on
  `lablink-allocator-service[config]>=0.2.0`, and `deploy_compose.py` imports
  `PUBLIC_HOSTNAME_HINT`, `is_valid_public_hostname` and
  `is_weak_admin_password` from it. Publishing the CLI against an allocator
  that predates those symbols leaves `provider: manual` raising ImportError at
  runtime — the AWS path and `--help` still work, so it does not fail loudly.
- **Alpha versions need `--pre`.** `pip install lablink-cli` skips `0.1.0a1`;
  users need `pip install --pre lablink-cli` until a final version ships.

PyPI auth is OIDC trusted publishing — no token. The workflow grants
`id-token: write` and `uv publish` defaults to `--trusted-publishing automatic`.
The publish job declares no `environment:`, so the PyPI publisher must leave
its environment field blank.
