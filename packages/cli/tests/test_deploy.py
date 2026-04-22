"""Tests for lablink_cli.commands.deploy Terraform orchestration."""

from __future__ import annotations

import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from lablink_cli import deployment_metrics
from lablink_cli.api import (
    AllocatorAuthError,
    AllocatorNotFoundError,
    AllocatorUnavailableError,
)
from lablink_cli.commands.deploy import (
    _destroy_client_vms,
    _poll_allocator_health,
    _prepare_working_dir,
    _run_terraform,
    _terraform_destroy,
    run_deploy,
    run_destroy,
)


# ------------------------------------------------------------------
# _prepare_working_dir
# ------------------------------------------------------------------
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
        (tf_cache / "main.tf").write_text(
            'provider "aws" {\n  region = var.region\n}'
        )
        mock_get_tf.return_value = tf_cache

        result = _prepare_working_dir(mock_cfg)
        content = (result / "main.tf").read_text()
        # File should be unchanged — region is passed via -var, not replaced
        assert "var.region" in content
        assert "eu-west-1" not in content


# ------------------------------------------------------------------
# _run_terraform
# ------------------------------------------------------------------
class TestRunTerraform:
    @patch("subprocess.Popen")
    def test_success(self, mock_popen, tmp_path):
        proc = MagicMock()
        proc.stdout = iter(["Initializing...\n", "Complete!\n"])
        proc.wait.return_value = None
        proc.returncode = 0
        mock_popen.return_value = proc

        returncode = _run_terraform(["init"], cwd=tmp_path)
        assert returncode == 0
        mock_popen.assert_called_once()

    @patch("subprocess.Popen")
    def test_failure_raises(self, mock_popen, tmp_path):
        proc = MagicMock()
        proc.stdout = iter(["Error!\n"])
        proc.wait.return_value = None
        proc.returncode = 1
        mock_popen.return_value = proc

        with pytest.raises(SystemExit):
            _run_terraform(["apply"], cwd=tmp_path)

    @patch("subprocess.Popen")
    def test_failure_no_check(self, mock_popen, tmp_path):
        proc = MagicMock()
        proc.stdout = iter([])
        proc.wait.return_value = None
        proc.returncode = 1
        mock_popen.return_value = proc

        returncode = _run_terraform(
            ["output"], cwd=tmp_path, check=False
        )
        assert returncode == 1


# ------------------------------------------------------------------
# _destroy_client_vms
# ------------------------------------------------------------------
class TestDestroyClientVms:
    @patch("lablink_cli.commands.deploy.AllocatorAPI")
    @patch(
        "lablink_cli.commands.deploy.get_allocator_url",
        return_value="https://allocator.example.com",
    )
    def test_success(self, mock_url, mock_api_cls, mock_cfg):
        mock_api = MagicMock()
        mock_api.destroy_vms.return_value = {"status": "ok"}
        mock_api_cls.return_value = mock_api

        _destroy_client_vms(mock_cfg, "admin", "pass")
        mock_api.destroy_vms.assert_called_once()

    @patch("lablink_cli.commands.deploy.AllocatorAPI")
    @patch(
        "lablink_cli.commands.deploy.get_allocator_url",
        return_value="https://allocator.example.com",
    )
    def test_auth_error_exits(self, mock_url, mock_api_cls, mock_cfg):
        mock_api = MagicMock()
        mock_api.destroy_vms.side_effect = AllocatorAuthError("401")
        mock_api_cls.return_value = mock_api

        with pytest.raises(SystemExit):
            _destroy_client_vms(mock_cfg, "admin", "pass")

    @patch("lablink_cli.commands.deploy.AllocatorAPI")
    @patch(
        "lablink_cli.commands.deploy.get_allocator_url",
        return_value="https://allocator.example.com",
    )
    def test_unavailable_continues(self, mock_url, mock_api_cls, mock_cfg):
        mock_api = MagicMock()
        mock_api.destroy_vms.side_effect = AllocatorUnavailableError("502")
        mock_api_cls.return_value = mock_api

        _destroy_client_vms(mock_cfg, "admin", "pass")

    @patch("lablink_cli.commands.deploy.AllocatorAPI")
    @patch(
        "lablink_cli.commands.deploy.get_allocator_url",
        return_value="https://allocator.example.com",
    )
    def test_not_found_continues(self, mock_url, mock_api_cls, mock_cfg):
        mock_api = MagicMock()
        mock_api.destroy_vms.side_effect = AllocatorNotFoundError("404")
        mock_api_cls.return_value = mock_api

        _destroy_client_vms(mock_cfg, "admin", "pass")

    @patch(
        "lablink_cli.commands.deploy.get_allocator_url",
        return_value=None,
    )
    def test_no_url_skips(self, mock_url, mock_cfg):
        _destroy_client_vms(mock_cfg, "admin", "pass")


