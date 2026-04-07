# Terraform Source Deduplication

**Date:** 2026-04-07
**Status:** Draft
**Issue:** https://github.com/talmolab/lablink/issues/313
**Problem:** The CLI package bundles copies of Terraform files from `lablink-template`, creating a redundancy that has already diverged (naming conventions, tags, namespaces, S3 paths).

## Decision

The CLI will download Terraform files from tagged GitHub releases of `talmolab/lablink-template` instead of bundling its own copies. The template repo remains the single source of truth.

Python command logic (setup, cleanup, status, etc.) stays duplicated intentionally — the template must remain self-contained for standalone use, and the CLI cannot depend on bash scripts on Windows.

## Architecture

### Download & Cache

A new module `packages/cli/src/lablink_cli/terraform_source.py` handles fetching and caching.

**Constants** (in `packages/cli/src/lablink_cli/__init__.py`):

```python
TEMPLATE_REPO = "talmolab/lablink-template"
TEMPLATE_VERSION = "v0.1.0"
TEMPLATE_SHA256 = "<sha256 hash of v0.1.0 tarball>"
```

These are package-level metadata — not reference data like AMI maps — so they belong in `__init__.py` rather than `schema.py`.

**Cache location:** `~/.lablink/cache/terraform/{version}/`

**Download URL:** `https://github.com/{TEMPLATE_REPO}/archive/refs/tags/{version}.tar.gz`

**Flow:**

1. Check if `~/.lablink/cache/terraform/{version}/` exists with `.tf` files
2. If cached, return the cached path
3. If not cached, download the tarball via `urllib.request`
4. Verify SHA-256 checksum against `TEMPLATE_SHA256` (skip verification if `--template-version` override is used since we won't have a pinned hash)
5. Extract to a temporary directory first, then atomically rename to the cache path (prevents partial cache on interrupted downloads)
6. Only extract files matching: `*.tf`, `*.hcl`, `user_data.sh`, `config/` — reject all other paths
7. Apply tarfile path traversal protection (Python 3.12+ `data_filter`, or manual member validation for older versions)
8. Return the cache path
9. On download failure, retry up to 3 times with exponential backoff. On final failure, print a clear error message mentioning: the URL to download manually, proxy settings (`HTTPS_PROXY`), and the `--terraform-bundle` flag

**No new dependencies** — uses only `urllib.request`, `tarfile`, and `hashlib` from stdlib.

**Download UX:** Print a single line during download:
```
Downloading infrastructure templates v0.1.0... done.
```

### Security

**Tarfile extraction safety:**
- Whitelist extracted files by extension: `.tf`, `.hcl`, `.sh`, `.yaml`
- Reject any member with `..` in the path or absolute paths
- Use Python 3.12+ `tarfile.data_filter` when available
- Extract to temp directory, verify contents, then atomic rename to cache path

**Integrity verification:**
- SHA-256 hash of the release tarball is pinned in `__init__.py` alongside `TEMPLATE_VERSION`
- Hash is verified after download, before extraction
- When `--template-version` is used to override, checksum verification is skipped (user accepts the risk) and a warning is printed
- Cache poisoning is mitigated by verifying the checksum before writing to cache

### Changes to deploy.py

- Remove `TERRAFORM_SRC` constant (the bundled path reference)
- `_prepare_working_dir` calls `terraform_source.get_terraform_files(version)` to get the cached path, then copies from there to the deploy working directory
- The `--template-version` CLI flag overrides the pinned default. Added to the deploy command in `app.py`, passed as `run_deploy(cfg, template_version=None)`. When `None`, uses `TEMPLATE_VERSION` from `__init__.py`

### Offline / Air-Gapped Support

A `--terraform-bundle` flag on `lablink deploy` accepts a path to a manually downloaded tarball:

```
lablink deploy --terraform-bundle ~/Downloads/lablink-template-v0.1.0.tar.gz
```

This extracts the tarball into the cache (with the same safety checks) and proceeds with the deploy. No network required.

The error message on download failure explicitly mentions this flag as a workaround.

### Fix: Region Terraform Variable

The current deploy code does an unsafe string replacement:

```python
content.replace('region = "us-west-2"', f'region = "{cfg.app.region}"')
```

This is brittle — if the template changes the default region string, the replacement silently fails and deploys go to the wrong region.

**Fix:** The template should use a Terraform variable for the AWS provider region. The CLI already passes `-var=deployment_name=...` and `-var=environment=...` to Terraform. Add `-var=region={cfg.app.region}` in the same way.

This requires a coordinated change:
1. Template repo: Add `variable "region"` and use it in the `provider "aws"` block
2. CLI: Pass `-var=region=...` and remove the string replacement hack

This should be included in the `v0.1.0` template release.

### Files Removed

Delete the entire `packages/cli/src/lablink_cli/terraform/` directory:

- `main.tf`, `alb.tf`, `budget.tf`, `cloudtrail.tf`, `cloudwatch_alarms.tf`, `backend.tf`
- `backend-dev.hcl`, `backend-prod.hcl`, `backend-test.hcl`
- `user_data.sh`
- `config/custom-startup.sh`, `config/startup-template.sh`
- `.gitignore`

### Changes to lablink-template

- Add `variable "region"` to Terraform config, use in `provider "aws"` block
- Create a `v0.1.0` tag on `main` after the region variable change

### CLI Flag Summary

```
lablink deploy                                          # uses pinned TEMPLATE_VERSION
lablink deploy --template-version v0.2.0                # override version (skips checksum, prints warning)
lablink deploy --terraform-bundle ./template.tar.gz     # use local tarball (offline support)
```

## Testing

### Unit Tests

New test file `tests/test_terraform_source.py`:

- Mock `urllib.request.urlopen` to return a fake tarball
- Cache hit: if cache dir exists, no download occurs
- Cache miss: download triggered, files extracted to correct location
- Checksum verification: correct hash passes, wrong hash fails
- `--template-version` override: skips checksum, prints warning
- `--terraform-bundle`: extracts from local file, no network call
- Tarfile safety: paths with `..` are rejected, only whitelisted extensions extracted
- Atomic cache: interrupted extraction leaves no partial cache directory
- Download failure: retry logic, clear error message with manual instructions
- Download UX: progress message printed

### Existing Test Updates

`tests/test_deploy.py` currently patches `deploy_mod.TERRAFORM_SRC` — update to mock `terraform_source.get_terraform_files()` instead, returning a temp directory with fake `.tf` files.

### Integration Test

One test marked `@pytest.mark.integration` that performs a real download from GitHub. Skipped by default, run explicitly with `pytest -m integration`. Verifies: download succeeds, checksum matches, expected files present, cache works on second call.

## Out of Scope

- Deduplicating Python command logic with template shell scripts (intentionally kept separate)
- Template manifest / compatibility matrix (same team maintains both repos, version pin is sufficient for now)
- Generic `github_release.py` utility (YAGNI — extract later if needed)
- Cache management commands (`lablink cache clear` etc. — cache is tiny, not worth the complexity yet)
- Template release versioning strategy beyond the initial `v0.1.0`
