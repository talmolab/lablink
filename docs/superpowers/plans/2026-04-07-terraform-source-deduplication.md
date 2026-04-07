# Terraform Source Deduplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate bundled Terraform file duplication by downloading them from lablink-template GitHub releases at deploy time.

**Architecture:** New `terraform_source.py` module handles download, checksum verification, and caching. `deploy.py` consumes it instead of copying from a bundled directory. The template repo gets a `variable "region"` so the CLI can pass it as a Terraform variable instead of string-replacing the file.

**Tech Stack:** Python stdlib (`urllib.request`, `tarfile`, `hashlib`), typer CLI framework, pytest

**Spec:** `docs/superpowers/specs/2026-04-07-terraform-source-deduplication-design.md`
**Issue:** https://github.com/talmolab/lablink/issues/313

---

### Task 1: Add template constants to `__init__.py`

**Files:**
- Modify: `packages/cli/src/lablink_cli/__init__.py`
- Test: `packages/cli/tests/test_terraform_source.py` (create)

- [ ] **Step 1: Write test for constants**

Create `packages/cli/tests/test_terraform_source.py`:

```python
"""Tests for lablink_cli template constants and terraform_source."""

from lablink_cli import TEMPLATE_REPO, TEMPLATE_VERSION, TEMPLATE_SHA256


class TestTemplateConstants:
    def test_repo_format(self):
        assert "/" in TEMPLATE_REPO
        assert TEMPLATE_REPO == "talmolab/lablink-template"

    def test_version_starts_with_v(self):
        assert TEMPLATE_VERSION.startswith("v")

    def test_sha256_is_hex(self):
        assert len(TEMPLATE_SHA256) == 64
        int(TEMPLATE_SHA256, 16)  # raises if not valid hex
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/cli && PYTHONPATH=src pytest tests/test_terraform_source.py::TestTemplateConstants -v`
Expected: FAIL with `ImportError: cannot import name 'TEMPLATE_REPO'`

- [ ] **Step 3: Add constants to `__init__.py`**

Edit `packages/cli/src/lablink_cli/__init__.py`:

```python
"""LabLink CLI - Deploy and manage LabLink infrastructure."""

TEMPLATE_REPO = "talmolab/lablink-template"
TEMPLATE_VERSION = "v0.1.0"
# SHA-256 of the GitHub release tarball for TEMPLATE_VERSION.
# Update this when bumping TEMPLATE_VERSION.
# To compute: curl -sL <tarball_url> | sha256sum
TEMPLATE_SHA256 = "0" * 64  # placeholder until v0.1.0 tag is created
```

Note: The SHA256 placeholder will be replaced with the real hash after the `v0.1.0` tag is created in the template repo (Task 7).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/cli && PYTHONPATH=src pytest tests/test_terraform_source.py::TestTemplateConstants -v`
Expected: 2 pass, 1 fail (sha256 placeholder is valid hex "000...0" so all 3 should pass)

- [ ] **Step 5: Commit**

```bash
git add packages/cli/src/lablink_cli/__init__.py packages/cli/tests/test_terraform_source.py
git commit -m "feat(cli): add template repo constants to __init__.py"
```

---

### Task 2: Create `terraform_source.py` — download and cache

**Files:**
- Create: `packages/cli/src/lablink_cli/terraform_source.py`
- Modify: `packages/cli/tests/test_terraform_source.py`

- [ ] **Step 1: Write tests for download and cache logic**

Append to `packages/cli/tests/test_terraform_source.py`:

```python
import io
import os
import tarfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from lablink_cli.terraform_source import (
    get_terraform_files,
    _download_tarball,
    _extract_terraform_files,
    CACHE_DIR,
)


def _make_test_tarball(tmp_path: Path) -> bytes:
    """Create a minimal tarball mimicking the GitHub release structure."""
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
        # GitHub tarballs have a top-level dir like "lablink-template-v0.1.0/"
        prefix = "lablink-template-v0.1.0/lablink-infrastructure"

        for name, content in [
            (f"{prefix}/main.tf", b'provider "aws" { region = var.region }'),
            (f"{prefix}/alb.tf", b"# alb config"),
            (f"{prefix}/backend.tf", b"# backend"),
            (f"{prefix}/backend-dev.hcl", b"# dev backend"),
            (f"{prefix}/user_data.sh", b"#!/bin/bash\necho hello"),
            (f"{prefix}/config/custom-startup.sh", b"#!/bin/bash"),
        ]:
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return tar_buffer.getvalue()