# ------------------------------------------------------------------
# _terraform_destroy
# ------------------------------------------------------------------
class TestTerraformDestroy:
    @patch("lablink_cli.commands.deploy.shutil.rmtree")
    @patch("lablink_cli.commands.deploy._run_terraform")
    @patch("lablink_cli.commands.deploy._terraform_init")
    @patch(
        "lablink_cli.commands.deploy.config_to_dict",
        return_value={"app": {}, "db": {}},
    )
    def test_runs_destroy_sequence(
        self,
        mock_cfg_dict,
        mock_tf_init,
        mock_tf_run,
        mock_rmtree,
        mock_cfg,
        tmp_path,
    ):
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        (deploy_dir / "backend.tf").write_text("")
        config_dir = deploy_dir / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("")

        _terraform_destroy(deploy_dir, mock_cfg, "admin", "pass")

        mock_tf_init.assert_called_once_with(deploy_dir, mock_cfg)
        mock_tf_run.assert_called_once()
        mock_rmtree.assert_called_once_with(deploy_dir)


# ------------------------------------------------------------------
# _poll_allocator_health
# ------------------------------------------------------------------
class TestPollAllocatorHealth:
    @patch("lablink_cli.commands.deploy.time")
    @patch("lablink_cli.commands.deploy.check_health_endpoint")
    def test_healthy_on_first_poll(self, mock_check, mock_time):
        """Returns immediately when allocator is healthy on first poll."""
        mock_time.monotonic.side_effect = [0.0, 5.0]
        mock_check.return_value = {
            "status": "pass",
            "healthy": True,
            "uptime_seconds": 30.0,
        }

        result = _poll_allocator_health("http://1.2.3.4:5000", max_wait=120)
        assert result["healthy"] is True
        assert result["elapsed"] == 5.0
        mock_time.sleep.assert_not_called()

    @patch("lablink_cli.commands.deploy.time")
    @patch("lablink_cli.commands.deploy.check_health_endpoint")
    def test_healthy_after_retries(self, mock_check, mock_time):
        """Keeps polling until healthy."""
        # monotonic: start, check1, sleep1, check2, sleep2, check3
        mock_time.monotonic.side_effect = [0.0, 3.0, 4.0, 6.0, 7.0, 9.0]
        mock_check.side_effect = [
            {"status": "unreachable", "healthy": False, "uptime_seconds": None},
            {"status": "starting", "healthy": False, "uptime_seconds": 2.0},
            {"status": "pass", "healthy": True, "uptime_seconds": 8.0},
        ]

        result = _poll_allocator_health("http://1.2.3.4:5000", max_wait=120)
        assert result["healthy"] is True
        assert mock_time.sleep.call_count == 2

    @patch("lablink_cli.commands.deploy.time")
    @patch("lablink_cli.commands.deploy.check_health_endpoint")
    def test_timeout(self, mock_check, mock_time):
        """Returns unhealthy after max_wait exceeded."""
        call_count = 0

        def mock_monotonic():
            nonlocal call_count
            val = call_count * 10.0
            call_count += 1
            return val

        mock_time.monotonic.side_effect = mock_monotonic
        mock_check.return_value = {
            "status": "unreachable",
            "healthy": False,
            "uptime_seconds": None,
        }

        result = _poll_allocator_health("http://1.2.3.4:5000", max_wait=30)
        assert result["healthy"] is False
        assert result["timed_out"] is True


