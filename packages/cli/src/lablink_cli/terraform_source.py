"""Download and cache Terraform files from lablink-template releases."""

from __future__ import annotations

import hashlib
import io
import shutil
import tarfile
import tempfile
import time
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
        skip_checksum: If True, skip SHA-256 verification.

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
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
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
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    return cache_path


def _download_tarball(version: str, retries: int = 3) -> bytes:
    """Download the release tarball from GitHub with retries."""
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