class TestDownloadTarball:
    @patch("lablink_cli.terraform_source.urlopen")
    def test_downloads_from_correct_url(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"fake tarball"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _download_tarball("v0.1.0")

        url = mock_urlopen.call_args[0][0]
        assert "talmolab/lablink-template" in url
        assert "v0.1.0" in url
        assert result == b"fake tarball"

    @patch("lablink_cli.terraform_source.urlopen")
    def test_retries_on_failure(self, mock_urlopen):
        mock_urlopen.side_effect = [
            Exception("network error"),
            Exception("network error"),
            MagicMock(
                read=lambda: b"data",
                __enter__=lambda s: s,
                __exit__=MagicMock(return_value=False),
            ),
        ]
        result = _download_tarball("v0.1.0", retries=3)
        assert result == b"data"
        assert mock_urlopen.call_count == 3

    @patch("lablink_cli.terraform_source.urlopen")
    def test_raises_after_all_retries_exhausted(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("network error")
        with pytest.raises(SystemExit):
            _download_tarball("v0.1.0", retries=3)


class TestExtractTerraformFiles:
    def test_extracts_expected_files(self, tmp_path):
        tarball_data = _make_test_tarball(tmp_path)
        dest = tmp_path / "extracted"

        _extract_terraform_files(tarball_data, dest)

        assert (dest / "main.tf").exists()
        assert (dest / "alb.tf").exists()
        assert (dest / "backend.tf").exists()
        assert (dest / "backend-dev.hcl").exists()
        assert (dest / "user_data.sh").exists()
        assert (dest / "config" / "custom-startup.sh").exists()

    def test_rejects_path_traversal(self, tmp_path):
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            info = tarfile.TarInfo(
                name="lablink-template-v0.1.0/lablink-infrastructure/../../etc/passwd"
            )
            info.size = 5
            tar.addfile(info, io.BytesIO(b"owned"))
        tarball_data = tar_buffer.getvalue()
        dest = tmp_path / "extracted"

        _extract_terraform_files(tarball_data, dest)

        # Malicious file must not exist anywhere
        assert not (tmp_path / "etc" / "passwd").exists()
        assert not (dest / "etc" / "passwd").exists()

    def test_rejects_non_whitelisted_extensions(self, tmp_path):
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            prefix = "lablink-template-v0.1.0/lablink-infrastructure"
            info = tarfile.TarInfo(name=f"{prefix}/malware.exe")
            info.size = 4
            tar.addfile(info, io.BytesIO(b"evil"))

            info2 = tarfile.TarInfo(name=f"{prefix}/main.tf")
            info2.size = 5
            tar.addfile(info2, io.BytesIO(b"valid"))
        tarball_data = tar_buffer.getvalue()
        dest = tmp_path / "extracted"

        _extract_terraform_files(tarball_data, dest)

        assert not (dest / "malware.exe").exists()
        assert (dest / "main.tf").exists()


class TestGetTerraformFiles:
    @patch("lablink_cli.terraform_source._download_tarball")
    @patch("lablink_cli.terraform_source._verify_checksum")
    def test_cache_miss_downloads(
        self, mock_verify, mock_download, tmp_path
    ):
        mock_download.return_value = _make_test_tarball(tmp_path)
        cache_dir = tmp_path / "cache"

        with patch.object(
            __import__("lablink_cli.terraform_source", fromlist=["CACHE_DIR"]),
            "CACHE_DIR",
            cache_dir,
        ):
            result = get_terraform_files("v0.1.0")

        mock_download.assert_called_once_with("v0.1.0", retries=3)
        assert (result / "main.tf").exists()

    @patch("lablink_cli.terraform_source._download_tarball")
    def test_cache_hit_skips_download(self, mock_download, tmp_path):
        cache_dir = tmp_path / "cache" / "v0.1.0"
        cache_dir.mkdir(parents=True)
        (cache_dir / "main.tf").write_text("# cached")

        with patch.object(
            __import__("lablink_cli.terraform_source", fromlist=["CACHE_DIR"]),
            "CACHE_DIR",
            tmp_path / "cache",
        ):
            result = get_terraform_files("v0.1.0")

        mock_download.assert_not_called()
        assert result == cache_dir
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/cli && PYTHONPATH=src pytest tests/test_terraform_source.py -v -k "not TestTemplateConstants"`
Expected: FAIL with `ModuleNotFoundError: No module named 'lablink_cli.terraform_source'`

- [ ] **Step 3: Implement `terraform_source.py`**

Create `packages/cli/src/lablink_cli/terraform_source.py`:

```python
"""Download and cache Terraform files from lablink-template releases."""

from __future__ import annotations

import hashlib
import io
import os
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from rich.console import Console

from lablink_cli import TEMPLATE_REPO, TEMPLATE_SHA256

console = Console()

CACHE_DIR = Path.home() / ".lablink" / "cache" / "terraform"

_ALLOWED_EXTENSIONS = {".tf", ".hcl", ".sh", ".yaml"}


def get_terraform_files(
    version: str,
    *,
    bundle_path: str | None = None,
    skip_checksum: bool = False,
) -> Path:
    """Return path to cached Terraform files, downloading if needed.

    Args:
        version: Git tag in the template repo (e.g. "v0.1.0").
        bundle_path: Path to a local tarball (offline mode). Skips download.
        skip_checksum: If True, skip SHA-256 verification (used with --template-version).

    Returns:
        Path to directory containing .tf files ready for use.
    """
    cache_path = CACHE_DIR / version

    # Cache hit — return immediately
    if cache_path.exists() and any(cache_path.glob("*.tf")):
        return cache_path

    # Get tarball bytes
    if bundle_path:
        console.print(f"  Using local bundle: {bundle_path}")
        tarball_data = Path(bundle_path).read_bytes()
    else:
        console.print(
            f"  Downloading infrastructure templates {version}... ",
            end="",
        )
        tarball_data = _download_tarball(version, retries=3)
        console.print("done.")

    # Verify checksum
    if not skip_checksum:
        _verify_checksum(tarball_data, version)

    # Extract to temp dir, then atomic rename to cache
    tmp_dir = Path(tempfile.mkdtemp(
        dir=CACHE_DIR.parent, prefix=".terraform-extract-"
    ))
    try:
        _extract_terraform_files(tarball_data, tmp_dir)

        # Atomic move to final cache location
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            # Another process may have created it concurrently
            return cache_path
        tmp_dir.rename(cache_path)
    except Exception:
        # Clean up temp dir on failure
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    return cache_path


def _download_tarball(version: str, retries: int = 3) -> bytes:
    """Download the release tarball from GitHub with retries."""
    import time

    url = (
        f"https://github.com/{TEMPLATE_REPO}"
        f"/archive/refs/tags/{version}.tar.gz"
    )

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urlopen(url, timeout=60) as resp:  # noqa: S310
                return resp.read()
        except (HTTPError, URLError, OSError) as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)

    console.print(
        f"\n\n  [red]Failed to download templates after "
        f"{retries} attempts.[/red]\n"
        f"  URL: {url}\n"
        f"  Error: {last_error}\n\n"
        f"  [bold]Workarounds:[/bold]\n"
        f"  1. Check your internet connection\n"
        f"  2. If behind a proxy, set HTTPS_PROXY\n"
        f"  3. Download manually and use:\n"
        f"     lablink deploy --terraform-bundle /path/to/tarball.tar.gz\n"
    )
    raise SystemExit(1)


def _verify_checksum(data: bytes, version: str) -> None:
    """Verify SHA-256 checksum of the downloaded tarball."""
    actual = hashlib.sha256(data).hexdigest()
    if actual != TEMPLATE_SHA256:
        console.print(
            f"\n  [red]Checksum mismatch for {version}![/red]\n"
            f"  Expected: {TEMPLATE_SHA256}\n"
            f"  Got:      {actual}\n"
            f"  The download may be corrupted or tampered with.\n"
        )
        raise SystemExit(1)


def _extract_terraform_files(data: bytes, dest: Path) -> None:
    """Extract Terraform files from tarball with safety checks."""
    dest.mkdir(parents=True, exist_ok=True)

    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            # Find the lablink-infrastructure/ prefix
            parts = Path(member.name).parts
            try:
                infra_idx = parts.index("lablink-infrastructure")
            except ValueError:
                continue

            # Get the relative path within lablink-infrastructure/
            rel_parts = parts[infra_idx + 1 :]
            if not rel_parts:
                continue

            rel_path = Path(*rel_parts)

            # Security: reject path traversal
            if ".." in rel_parts:
                continue

            # Security: only allow whitelisted extensions
            suffix = rel_path.suffix
            if suffix and suffix not in _ALLOWED_EXTENSIONS:
                continue

            # Skip directories (we create them as needed)
            if member.isdir():
                continue

            # Extract to dest
            out_path = dest / rel_path
            out_path.parent.mkdir(parents=True, exist_ok=True)

            fileobj = tar.extractfile(member)
            if fileobj:
                out_path.write_bytes(fileobj.read())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/cli && PYTHONPATH=src pytest tests/test_terraform_source.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/cli/src/lablink_cli/terraform_source.py packages/cli/tests/test_terraform_source.py
git commit -m "feat(cli): add terraform_source module for download and cache"
```

---

### Task 3: Update `deploy.py` to use `terraform_source`

**Files:**
- Modify: `packages/cli/src/lablink_cli/commands/deploy.py:1-90`
- Modify: `packages/cli/tests/test_deploy.py:20-73`

- [ ] **Step 1: Update deploy tests to mock `get_terraform_files`**

Replace `TestPrepareWorkingDir` in `packages/cli/tests/test_deploy.py`:

```python
class TestPrepareWorkingDir:
    @patch("lablink_cli.commands.deploy.get_terraform_files")
    @patch("lablink_cli.commands.deploy.get_deploy_dir")
    @patch("lablink_cli.commands.deploy.save_config")
    def test_creates_directory(
        self, mock_save, mock_deploy_dir, mock_get_tf, mock_cfg, tmp_path
    ):
        deploy_dir = tmp_path / "deploy"
        mock_deploy_dir.return_value = deploy_dir

        # Simulate cached terraform files
        tf_cache = tmp_path / "tf_cache"
        tf_cache.mkdir()
        (tf_cache / "main.tf").write_text('variable "region" {}')
        (tf_cache / "variables.tf").write_text("# variables")
        (tf_cache / "user_data.sh").write_text("#!/bin/bash")
        mock_get_tf.return_value = tf_cache

        result = _prepare_working_dir(mock_cfg)
        assert result == deploy_dir
        assert (deploy_dir / "config").exists()
        assert (deploy_dir / "main.tf").exists()
        assert (deploy_dir / "user_data.sh").exists()

    @patch("lablink_cli.commands.deploy.get_terraform_files")
    @patch("lablink_cli.commands.deploy.get_deploy_dir")
    @patch("lablink_cli.commands.deploy.save_config")
    def test_copies_hcl_files(
        self, mock_save, mock_deploy_dir, mock_get_tf, mock_cfg, tmp_path
    ):
        deploy_dir = tmp_path / "deploy"
        mock_deploy_dir.return_value = deploy_dir

        tf_cache = tmp_path / "tf_cache"
        tf_cache.mkdir()
        (tf_cache / "main.tf").write_text('variable "region" {}')
        (tf_cache / "backend-dev.hcl").write_text("# dev")
        mock_get_tf.return_value = tf_cache

        result = _prepare_working_dir(mock_cfg)
        assert (result / "backend-dev.hcl").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/cli && PYTHONPATH=src pytest tests/test_deploy.py::TestPrepareWorkingDir -v`
Expected: FAIL because `deploy.py` still uses `TERRAFORM_SRC` and doesn't import `get_terraform_files`

- [ ] **Step 3: Update `deploy.py`**

In `packages/cli/src/lablink_cli/commands/deploy.py`:

Remove the `TERRAFORM_SRC` constant (lines 25-28):
```python
# DELETE these lines:
# Bundled terraform files shipped with the CLI package
TERRAFORM_SRC = (
    Path(__file__).resolve().parent.parent / "terraform"
)
```

Add import at the top (after existing imports):
```python
from lablink_cli.terraform_source import get_terraform_files
```

Replace `_prepare_working_dir` (lines 31-90) with:

```python
def _prepare_working_dir(
    cfg: Config,
    *,
    template_version: str | None = None,
    terraform_bundle: str | None = None,
) -> Path:
    """Set up the Terraform working directory.

    Downloads (or loads from cache/bundle) the template's .tf files,
    copies them into the deploy directory, and writes config/config.yaml.
    """
    from lablink_cli import TEMPLATE_VERSION

    version = template_version or TEMPLATE_VERSION
    skip_checksum = template_version is not None

    if skip_checksum and template_version:
        from rich.console import Console
        Console().print(
            f"  [yellow]Warning: using override version {template_version}, "
            f"skipping checksum verification[/yellow]"
        )

    tf_source = get_terraform_files(
        version,
        bundle_path=terraform_bundle,
        skip_checksum=skip_checksum,
    )

    deploy_dir = get_deploy_dir(cfg)
    deploy_dir.mkdir(parents=True, exist_ok=True)

    # Copy .tf and .hcl files
    for src_file in tf_source.glob("*.tf"):
        shutil.copy2(src_file, deploy_dir / src_file.name)
    for src_file in tf_source.glob("*.hcl"):
        shutil.copy2(src_file, deploy_dir / src_file.name)

    # Copy user_data.sh
    user_data_src = tf_source / "user_data.sh"
    if user_data_src.exists():
        shutil.copy2(user_data_src, deploy_dir / "user_data.sh")

    # Copy .terraform.lock.hcl if present
    lock_file = tf_source / ".terraform.lock.hcl"
    if lock_file.exists():
        shutil.copy2(lock_file, deploy_dir / ".terraform.lock.hcl")

    # Write config/config.yaml
    config_dir = deploy_dir / "config"
    config_dir.mkdir(exist_ok=True)
    save_config(cfg, config_dir / "config.yaml")

    # Copy custom startup script if configured
    if cfg.startup_script.enabled and cfg.startup_script.path:
        user_script = Path.home() / ".lablink" / "custom-startup.sh"
        if user_script.exists():
            src_startup = user_script
        else:
            src_startup = tf_source / cfg.startup_script.path

        if src_startup.exists():
            dest_startup = deploy_dir / "config" / "custom-startup.sh"
            dest_startup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_startup, dest_startup)

    return deploy_dir