# ------------------------------------------------------------------
# run_deploy — metrics instrumentation (issue #317)
# ------------------------------------------------------------------
def _patch_deploy_deps(deploy_dir):
    """Common mock context for run_deploy. Stubs everything except metrics wiring."""
    return [
        patch(
            "lablink_cli.commands.deploy._prepare_working_dir",
            return_value=deploy_dir,
        ),
        patch("lablink_cli.commands.deploy.check_credentials"),
        patch("lablink_cli.commands.deploy._get_session"),
        patch(
            "lablink_cli.commands.deploy._prompt_passwords",
            return_value={
                "admin_user": "admin",
                "admin_password": "pw",
                "db_password": "dbpw",
            },
        ),
        patch("lablink_cli.commands.deploy._terraform_init"),
        patch(
            "lablink_cli.commands.utils.get_terraform_outputs",
            return_value={"ec2_public_ip": "1.2.3.4"},
        ),
        patch(
            "lablink_cli.commands.deploy._poll_allocator_health",
            return_value={
                "healthy": True,
                "elapsed": 12.0,
                "timed_out": False,
                "uptime_seconds": 5.0,
            },
        ),
        patch("lablink_cli.commands.status.run_status"),
        patch("builtins.input", return_value="yes"),
    ]


class TestRunDeployMetrics:
    def test_writes_success_metrics(self, mock_cfg, tmp_path, monkeypatch):
        """Successful deploy → cache file with status='success' and all durations."""
        cache_dir = tmp_path / "cache"
        monkeypatch.setattr(
            deployment_metrics, "DEPLOYMENTS_DIR", cache_dir
        )

        deploy_dir = tmp_path / "deploy"
        (deploy_dir / "config").mkdir(parents=True)
        (deploy_dir / "config" / "config.yaml").write_text(
            "app: {}\ndb: {}\n"
        )

        with ExitStack() as stack:
            for cm in _patch_deploy_deps(deploy_dir):
                stack.enter_context(cm)
            stack.enter_context(
                patch("lablink_cli.commands.deploy._run_terraform")
            )
            run_deploy(mock_cfg)

        cache_files = list(cache_dir.glob("*.json"))
        assert len(cache_files) == 1, f"expected 1 cache file, got {cache_files}"

        data = json.loads(cache_files[0].read_text())
        assert data["status"] == "success"
        assert data["deployment_name"] == "mylab"
        assert data["region"] == "us-east-1"
        assert data["ssl_enabled"] is False  # mock_cfg has ssl.provider="none"
        assert data["template_version"] is not None
        assert data["allocator_deploy_start_time"] is not None
        assert data["allocator_deploy_end_time"] is not None
        assert data["allocator_terraform_init_duration_seconds"] is not None
        assert data["allocator_terraform_plan_duration_seconds"] is not None
        assert data["allocator_terraform_apply_duration_seconds"] is not None
        assert data["allocator_health_check_duration_seconds"] is not None
        assert data["allocator_total_deployment_duration_seconds"] is not None
        assert data["error"] is None

    def test_writes_failure_metrics_when_apply_raises(
        self, mock_cfg, tmp_path, monkeypatch
    ):
        """Failed apply → status='failed' with earlier phase durations preserved."""
        cache_dir = tmp_path / "cache"
        monkeypatch.setattr(
            deployment_metrics, "DEPLOYMENTS_DIR", cache_dir
        )

        deploy_dir = tmp_path / "deploy"
        (deploy_dir / "config").mkdir(parents=True)
        (deploy_dir / "config" / "config.yaml").write_text(
            "app: {}\ndb: {}\n"
        )

        def fail_on_apply(args, cwd=None, check=True):
            if args and args[0] == "apply":
                raise RuntimeError("terraform apply blew up")
            return 0

        with ExitStack() as stack:
            for cm in _patch_deploy_deps(deploy_dir):
                stack.enter_context(cm)
            stack.enter_context(
                patch(
                    "lablink_cli.commands.deploy._run_terraform",
                    side_effect=fail_on_apply,
                )
            )
            with pytest.raises(RuntimeError, match="terraform apply blew up"):
                run_deploy(mock_cfg)

        cache_files = list(cache_dir.glob("*.json"))
        assert len(cache_files) == 1

        data = json.loads(cache_files[0].read_text())
        assert data["status"] == "failed"
        assert "terraform apply blew up" in data["error"]
        assert (
            data["allocator_terraform_init_duration_seconds"] is not None
        ), "init succeeded — its duration should be persisted"
        assert (
            data["allocator_terraform_plan_duration_seconds"] is not None
        ), "plan succeeded — its duration should be persisted"
        # apply ran but raised — phase_timer's try/finally should still record duration
        assert (
            data["allocator_terraform_apply_duration_seconds"] is not None
        ), "apply duration should be recorded even on failure"
        assert (
            data["allocator_health_check_duration_seconds"] is None
        ), "health check should not have run after apply failed"


