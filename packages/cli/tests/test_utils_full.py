"""Additional tests for lablink_cli.commands.utils uncovered paths."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import yaml

from lablink_cli.commands.utils import (
    _resolve_from_config,
    get_allocator_url,
    get_deploy_dir,
    print_admin_credentials_hint,
    resolve_admin_credentials,
    resolve_from_saved_config,
)


# ------------------------------------------------------------------
# get_deploy_dir
# ------------------------------------------------------------------
class TestGetDeployDir:
    def test_path_structure(self, mock_cfg):
        result = get_deploy_dir(mock_cfg)
        assert "mylab" in str(result)
        assert "dev" in str(result)
        assert ".lablink/deploy" in str(result)


# ------------------------------------------------------------------
# get_allocator_url
# ------------------------------------------------------------------
class TestGetAllocatorUrl:
    @patch("lablink_cli.commands.utils.get_tofu_outputs")
    def test_https_domain(self, mock_outputs, mock_cfg):
        mock_cfg.dns.enabled = True
        mock_cfg.dns.domain = "test.example.com"
        mock_cfg.ssl.provider = "letsencrypt"
        mock_outputs.return_value = {"ec2_public_ip": "1.2.3.4"}

        with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
            mock_dir.return_value = MagicMock(exists=MagicMock(return_value=True))
            result = get_allocator_url(mock_cfg)

        assert result == "https://test.example.com"

    @patch("lablink_cli.commands.utils.get_tofu_outputs")
    def test_http_domain(self, mock_outputs, mock_cfg):
        mock_cfg.dns.enabled = True
        mock_cfg.dns.domain = "test.example.com"
        mock_cfg.ssl.provider = "none"
        mock_outputs.return_value = {"ec2_public_ip": "1.2.3.4"}

        with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
            mock_dir.return_value = MagicMock(exists=MagicMock(return_value=True))
            result = get_allocator_url(mock_cfg)

        assert result == "http://test.example.com"

    @patch("lablink_cli.commands.utils.get_tofu_outputs")
    def test_ip_fallback(self, mock_outputs, mock_cfg):
        mock_cfg.dns.enabled = False
        mock_cfg.ssl.provider = "none"
        mock_outputs.return_value = {"ec2_public_ip": "1.2.3.4"}

        with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
            mock_dir.return_value = MagicMock(exists=MagicMock(return_value=True))
            result = get_allocator_url(mock_cfg)

        assert result == "http://1.2.3.4"

    @patch("lablink_cli.commands.utils.get_tofu_outputs")
    def test_no_url(self, mock_outputs, mock_cfg):
        mock_cfg.dns.enabled = False
        mock_cfg.ssl.provider = "none"
        mock_outputs.return_value = {}

        with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
            mock_dir.return_value = MagicMock(exists=MagicMock(return_value=True))
            result = get_allocator_url(mock_cfg)

        assert result == ""

    def test_manual_provider_uses_localhost(self, mock_cfg):
        """Manual provider short-circuits: no OpenTofu state, no DNS."""
        mock_cfg.provider = "manual"

        with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
            result = get_allocator_url(mock_cfg)

        assert result == "http://localhost:80"
        mock_dir.assert_not_called()

    def test_manual_provider_external_runtime_uses_public_url(self, mock_cfg):
        """An external-runtime deployment (`lablink deploy --render-only`)
        has no localhost port to fall back to — the allocator only exists
        at its recorded public URL. Without this, `stats`/`export-metrics`
        hit http://localhost:80 for a deployment with nothing listening
        there."""
        mock_cfg.provider = "manual"

        with patch(
            "lablink_cli.manual.deployment_runtime",
            return_value="external",
        ), patch(
            "lablink_cli.manual.public_url",
            return_value="https://lab.example.org",
        ):
            result = get_allocator_url(mock_cfg)

        assert result == "https://lab.example.org"

    def test_manual_provider_external_runtime_no_url_returns_empty(self, mock_cfg):
        """A render-only bundle with no recorded public URL yields an empty
        string, not a bogus localhost guess — callers already print 'Could
        not determine allocator URL' on empty."""
        mock_cfg.provider = "manual"

        with patch(
            "lablink_cli.manual.deployment_runtime",
            return_value="external",
        ), patch(
            "lablink_cli.manual.public_url",
            return_value=None,
        ):
            result = get_allocator_url(mock_cfg)

        assert result == ""

    def test_deploy_dir_missing(self, mock_cfg):
        mock_cfg.dns.enabled = False
        mock_cfg.ssl.provider = "none"

        with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
            mock_dir.return_value = MagicMock(exists=MagicMock(return_value=False))
            result = get_allocator_url(mock_cfg)

        assert result == ""