```

Note: The region string replacement hack is removed. Region will be passed as a Terraform variable (Task 5).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/cli && PYTHONPATH=src pytest tests/test_deploy.py::TestPrepareWorkingDir -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/cli/src/lablink_cli/commands/deploy.py packages/cli/tests/test_deploy.py
git commit -m "refactor(cli): use terraform_source instead of bundled files in deploy"
```

---

### Task 4: Add `--template-version` and `--terraform-bundle` flags to CLI

**Files:**
- Modify: `packages/cli/src/lablink_cli/app.py:89-101`
- Modify: `packages/cli/src/lablink_cli/commands/deploy.py` (`run_deploy` signature)
- Modify: `packages/cli/tests/test_app.py` (if deploy command tests exist)

- [ ] **Step 1: Update the `deploy` command in `app.py`**

Replace the `deploy` command (lines 89-101) in `packages/cli/src/lablink_cli/app.py`:

```python
@app.command()
def deploy(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
    template_version: str = typer.Option(
        None,
        "--template-version",
        help="Override the pinned template version (e.g. v0.2.0). "
        "Skips checksum verification.",
    ),
    terraform_bundle: str = typer.Option(
        None,
        "--terraform-bundle",
        help="Path to a local template tarball for offline deploys.",
    ),
) -> None:
    """Deploy LabLink infrastructure with Terraform."""
    from lablink_cli.commands.deploy import run_deploy

    run_deploy(
        _load_cfg(config),
        template_version=template_version,
        terraform_bundle=terraform_bundle,
    )
```

