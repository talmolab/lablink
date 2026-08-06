"""Tests for lablink_cli.commands.export_metrics."""

from __future__ import annotations

import csv
import json
from contextlib import ExitStack
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from lablink_cli import deployment_metrics
from lablink_cli.commands.export_metrics import (
    _export_allocator_metrics,
    run_export_metrics,
)


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
                "lablink_cli.api.urlopen",
                return_value=mock_resp,
            ),
        ):
            run_export_metrics(mock_cfg, output=str(output_path), client=True)

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
                "lablink_cli.api.urlopen",
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
                "lablink_cli.api.urlopen",
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
                "lablink_cli.api.urlopen",
                side_effect=error,
            ),
            pytest.raises(SystemExit),
        ):
            run_export_metrics(mock_cfg, output=str(output_path))

    def test_401_names_the_rejected_admin_credentials(
        self, mock_cfg, tmp_path, capsys
    ):
        """A bare "HTTP 401: Unauthorized" doesn't say what to fix."""
        error = HTTPError(
            url="http://1.2.3.4/api/export-metrics",
            code=401,
            msg="Unauthorized",
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
                return_value=("admin", "wrong-pw"),
            ),
            patch(
                "lablink_cli.api.urlopen",
                side_effect=error,
            ),
            pytest.raises(SystemExit) as exc,
        ):
            run_export_metrics(mock_cfg, output=str(tmp_path / "m.csv"))

        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "401" in out
        assert "admin" in out
        assert "admin_user" in out
        assert "admin_password" in out

    def test_non_401_http_error_stays_generic(
        self, mock_cfg, tmp_path, capsys
    ):
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
                "lablink_cli.api.urlopen",
                side_effect=error,
            ),
            pytest.raises(SystemExit),
        ):
            run_export_metrics(mock_cfg, output=str(tmp_path / "m.csv"))

        out = capsys.readouterr().out
        assert "500" in out
        # Credential guidance would be misleading here.
        assert "admin_password" not in out

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

    def test_writes_json(self, mock_cfg, tmp_path):
        """Test that format='json' writes a valid JSON file."""
        output_path = tmp_path / "metrics.json"

        vms = [
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
        ]
        response_body = json.dumps({"vms": vms, "count": 2}).encode()

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
                "lablink_cli.api.urlopen",
                return_value=mock_resp,
            ),
        ):
            run_export_metrics(
                mock_cfg,
                output=str(output_path),
                format="json",
                client=True,
            )

        assert output_path.exists()
        with open(output_path) as f:
            data = json.load(f)

        assert data == vms

    def test_invalid_format(self, mock_cfg, tmp_path):
        """Test that an invalid format value raises an error."""
        with pytest.raises(SystemExit):
            run_export_metrics(
                mock_cfg,
                output=str(tmp_path / "m.txt"),
                format="xml",
            )

    def test_default_output_matches_json_format(
        self, mock_cfg, tmp_path, monkeypatch
    ):
        """--client + format=json + no -o → metrics_client.json default."""
        monkeypatch.chdir(tmp_path)

        response_body = json.dumps({
            "vms": [{"hostname": "vm-1"}],
            "count": 1,
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
                "lablink_cli.api.urlopen",
                return_value=mock_resp,
            ),
        ):
            run_export_metrics(
                mock_cfg, output=None, format="json", client=True
            )

        assert (tmp_path / "metrics_client.json").exists()
        assert not (tmp_path / "metrics_client.csv").exists()

    def test_malformed_json_response(self, mock_cfg, tmp_path):
        """Test graceful handling when the response body isn't valid JSON."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html>500 bad gateway</html>"

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
                "lablink_cli.api.urlopen",
                return_value=mock_resp,
            ),
            pytest.raises(SystemExit),
        ):
            run_export_metrics(
                mock_cfg, output=str(tmp_path / "m.csv")
            )

    def test_default_output_matches_csv_format(
        self, mock_cfg, tmp_path, monkeypatch
    ):
        """--client + format=csv + no -o → metrics_client.csv default."""
        monkeypatch.chdir(tmp_path)

        response_body = json.dumps({
            "vms": [{"hostname": "vm-1"}],
            "count": 1,
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
                "lablink_cli.api.urlopen",
                return_value=mock_resp,
            ),
        ):
            run_export_metrics(
                mock_cfg, output=None, format="csv", client=True
            )

        assert (tmp_path / "metrics_client.csv").exists()


# ------------------------------------------------------------------
# Allocator metrics sidecar (issue #317)
# ------------------------------------------------------------------
def _seed_allocator_cache(cache_dir, monkeypatch, records):
    """Point DEPLOYMENTS_DIR at cache_dir and write the given records as JSON files."""
    monkeypatch.setattr(deployment_metrics, "DEPLOYMENTS_DIR", cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    for i, rec in enumerate(records):
        (cache_dir / f"deploy-{i}.json").write_text(json.dumps(rec))


def _vm_response_body():
    return json.dumps(
        {"vms": [{"hostname": "vm-1"}], "count": 1}
    ).encode()


def _patch_export_calls(mock_resp):
    return [
        patch(
            "lablink_cli.commands.export_metrics.get_allocator_url",
            return_value="http://1.2.3.4",
        ),
        patch(
            "lablink_cli.commands.export_metrics.resolve_admin_credentials",
            return_value=("admin", "secret"),
        ),
        patch(
            "lablink_cli.api.urlopen",
            return_value=mock_resp,
        ),
    ]


class TestExportMetricsFlags:
    """Tests for the --client / --allocator flag semantics (issue #317).

    Default (no flags) = both. Each flag acts as a filter when given alone.
    """

    def test_both_flags_writes_csv_sidecar(
        self, mock_cfg, tmp_path, monkeypatch
    ):
        """Both flags + -o metrics.csv → _client + _allocator sidecar files.

        Records carry mock_cfg's deployment_name: allocator records are
        scoped to the current deployment, so foreign names would be filtered
        out and there'd be no sidecar to assert on.
        """
        records = [
            {
                "deployment_name": "mylab",
                "region": "us-east-1",
                "status": "success",
            },
            {
                "deployment_name": "mylab",
                "region": "us-west-2",
                "status": "failed",
            },
        ]
        _seed_allocator_cache(tmp_path / "cache", monkeypatch, records)

        mock_resp = MagicMock()
        mock_resp.read.return_value = _vm_response_body()

        base_path = tmp_path / "metrics.csv"
        client_path = tmp_path / "metrics_client.csv"
        allocator_path = tmp_path / "metrics_allocator.csv"

        with ExitStack() as stack:
            for cm in _patch_export_calls(mock_resp):
                stack.enter_context(cm)
            run_export_metrics(
                mock_cfg,
                output=str(base_path),
                client=True,
                allocator=True,
            )

        assert client_path.exists()
        assert allocator_path.exists()
        # -o base name was not itself written
        assert not base_path.exists()
        with open(allocator_path) as f:
            rows = list(csv.DictReader(f))
        assert {r["region"] for r in rows} == {"us-east-1", "us-west-2"}

    def test_both_flags_writes_json_sidecar(
        self, mock_cfg, tmp_path, monkeypatch
    ):
        """JSON mode: both flags write _client.json and _allocator.json sidecars."""
        records = [
            {"deployment_name": "mylab", "status": "success"},
            {"deployment_name": "mylab", "status": "failed"},
        ]
        _seed_allocator_cache(tmp_path / "cache", monkeypatch, records)

        mock_resp = MagicMock()
        mock_resp.read.return_value = _vm_response_body()

        base_path = tmp_path / "metrics.json"
        client_path = tmp_path / "metrics_client.json"
        allocator_path = tmp_path / "metrics_allocator.json"

        with ExitStack() as stack:
            for cm in _patch_export_calls(mock_resp):
                stack.enter_context(cm)
            run_export_metrics(
                mock_cfg,
                output=str(base_path),
                format="json",
                client=True,
                allocator=True,
            )

        assert client_path.exists()
        assert allocator_path.exists()
        assert not base_path.exists()
        data = json.loads(allocator_path.read_text())
        assert data["count"] == 2
        assert {r["status"] for r in data["allocator_metrics"]} == {
            "success",
            "failed",
        }

    def test_no_flags_defaults_to_both(self, mock_cfg, tmp_path, monkeypatch):
        """No flags → same as --client --allocator (-o is treated as base name)."""
        records = [{"deployment_name": "mylab", "status": "success"}]
        _seed_allocator_cache(tmp_path / "cache", monkeypatch, records)

        mock_resp = MagicMock()
        mock_resp.read.return_value = _vm_response_body()

        base_path = tmp_path / "metrics.csv"
        client_path = tmp_path / "metrics_client.csv"
        allocator_path = tmp_path / "metrics_allocator.csv"

        with ExitStack() as stack:
            for cm in _patch_export_calls(mock_resp):
                stack.enter_context(cm)
            run_export_metrics(mock_cfg, output=str(base_path))

        assert client_path.exists()
        assert allocator_path.exists()
        assert not base_path.exists()

    def test_allocator_records_scoped_to_deployment(
        self, mock_cfg, tmp_path, monkeypatch
    ):
        """Other deployments' cached records stay out of this export.

        The cache is global, so before scoping an export named for one
        deployment carried every deployment's rows.
        """
        records = [
            {"deployment_name": "mylab", "status": "success"},
            {"deployment_name": "someone-elses-lab", "status": "success"},
            {"deployment_name": "old-aws-lab", "status": "failed"},
        ]
        _seed_allocator_cache(tmp_path / "cache", monkeypatch, records)

        allocator_path = tmp_path / "alloc.csv"
        _export_allocator_metrics(
            allocator_path, "csv", deployment_name=mock_cfg.deployment_name
        )

        with open(allocator_path) as f:
            rows = list(csv.DictReader(f))
        assert [r["deployment_name"] for r in rows] == ["mylab"]

    def test_allocator_records_scoped_to_provider(
        self, tmp_path, monkeypatch, capsys
    ):
        """A reused deployment_name must not leak its AWS rows into BYO.

        The real case: a `sleap-lablink` config switched from aws to manual.
        Name-scoping alone still matched the old AWS Terraform records.
        """
        records = [
            {"deployment_name": "sleap-lablink", "region": "us-west-2"},
            {
                "deployment_name": "sleap-lablink",
                "provider": "aws",
                "region": "us-west-2",
            },
        ]
        _seed_allocator_cache(tmp_path / "cache", monkeypatch, records)

        allocator_path = tmp_path / "alloc.csv"
        _export_allocator_metrics(
            allocator_path,
            "csv",
            deployment_name="sleap-lablink",
            provider="manual",
        )

        assert not allocator_path.exists()
        assert "sleap-lablink" in capsys.readouterr().out

        # Same cache, AWS config: both rows export, including the legacy one
        # written before the provider field existed.
        aws_path = tmp_path / "aws.csv"
        _export_allocator_metrics(
            aws_path, "csv", deployment_name="sleap-lablink", provider="aws"
        )
        with open(aws_path) as f:
            assert len(list(csv.DictReader(f))) == 2

    def test_allocator_empty_after_scoping_skips_file(
        self, mock_cfg, tmp_path, monkeypatch, capsys
    ):
        """A cache with no rows for this deployment writes nothing.

        The manual/compose deploy path records no allocator metrics at all,
        so this is the normal BYO outcome — it must not dump the AWS rows
        that happen to share the cache.
        """
        records = [{"deployment_name": "old-aws-lab", "status": "success"}]
        _seed_allocator_cache(tmp_path / "cache", monkeypatch, records)

        allocator_path = tmp_path / "alloc.csv"
        _export_allocator_metrics(
            allocator_path, "csv", deployment_name="byo-lab"
        )

        assert not allocator_path.exists()
        assert "byo-lab" in capsys.readouterr().out

    def test_client_only_skips_allocator_file(
        self, mock_cfg, tmp_path, monkeypatch
    ):
        """--client alone → no allocator sidecar even if cache is non-empty."""
        records = [{"deployment_name": "lab-a", "status": "success"}]
        _seed_allocator_cache(tmp_path / "cache", monkeypatch, records)

        mock_resp = MagicMock()
        mock_resp.read.return_value = _vm_response_body()

        output_path = tmp_path / "metrics.csv"
        sidecar_path = tmp_path / "metrics_allocator.csv"

        with ExitStack() as stack:
            for cm in _patch_export_calls(mock_resp):
                stack.enter_context(cm)
            run_export_metrics(
                mock_cfg, output=str(output_path), client=True
            )

        assert output_path.exists()
        assert not sidecar_path.exists()

    def test_allocator_only_skips_network(self, tmp_path, monkeypatch):
        """--allocator alone never calls the allocator (works after destroy)."""
        records = [{"deployment_name": "lab-a", "status": "success"}]
        _seed_allocator_cache(tmp_path / "cache", monkeypatch, records)

        with ExitStack() as stack:
            mock_url = stack.enter_context(
                patch(
                    "lablink_cli.commands.export_metrics.get_allocator_url"
                )
            )
            mock_creds = stack.enter_context(
                patch(
                    "lablink_cli.commands.export_metrics.resolve_admin_credentials"
                )
            )
            mock_open = stack.enter_context(
                patch("lablink_cli.api.urlopen")
            )

            run_export_metrics(
                None,
                output=str(tmp_path / "alloc.csv"),
                allocator=True,
            )

            mock_url.assert_not_called()
            mock_creds.assert_not_called()
            mock_open.assert_not_called()

    def test_allocator_only_writes_to_output_path(
        self, tmp_path, monkeypatch
    ):
        """--allocator alone with -o foo.csv → writes foo.csv (no sidecar suffix)."""
        records = [{"deployment_name": "lab-a", "status": "success"}]
        _seed_allocator_cache(tmp_path / "cache", monkeypatch, records)

        target = tmp_path / "alloc.csv"
        run_export_metrics(None, output=str(target), allocator=True)

        assert target.exists()
        # No sidecar-suffixed file should be created
        assert not (tmp_path / "alloc_allocator.csv").exists()

    def test_allocator_only_default_filename(
        self, tmp_path, monkeypatch
    ):
        """--allocator alone with no -o → defaults to metrics_allocator.<fmt>."""
        records = [{"deployment_name": "lab-a", "status": "success"}]
        _seed_allocator_cache(tmp_path / "cache", monkeypatch, records)
        monkeypatch.chdir(tmp_path)

        run_export_metrics(None, output=None, allocator=True)

        assert (tmp_path / "metrics_allocator.csv").exists()
        assert not (tmp_path / "metrics.csv").exists()

    def test_allocator_empty_cache_skips_file(
        self, tmp_path, monkeypatch
    ):
        """--allocator with empty cache → no file written, warning printed."""
        _seed_allocator_cache(tmp_path / "cache", monkeypatch, [])

        target = tmp_path / "alloc.csv"
        run_export_metrics(None, output=str(target), allocator=True)

        assert not target.exists()

    def test_vm_metrics_unchanged_when_cache_empty(
        self, mock_cfg, tmp_path, monkeypatch
    ):
        """--client JSON shape is a top-level VM list (regression guard)."""
        _seed_allocator_cache(tmp_path / "cache", monkeypatch, [])

        vms = [{"hostname": "vm-1", "status": "running"}]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"vms": vms, "count": 1}
        ).encode()

        output_path = tmp_path / "metrics.json"

        with ExitStack() as stack:
            for cm in _patch_export_calls(mock_resp):
                stack.enter_context(cm)
            run_export_metrics(
                mock_cfg,
                output=str(output_path),
                format="json",
                client=True,
            )

        # Existing contract: top-level JSON is the VM list (see test_writes_json).
        data = json.loads(output_path.read_text())
        assert data == vms