# ------------------------------------------------------------------
# resolve_admin_credentials
# ------------------------------------------------------------------
class TestResolveAdminCredentials:
    def test_from_config(self, mock_cfg):
        mock_cfg.app.admin_user = "myuser"
        mock_cfg.app.admin_password = "mypassword"

        user, pw = resolve_admin_credentials(mock_cfg)
        assert user == "myuser"
        assert pw == "mypassword"

    def test_from_deploy_config(self, mock_cfg, tmp_path):
        mock_cfg.app.admin_user = "MISSING"
        mock_cfg.app.admin_password = "MISSING"

        deploy_config = tmp_path / "config" / "config.yaml"
        deploy_config.parent.mkdir(parents=True)
        data = {"app": {"admin_user": "deploy-user", "admin_password": "deploy-pw"}}
        deploy_config.write_text(yaml.dump(data))

        with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
            mock_dir.return_value = tmp_path
            user, pw = resolve_admin_credentials(mock_cfg)

        assert user == "deploy-user"
        assert pw == "deploy-pw"

    def test_empty_falls_through(self, mock_cfg, tmp_path):
        mock_cfg.app.admin_user = ""
        mock_cfg.app.admin_password = ""

        deploy_config = tmp_path / "config" / "config.yaml"
        deploy_config.parent.mkdir(parents=True)
        data = {"app": {"admin_user": "from-deploy", "admin_password": "from-deploy"}}
        deploy_config.write_text(yaml.dump(data))

        with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
            mock_dir.return_value = tmp_path
            user, pw = resolve_admin_credentials(mock_cfg)

        assert user == "from-deploy"
        assert pw == "from-deploy"

    def test_manual_reads_compose_config(self, mock_cfg, tmp_path):
        """Manual provider: creds come from the rendered compose workdir."""
        mock_cfg.provider = "manual"
        mock_cfg.app.admin_user = "MISSING"
        mock_cfg.app.admin_password = "MISSING"

        compose_config = tmp_path / "mylab" / "config.yaml"
        compose_config.parent.mkdir(parents=True)
        compose_config.write_text(
            yaml.dump(
                {"app": {"admin_user": "byo-user", "admin_password": "byo-pw"}}
            )
        )

        with patch(
            "lablink_cli.manual.DEFAULT_COMPOSE_DIR", tmp_path
        ):
            with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
                user, pw = resolve_admin_credentials(mock_cfg)

        assert (user, pw) == ("byo-user", "byo-pw")
        # The AWS deploy dir must not even be consulted — it never exists
        # for a manual deployment, which is what used to force the prompt.
        mock_dir.assert_not_called()

    @patch("builtins.input", return_value="prompted-user")
    @patch("getpass.getpass", return_value="prompted-pw")
    def test_interactive_prompt(self, mock_getpass, mock_input, mock_cfg, tmp_path):
        mock_cfg.app.admin_user = "MISSING"
        mock_cfg.app.admin_password = "MISSING"

        with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
            mock_dir.return_value = tmp_path / "nonexistent"
            user, pw = resolve_admin_credentials(mock_cfg)

        assert user == "prompted-user"
        assert pw == "prompted-pw"

    @patch("builtins.input", return_value="")
    @patch("getpass.getpass", return_value="")
    def test_empty_password_exits(self, mock_getpass, mock_input, mock_cfg, tmp_path):
        mock_cfg.app.admin_user = "MISSING"
        mock_cfg.app.admin_password = "MISSING"

        with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
            mock_dir.return_value = tmp_path / "nonexistent"
            with pytest.raises(SystemExit):
                resolve_admin_credentials(mock_cfg)


# ------------------------------------------------------------------
# _resolve_from_config
# ------------------------------------------------------------------
class TestResolveFromConfig:
    def test_returns_credentials(self, mock_cfg):
        mock_cfg.app.admin_user = "myuser"
        mock_cfg.app.admin_password = "mypass"
        result = _resolve_from_config(mock_cfg)
        assert result == ("myuser", "mypass")

    def test_returns_none_when_missing(self, mock_cfg):
        mock_cfg.app.admin_user = "MISSING"
        mock_cfg.app.admin_password = "MISSING"
        result = _resolve_from_config(mock_cfg)
        assert result is None

    def test_returns_none_when_empty(self, mock_cfg):
        mock_cfg.app.admin_user = ""
        mock_cfg.app.admin_password = ""
        result = _resolve_from_config(mock_cfg)
        assert result is None

    def test_returns_none_when_partial(self, mock_cfg):
        mock_cfg.app.admin_user = "myuser"
        mock_cfg.app.admin_password = "MISSING"
        result = _resolve_from_config(mock_cfg)
        assert result is None


class TestPrintAdminCredentialsHint:
    def test_aws_names_deploy_dir(self, capsys, mock_cfg):
        print_admin_credentials_hint(mock_cfg)
        out = capsys.readouterr().out
        assert ".lablink/deploy" in out
        assert "compose" not in out

    def test_manual_names_compose_dir(self, capsys, mock_cfg):
        mock_cfg.provider = "manual"
        print_admin_credentials_hint(mock_cfg)
        out = capsys.readouterr().out
        assert ".lablink/compose" in out
        assert "deploy/" not in out

    def test_no_cfg_defaults_to_aws(self, capsys):
        print_admin_credentials_hint()
        assert ".lablink/deploy" in capsys.readouterr().out


class TestResolveFromSavedConfig:
    """The reader both providers share; only the path differs."""

    def test_returns_credentials(self, tmp_path):
        path = tmp_path / "config.yaml"
        data = {"app": {"admin_user": "deploy-user", "admin_password": "deploy-pw"}}
        path.write_text(yaml.dump(data))
        assert resolve_from_saved_config(path) == ("deploy-user", "deploy-pw")

    def test_returns_none_when_file_missing(self, tmp_path):
        assert resolve_from_saved_config(tmp_path / "nonexistent.yaml") is None

    def test_returns_none_when_missing_keys(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump({"app": {}}))
        assert resolve_from_saved_config(path) is None
