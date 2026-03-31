"""Additional tests for lablink_cli.commands.utils uncovered paths."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import yaml

from lablink_cli.commands.utils import (
    get_allocator_url,
    get_deploy_dir,
    resolve_admin_credentials,
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
    @patch("lablink_cli.commands.utils.get_terraform_outputs")
    def test_https_domain(self, mock_outputs, mock_cfg):
        mock_cfg.dns.enabled = True
        mock_cfg.dns.domain = "test.example.com"
        mock_cfg.ssl.provider = "letsencrypt"
        mock_outputs.return_value = {"ec2_public_ip": "1.2.3.4"}

        with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
            mock_dir.return_value = MagicMock(exists=MagicMock(return_value=True))
            result = get_allocator_url(mock_cfg)

        assert result == "https://test.example.com"

    @patch("lablink_cli.commands.utils.get_terraform_outputs")
    def test_http_domain(self, mock_outputs, mock_cfg):
        mock_cfg.dns.enabled = True
        mock_cfg.dns.domain = "test.example.com"
        mock_cfg.ssl.provider = "none"
        mock_outputs.return_value = {"ec2_public_ip": "1.2.3.4"}

        with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
            mock_dir.return_value = MagicMock(exists=MagicMock(return_value=True))
            result = get_allocator_url(mock_cfg)

        assert result == "http://test.example.com"

    @patch("lablink_cli.commands.utils.get_terraform_outputs")
    def test_ip_fallback(self, mock_outputs, mock_cfg):
        mock_cfg.dns.enabled = False
        mock_cfg.ssl.provider = "none"
        mock_outputs.return_value = {"ec2_public_ip": "1.2.3.4"}

        with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
            mock_dir.return_value = MagicMock(exists=MagicMock(return_value=True))
            result = get_allocator_url(mock_cfg)

        assert result == "http://1.2.3.4"

    @patch("lablink_cli.commands.utils.get_terraform_outputs")
    def test_no_url(self, mock_outputs, mock_cfg):
        mock_cfg.dns.enabled = False
        mock_cfg.ssl.provider = "none"
        mock_outputs.return_value = {}

        with patch("lablink_cli.commands.utils.get_deploy_dir") as mock_dir:
            mock_dir.return_value = MagicMock(exists=MagicMock(return_value=True))
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