# ------------------------------------------------------------------
# run_destroy — export prompt before tearing down (issue #317)
# ------------------------------------------------------------------
def _patch_destroy_deps(deploy_dir, stack):
    """Enter run_destroy dep mocks into ``stack`` and return a dict of the mocks.

    Tests that need to assert against a mock (e.g. ``_terraform_destroy``) can
    look it up by key instead of re-patching — avoids shadowing the shared
    patch with a redundant second one.
    """
    return {
        "check_credentials": stack.enter_context(
            patch("lablink_cli.commands.deploy.check_credentials")
        ),
        "get_session": stack.enter_context(
            patch("lablink_cli.commands.deploy._get_session")
        ),
        "get_deploy_dir": stack.enter_context(
            patch(
                "lablink_cli.commands.deploy.get_deploy_dir",
                return_value=deploy_dir,
            )
        ),
        "resolve_admin_credentials": stack.enter_context(
            patch(
                "lablink_cli.commands.deploy.resolve_admin_credentials",
                return_value=("admin", "pw"),
            )
        ),
        "destroy_client_vms": stack.enter_context(
            patch("lablink_cli.commands.deploy._destroy_client_vms")
        ),
        "terraform_destroy": stack.enter_context(
            patch("lablink_cli.commands.deploy._terraform_destroy")
        ),
    }


def _setup_destroy_dir(deploy_dir):
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "terraform.tfstate").write_text("{}")


class TestRunDestroyExportPrompt:
    def test_prompts_and_runs_export_when_yes(self, mock_cfg, tmp_path):
        """User confirms destroy AND accepts export → run_export_metrics called."""
        deploy_dir = tmp_path / "deploy"
        _setup_destroy_dir(deploy_dir)

        # input(): "yes" (confirm destroy), "y" (export)
        with ExitStack() as stack:
            _patch_destroy_deps(deploy_dir, stack)
            mock_export = stack.enter_context(
                patch("lablink_cli.commands.deploy.run_export_metrics")
            )
            stack.enter_context(
                patch("builtins.input", side_effect=["yes", "y"])
            )

            run_destroy(mock_cfg)

            mock_export.assert_called_once()
            # Output path should be deployment-scoped + UTC-timestamped so
            # repeat destroys in the same cwd don't overwrite prior exports.
            kwargs = mock_export.call_args.kwargs
            assert "output" in kwargs
            assert kwargs["output"].startswith(f"metrics-{mock_cfg.deployment_name}-")
            assert kwargs["output"].endswith(".csv")

    def test_default_empty_input_runs_export(self, mock_cfg, tmp_path):
        """Default on Enter (empty input) is to export (destruction is irreversible)."""
        deploy_dir = tmp_path / "deploy"
        _setup_destroy_dir(deploy_dir)

        with ExitStack() as stack:
            _patch_destroy_deps(deploy_dir, stack)
            mock_export = stack.enter_context(
                patch("lablink_cli.commands.deploy.run_export_metrics")
            )
            stack.enter_context(
                patch("builtins.input", side_effect=["yes", ""])
            )

            run_destroy(mock_cfg)

            mock_export.assert_called_once()
            kwargs = mock_export.call_args.kwargs
            assert kwargs["output"].startswith(f"metrics-{mock_cfg.deployment_name}-")

    def test_skips_export_when_n(self, mock_cfg, tmp_path):
        """User says 'n' to export prompt → skip export, still destroy."""
        deploy_dir = tmp_path / "deploy"
        _setup_destroy_dir(deploy_dir)

        with ExitStack() as stack:
            mocks = _patch_destroy_deps(deploy_dir, stack)
            mock_export = stack.enter_context(
                patch("lablink_cli.commands.deploy.run_export_metrics")
            )
            stack.enter_context(
                patch("builtins.input", side_effect=["yes", "n"])
            )

            run_destroy(mock_cfg)

            mock_export.assert_not_called()
            mocks["destroy_client_vms"].assert_called_once()

    def test_destroy_proceeds_if_export_fails(self, mock_cfg, tmp_path):
        """Export raising Exception should NOT block destruction."""
        deploy_dir = tmp_path / "deploy"
        _setup_destroy_dir(deploy_dir)

        with ExitStack() as stack:
            mocks = _patch_destroy_deps(deploy_dir, stack)
            stack.enter_context(
                patch(
                    "lablink_cli.commands.deploy.run_export_metrics",
                    side_effect=RuntimeError("network down"),
                )
            )
            stack.enter_context(
                patch("builtins.input", side_effect=["yes", "y"])
            )

            run_destroy(mock_cfg)

            mocks["terraform_destroy"].assert_called_once()

    def test_destroy_proceeds_when_export_raises_systemexit(
        self, mock_cfg, tmp_path
    ):
        """Export raising SystemExit (the real failure shape from
        _export_client_metrics on HTTP/URL/JSON errors) must not abort destroy.

        Regression guard: SystemExit inherits from BaseException, not
        Exception, so a plain `except Exception` would miss it and let the
        SystemExit propagate out of run_destroy — killing the destroy before
        _terraform_destroy runs.
        """
        deploy_dir = tmp_path / "deploy"
        _setup_destroy_dir(deploy_dir)

        with ExitStack() as stack:
            mocks = _patch_destroy_deps(deploy_dir, stack)
            stack.enter_context(
                patch(
                    "lablink_cli.commands.deploy.run_export_metrics",
                    side_effect=SystemExit(1),
                )
            )
            stack.enter_context(
                patch("builtins.input", side_effect=["yes", "y"])
            )

            run_destroy(mock_cfg)

            mocks["terraform_destroy"].assert_called_once()

    def test_no_export_prompt_when_user_cancels_destroy(
        self, mock_cfg, tmp_path
    ):
        """'no' to destroy → no export prompt (preserves existing cancel flow)."""
        deploy_dir = tmp_path / "deploy"
        _setup_destroy_dir(deploy_dir)

        with ExitStack() as stack:
            _patch_destroy_deps(deploy_dir, stack)
            mock_export = stack.enter_context(
                patch("lablink_cli.commands.deploy.run_export_metrics")
            )
            # Only one input call expected (the destroy confirmation).
            # If a second input() were attempted, side_effect would raise StopIteration.
            stack.enter_context(
                patch("builtins.input", side_effect=["no"])
            )

            with pytest.raises(SystemExit):
                run_destroy(mock_cfg)

            mock_export.assert_not_called()