- [ ] **Step 2: Update `run_deploy` signature in `deploy.py`**

In `packages/cli/src/lablink_cli/commands/deploy.py`, update `run_deploy` (line 206) to accept and pass the new parameters:

```python
def run_deploy(
    cfg: Config,
    *,
    template_version: str | None = None,
    terraform_bundle: str | None = None,
) -> None:
    """Deploy LabLink infrastructure."""
```

And update the call to `_prepare_working_dir` (line 224):

```python
    deploy_dir = _prepare_working_dir(
        cfg,
        template_version=template_version,
        terraform_bundle=terraform_bundle,
    )
```

- [ ] **Step 3: Run the full deploy test suite**

Run: `cd packages/cli && PYTHONPATH=src pytest tests/test_deploy.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add packages/cli/src/lablink_cli/app.py packages/cli/src/lablink_cli/commands/deploy.py
git commit -m "feat(cli): add --template-version and --terraform-bundle flags to deploy"
```

---

### Task 5: Pass region as Terraform variable

**Files:**
- Modify: `packages/cli/src/lablink_cli/commands/deploy.py` (`_terraform_init`, `run_deploy`)
- Modify: `packages/cli/tests/test_deploy.py`

- [ ] **Step 1: Write test for region variable**

Add to `TestPrepareWorkingDir` in `packages/cli/tests/test_deploy.py`:

