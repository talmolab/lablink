"""Tests for lablink_cli template constants and terraform_source."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from lablink_cli import TEMPLATE_REPO, TEMPLATE_VERSION, TEMPLATE_SHA256
from lablink_cli.terraform_source import (
    get_terraform_files,
    _download_tarball,
    _extract_terraform_files,
)


class TestTemplateConstants:
    def test_repo_format(self):
        assert "/" in TEMPLATE_REPO
        assert TEMPLATE_REPO == "talmolab/lablink-template"

    def test_version_starts_with_v(self):
        assert TEMPLATE_VERSION.startswith("v")

    def test_sha256_is_hex(self):
        assert len(TEMPLATE_SHA256) == 64
        int(TEMPLATE_SHA256, 16)  # raises if not valid hex


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
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"data"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.side_effect = [
            URLError("network error"),
            URLError("network error"),
            mock_resp,
        ]
        result = _download_tarball("v0.1.0", retries=3)
        assert result == b"data"
        assert mock_urlopen.call_count == 3

    @patch("lablink_cli.terraform_source.urlopen")
    def test_raises_after_all_retries_exhausted(self, mock_urlopen):
        mock_urlopen.side_effect = URLError("network error")
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
    def test_cache_miss_downloads(self, mock_verify, mock_download, tmp_path):
        mock_download.return_value = _make_test_tarball(tmp_path)

        with patch(
            "lablink_cli.terraform_source.CACHE_DIR",
            tmp_path / "cache",
        ):
            result = get_terraform_files("v0.1.0")

        mock_download.assert_called_once_with("v0.1.0", retries=3)
        assert (result / "main.tf").exists()

    @patch("lablink_cli.terraform_source._download_tarball")
    def test_cache_hit_skips_download(self, mock_download, tmp_path):
        cache_dir = tmp_path / "cache" / "v0.1.0"
        cache_dir.mkdir(parents=True)
        (cache_dir / "main.tf").write_text("# cached")

        with patch(
            "lablink_cli.terraform_source.CACHE_DIR",
            tmp_path / "cache",
        ):
            result = get_terraform_files("v0.1.0")

        mock_download.assert_not_called()
        assert result == cache_dir

    @patch("lablink_cli.terraform_source._download_tarball")
    def test_bundle_path_extracts_local_tarball(self, mock_download, tmp_path):
        """--terraform-bundle should extract from local file, no download."""
        tarball_data = _make_test_tarball(tmp_path)
        bundle_file = tmp_path / "template.tar.gz"
        bundle_file.write_bytes(tarball_data)

        with patch(
            "lablink_cli.terraform_source.CACHE_DIR",
            tmp_path / "cache",
        ):
            result = get_terraform_files(
                "v0.1.0",
                bundle_path=str(bundle_file),
                skip_checksum=True,
            )

        mock_download.assert_not_called()
        assert (result / "main.tf").exists()
        assert (result / "alb.tf").exists()
        assert (result / "user_data.sh").exists()

    @patch("lablink_cli.terraform_source._download_tarball")
    def test_bundle_path_ignores_cache(self, mock_download, tmp_path):
        """Bundle should work even when cache already exists."""
        # Pre-populate cache with different content
        cache_dir = tmp_path / "cache" / "v0.1.0"
        cache_dir.mkdir(parents=True)
        (cache_dir / "main.tf").write_text("# old cached")

        tarball_data = _make_test_tarball(tmp_path)
        bundle_file = tmp_path / "template.tar.gz"
        bundle_file.write_bytes(tarball_data)

        with patch(
            "lablink_cli.terraform_source.CACHE_DIR",
            tmp_path / "cache",
        ):
            # Cache hit returns existing cache, bundle is not used
            result = get_terraform_files(
                "v0.1.0",
                bundle_path=str(bundle_file),
                skip_checksum=True,
            )

        # Cache hit takes priority — existing cache returned
        assert result == cache_dir
        assert (result / "main.tf").read_text() == "# old cached"


@pytest.mark.integration
class TestIntegrationDownload:
    """Real download from GitHub. Run with: pytest -m integration"""

    def test_download_and_cache(self, tmp_path):
        with patch(
            "lablink_cli.terraform_source.CACHE_DIR",
            tmp_path / "cache",
        ), patch("lablink_cli.terraform_source._verify_checksum"):
            result = get_terraform_files(TEMPLATE_VERSION)

            # Expected files exist
            assert (result / "main.tf").exists()
            assert (result / "user_data.sh").exists()

            # Cache works on second call (no download)
            result2 = get_terraform_files(TEMPLATE_VERSION)
            assert result == result2
