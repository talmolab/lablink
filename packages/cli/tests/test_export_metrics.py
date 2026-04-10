"""Tests for lablink_cli.commands.export_metrics."""

from __future__ import annotations

import csv
import json
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from lablink_cli.commands.export_metrics import run_export_metrics


class TestRunExportMetrics:
    def test_writes_csv(self, mock_cfg, tmp_path):
        """Test that export writes a valid CSV file."""
        output_path = tmp_path / "metrics.csv"

        response_body = json.dumps({
            "vms": [
                {
                    "hostname": "vm-1",
                    "useremail": "user@example.com",
                    "inuse": False,
                    "healthy": "Healthy",
                    "status": "running",
                    "terraformapplydurationseconds": 45.0,
                    "createdat": "2023-01-01T00:00:00",
                },
                {
                    "hostname": "vm-2",
                    "useremail": "user2@example.com",
                    "inuse": True,
                    "healthy": "Healthy",
                    "status": "running",
                    "terraformapplydurationseconds": 50.0,
                    "createdat": "2023-01-01T00:01:00",
                },
            ],
            "count": 2,
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body

        with (
            patch(
                "lablink_cli.commands.export_metrics.get_allocator_url",
                return_value="http://1.2.3.4",
            ),
            patch(
                "lablink_cli.commands.export_metrics.resolve_admin_credentials",
                return_value=("admin", "secret"),
            ),
            patch(
                "lablink_cli.commands.export_metrics.urlopen",
                return_value=mock_resp,
            ),
        ):
            run_export_metrics(mock_cfg, output=str(output_path))

        assert output_path.exists()
        with open(output_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 2
        assert rows[0]["hostname"] == "vm-1"
        assert rows[1]["hostname"] == "vm-2"
        assert "terraformapplydurationseconds" in reader.fieldnames

    def test_include_logs_flag(self, mock_cfg, tmp_path):
        """Test that include_logs=True sends include_logs=true in URL."""
        output_path = tmp_path / "metrics.csv"

        response_body = json.dumps({
            "vms": [{"hostname": "vm-1", "cloudinitlogs": "logs"}],
            "count": 1,
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body

        captured_url = None

        def fake_urlopen(req, **kwargs):
            nonlocal captured_url
            captured_url = req.full_url
            return mock_resp

        with (
            patch(
                "lablink_cli.commands.export_metrics.get_allocator_url",
                return_value="http://1.2.3.4",
            ),
            patch(
                "lablink_cli.commands.export_metrics.resolve_admin_credentials",
                return_value=("admin", "secret"),
            ),
            patch(
                "lablink_cli.commands.export_metrics.urlopen",
                side_effect=fake_urlopen,
            ),
        ):
            run_export_metrics(
                mock_cfg, output=str(output_path), include_logs=True
            )

        assert "include_logs=true" in captured_url

    def test_no_vms(self, mock_cfg, tmp_path, capsys):
        """Test warning message when no VMs returned."""
        output_path = tmp_path / "metrics.csv"

        response_body = json.dumps({"vms": [], "count": 0}).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body

        with (
            patch(
                "lablink_cli.commands.export_metrics.get_allocator_url",
                return_value="http://1.2.3.4",
            ),
            patch(
                "lablink_cli.commands.export_metrics.resolve_admin_credentials",
                return_value=("admin", "secret"),
            ),
            patch(
                "lablink_cli.commands.export_metrics.urlopen",
                return_value=mock_resp,
            ),
        ):
            run_export_metrics(mock_cfg, output=str(output_path))

        # CSV file should not be created when there are no VMs
        assert not output_path.exists()

    def test_http_error(self, mock_cfg, tmp_path):
        """Test graceful handling of HTTP errors."""
        output_path = tmp_path / "metrics.csv"

        error = HTTPError(
            url="http://1.2.3.4/api/export-metrics",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=BytesIO(b""),
        )

        with (
            patch(
                "lablink_cli.commands.export_metrics.get_allocator_url",
                return_value="http://1.2.3.4",
            ),
            patch(
                "lablink_cli.commands.export_metrics.resolve_admin_credentials",
                return_value=("admin", "secret"),
            ),
            patch(
                "lablink_cli.commands.export_metrics.urlopen",
                side_effect=error,
            ),
            pytest.raises(SystemExit),
        ):
            run_export_metrics(mock_cfg, output=str(output_path))

    def test_no_allocator_url(self, mock_cfg, tmp_path):
        """Test error when allocator URL can't be determined."""
        with (
            patch(
                "lablink_cli.commands.export_metrics.get_allocator_url",
                return_value="",
            ),
            pytest.raises(SystemExit),
        ):
            run_export_metrics(mock_cfg, output=str(tmp_path / "m.csv"))