```python
    @patch("lablink_cli.commands.deploy.get_terraform_files")
    @patch("lablink_cli.commands.deploy.get_deploy_dir")
    @patch("lablink_cli.commands.deploy.save_config")
    def test_no_region_string_replacement(
        self, mock_save, mock_deploy_dir, mock_get_tf, mock_cfg, tmp_path
    ):
        """Region should NOT be string-replaced in main.tf."""
        deploy_dir = tmp_path / "deploy"
        mock_deploy_dir.return_value = deploy_dir
        mock_cfg.app.region = "eu-west-1"

        tf_cache = tmp_path / "tf_cache"
        tf_cache.mkdir()
        # Simulate template with region variable (not hardcoded)
        (tf_cache / "main.tf").write_text(
            'provider "aws" {\n  region = var.region\n}'
        )
        mock_get_tf.return_value = tf_cache

        result = _prepare_working_dir(mock_cfg)
        content = (result / "main.tf").read_text()
        # File should be unchanged — region is passed via -var, not replaced
        assert "var.region" in content
        assert "eu-west-1" not in content
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd packages/cli && PYTHONPATH=src pytest tests/test_deploy.py::TestPrepareWorkingDir::test_no_region_string_replacement -v`
Expected: PASS (the string replacement was already removed in Task 3)