# ------------------------------------------------------------------
# run_deploy / run_destroy — -y / --yes auto-accept flag
# ------------------------------------------------------------------
class TestRunDeployYesFlag:
    def test_yes_skips_apply_confirm(self, mock_cfg, tmp_path, monkeypatch):
        """yes=True → no input() for apply-confirm; terraform apply still runs."""
        cache_dir = tmp_path / "cache"
        monkeypatch.setattr(
            deployment_metrics, "DEPLOYMENTS_DIR", cache_dir
        )

        deploy_dir = tmp_path / "deploy"
        (deploy_dir / "config").mkdir(parents=True)
        (deploy_dir / "config" / "config.yaml").write_text(
            "app: {}\ndb: {}\n"
        )

        with ExitStack() as stack:
            # Enter helper mocks; then override builtins.input with a strict
            # mock that fails the test if input() is called at all.
            for cm in _patch_deploy_deps(deploy_dir):
                stack.enter_context(cm)
            stack.enter_context(
                patch(
                    "builtins.input",
                    side_effect=AssertionError(
                        "input() must not be called when yes=True"
                    ),
                )
            )
            mock_tf = stack.enter_context(
                patch("lablink_cli.commands.deploy._run_terraform")
            )

            run_deploy(mock_cfg, yes=True)

        apply_calls = [
            c
            for c in mock_tf.call_args_list
            if c.args and c.args[0] == ["apply", "-auto-approve", "tfplan"]
        ]
        assert len(apply_calls) == 1, (
            f"expected one `terraform apply` call, got {mock_tf.call_args_list}"
        )


class TestRunDestroyYesFlag:
    def test_yes_skips_all_prompts_and_exports_by_default(
        self, mock_cfg, tmp_path
    ):
        """yes=True → no input() for destroy-confirm or export prompt; export runs."""
        deploy_dir = tmp_path / "deploy"
        _setup_destroy_dir(deploy_dir)

        with ExitStack() as stack:
            mocks = _patch_destroy_deps(deploy_dir, stack)
            mock_export = stack.enter_context(
                patch("lablink_cli.commands.deploy.run_export_metrics")
            )
            stack.enter_context(
                patch(
                    "builtins.input",
                    side_effect=AssertionError(
                        "input() must not be called when yes=True"
                    ),
                )
            )

            run_destroy(mock_cfg, yes=True)

            mock_export.assert_called_once()
            mocks["terraform_destroy"].assert_called_once()