- [ ] **Step 3: Add `-var=region=` to terraform plan and destroy commands**

In `packages/cli/src/lablink_cli/commands/deploy.py`, update the `terraform plan` call in `run_deploy` (around line 257):

```python
    _run_terraform(
        [
            "plan",
            f"-var=deployment_name={cfg.deployment_name}",
            f"-var=environment={cfg.environment}",
            f"-var=region={cfg.app.region}",
            "-out=tfplan",
        ],
        cwd=deploy_dir,
    )
```

And the `terraform destroy` call in `run_destroy` (around line 567):

```python
    _run_terraform(
        [
            "destroy",
            "-auto-approve",
            f"-var=deployment_name={cfg.deployment_name}",
            f"-var=environment={cfg.environment}",
            f"-var=region={cfg.app.region}",
        ],
        cwd=deploy_dir,
    )
```

- [ ] **Step 4: Remove the old region replacement test**

In `packages/cli/tests/test_deploy.py`, delete the `test_region_override` test method entirely (it tested the old string-replacement behavior which no longer exists).

- [ ] **Step 5: Run tests**

Run: `cd packages/cli && PYTHONPATH=src pytest tests/test_deploy.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add packages/cli/src/lablink_cli/commands/deploy.py packages/cli/tests/test_deploy.py
git commit -m "refactor(cli): pass region as Terraform variable instead of string replacement"
```

---

### Task 6: Delete bundled Terraform files and update `pyproject.toml`

**Files:**
- Delete: `packages/cli/src/lablink_cli/terraform/` (entire directory)
- Modify: `packages/cli/pyproject.toml:29-30, 38-39`

- [ ] **Step 1: Delete the bundled terraform directory**

```bash
rm -rf packages/cli/src/lablink_cli/terraform
```

- [ ] **Step 2: Update `pyproject.toml`**

In `packages/cli/pyproject.toml`, remove the `package-data` section (lines 29-30):

```toml
# DELETE these lines:
[tool.setuptools.package-data]
lablink_cli = ["terraform/**/*"]
```

And update the coverage omit (lines 35-39) to remove the terraform exclusion:

```toml
[tool.coverage.run]
omit = [
    "src/lablink_cli/tui/*",
]
```

- [ ] **Step 3: Run the full test suite**

Run: `cd packages/cli && PYTHONPATH=src pytest tests/ -v`
Expected: All tests PASS. No test should depend on the bundled terraform files.

- [ ] **Step 4: Commit**

```bash
git add -A packages/cli/src/lablink_cli/terraform packages/cli/pyproject.toml
git commit -m "chore(cli): remove bundled Terraform files, update pyproject.toml

Terraform files are now downloaded from lablink-template releases
at deploy time. See #313."
```

---

### Task 7: Create `v0.1.0` tag in lablink-template and update SHA-256

**Files:**
- Modify: `packages/cli/src/lablink_cli/__init__.py` (update `TEMPLATE_SHA256`)

This task requires coordination with the lablink-template repo.

- [ ] **Step 1: Add `variable "region"` to the template's `main.tf`**

In the lablink-template repo, edit `lablink-infrastructure/main.tf`. Add a `region` variable:

```hcl
variable "region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-west-2"
}
```

And update the provider block:

```hcl
provider "aws" {
  region = var.region
```

- [ ] **Step 2: Commit and push in lablink-template**

```bash
cd /c/repos/lablink-template
git checkout -b feature/add-region-variable
# ... make the changes above ...
git add lablink-infrastructure/main.tf
git commit -m "feat: add region as Terraform variable for CLI compatibility"
git push -u origin feature/add-region-variable
```

Then merge to `main` (via PR or direct push per your workflow).

- [ ] **Step 3: Create the `v0.1.0` tag**

```bash
cd /c/repos/lablink-template
git checkout main
git pull
git tag v0.1.0
git push origin v0.1.0
```

- [ ] **Step 4: Compute and update the SHA-256 hash**

```bash
curl -sL https://github.com/talmolab/lablink-template/archive/refs/tags/v0.1.0.tar.gz | sha256sum
```

Take the resulting hash and update `packages/cli/src/lablink_cli/__init__.py`:

```python
TEMPLATE_SHA256 = "<paste actual hash here>"
```

- [ ] **Step 5: Run the integration test**

Run: `cd packages/cli && PYTHONPATH=src pytest tests/test_terraform_source.py -v`
Expected: All tests PASS (unit tests use mocks, so the hash placeholder doesn't matter for them)

- [ ] **Step 6: Commit**

```bash
git add packages/cli/src/lablink_cli/__init__.py
git commit -m "chore(cli): set TEMPLATE_SHA256 for v0.1.0 release"
```

---

### Task 8: Add integration test

**Files:**
- Modify: `packages/cli/tests/test_terraform_source.py`

- [ ] **Step 1: Add integration test**

Append to `packages/cli/tests/test_terraform_source.py`:

```python
@pytest.mark.integration
class TestIntegrationDownload:
    """Real download from GitHub. Run with: pytest -m integration"""

    def test_download_and_cache(self, tmp_path):
        from lablink_cli import TEMPLATE_VERSION
        from lablink_cli.terraform_source import (
            get_terraform_files,
            CACHE_DIR,
        )

        with patch.object(
            __import__("lablink_cli.terraform_source", fromlist=["CACHE_DIR"]),
            "CACHE_DIR",
            tmp_path / "cache",
        ):
            result = get_terraform_files(TEMPLATE_VERSION)

            # Expected files exist
            assert (result / "main.tf").exists()
            assert (result / "user_data.sh").exists()

            # Cache works on second call (no download)
            result2 = get_terraform_files(TEMPLATE_VERSION)
            assert result == result2
```

- [ ] **Step 2: Configure pytest to skip integration tests by default**

Add to `packages/cli/pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration: real network tests (deselect with '-m not integration')"]
addopts = "-m 'not integration'"
```

- [ ] **Step 3: Run unit tests (should skip integration)**

Run: `cd packages/cli && PYTHONPATH=src pytest tests/test_terraform_source.py -v`
Expected: All unit tests PASS, integration test is SKIPPED

- [ ] **Step 4: Commit**

```bash
git add packages/cli/tests/test_terraform_source.py packages/cli/pyproject.toml
git commit -m "test(cli): add integration test for real template download"
```

---

### Task 9: Final verification

- [ ] **Step 1: Run the full CLI test suite**

Run: `cd packages/cli && PYTHONPATH=src pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run linting**

Run: `ruff check packages/cli`
Expected: No errors

- [ ] **Step 3: Verify the bundled terraform directory is gone**

Run: `ls packages/cli/src/lablink_cli/terraform/ 2>/dev/null && echo "ERROR: directory still exists" || echo "OK: directory removed"`
Expected: `OK: directory removed`

- [ ] **Step 4: Verify no imports reference the old TERRAFORM_SRC**

Run: `grep -r "TERRAFORM_SRC" packages/cli/`
Expected: No matches
