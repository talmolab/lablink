"""Tests for lablink_cli.commands.deploy_compose."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.config.schema import Config


def _manual_cfg(
    deployment_name="testlab",
    admin_user="admin",
    admin_password="pw",
    ssl_provider="none",
    image_tag="linux-amd64-latest",
):
    cfg = Config()
    cfg.provider = "manual"
    cfg.deployment_name = deployment_name
    cfg.app.admin_user = admin_user
    cfg.app.admin_password = admin_password
    cfg.ssl.provider = ssl_provider
    cfg.allocator.image_tag = image_tag
    return cfg


class TestRenderComposeDir:
    def test_writes_compose_env_and_config_yaml(self, tmp_path):
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg()
        target = tmp_path / "compose"
        render_compose_dir(cfg, target)

        assert (target / "docker-compose.yml").exists()
        assert (target / ".env").exists()
        assert (target / "config.yaml").exists()

        env_content = (target / ".env").read_text()
        # .env exposes only what the compose template substitutes — the
        # monolithic allocator reads admin/DB creds from config.yaml, not
        # from env vars.
        assert (
            "ALLOCATOR_IMAGE=ghcr.io/talmolab/lablink-allocator-image:linux-amd64-latest"
            in env_content
        )
        assert "HTTP_PORT=80" in env_content
        assert "HTTPS_PORT=443" in env_content

        # config.yaml carries the admin user/password (resolved before
        # render_compose_dir is invoked from run_deploy_compose).
        config_text = (target / "config.yaml").read_text()
        assert (
            "admin_user: admin" in config_text
            or "admin_user: 'admin'" in config_text
        )
        assert (
            "admin_password: pw" in config_text
            or "admin_password: 'pw'" in config_text
        )

    def test_template_is_single_service(self, tmp_path):
        """Regression: compose template must NOT spin up a separate
        Postgres service — the allocator image bundles its own."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg()
        target = tmp_path / "compose"
        render_compose_dir(cfg, target)
        compose_yaml = (target / "docker-compose.yml").read_text()
        # No standalone postgres service before the named-volumes block.
        assert "postgres:" not in compose_yaml.split("volumes:")[0]
        # The single service is `allocator`.
        assert "allocator:" in compose_yaml
        # Config mount path must match the container's CONFIG_DIR default.
        assert "/config/config.yaml" in compose_yaml
        # Internal Postgres data is persisted via a named volume.
        assert "/var/lib/postgresql" in compose_yaml
        # Container name pinned so other CLI commands can address it.
        assert "container_name: lablink-allocator" in compose_yaml

    def test_env_has_no_credentials(self, tmp_path):
        """.env must not leak admin/DB/postgres credentials."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg()
        target = tmp_path / "compose"
        render_compose_dir(cfg, target)
        env_content = (target / ".env").read_text()
        for forbidden in (
            "ADMIN_USER",
            "ADMIN_PASSWORD",
            "DB_HOST",
            "DB_PASSWORD",
            "POSTGRES_PASSWORD",
            "POSTGRES_USER",
        ):
            assert forbidden not in env_content, (
                f"{forbidden} unexpectedly appeared in .env"
            )

    def test_env_file_mode_is_0600(self, tmp_path):
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg()
        target = tmp_path / "compose"
        render_compose_dir(cfg, target)
        mode = (target / ".env").stat().st_mode & 0o777
        assert mode == 0o600

    def test_uses_image_tag_from_config(self, tmp_path):
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(image_tag="v1.2.3")
        target = tmp_path / "compose"
        render_compose_dir(cfg, target)
        env_content = (target / ".env").read_text()
        assert (
            "ALLOCATOR_IMAGE=ghcr.io/talmolab/lablink-allocator-image:v1.2.3"
            in env_content
        )


def _read_env_var(env_file: Path, key: str) -> str:
    for line in env_file.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    raise AssertionError(f"{key} not in {env_file}")


class TestDeployComposePreflight:
    def test_rejects_letsencrypt(self, tmp_path):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(ssl_provider="letsencrypt")
        with pytest.raises(SystemExit):
            run_deploy_compose(cfg, yes=True, workdir_root=tmp_path)

    def test_rejects_acm(self, tmp_path):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(ssl_provider="acm")
        with pytest.raises(SystemExit):
            run_deploy_compose(cfg, yes=True, workdir_root=tmp_path)

    @patch("lablink_cli.commands.deploy_compose.shutil.which")
    def test_rejects_when_docker_missing(self, mock_which, tmp_path):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg()
        mock_which.return_value = None
        with pytest.raises(SystemExit):
            run_deploy_compose(cfg, yes=True, workdir_root=tmp_path)


class TestDestroyCompose:
    @patch("lablink_cli.commands.deploy_compose.subprocess.run")
    def test_default_compose_down_no_volumes(self, mock_run, tmp_path):
        from lablink_cli.commands.deploy_compose import run_destroy_compose

        cfg = _manual_cfg()
        workdir = tmp_path / "compose" / "testlab"
        workdir.mkdir(parents=True)
        (workdir / "docker-compose.yml").write_text("")
        mock_run.return_value = MagicMock(returncode=0)

        run_destroy_compose(
            cfg, yes=True, purge=False, workdir_root=tmp_path / "compose"
        )

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "down" in cmd
        assert "--volumes" not in cmd
        assert workdir.exists()  # NOT removed without --purge

    @patch("lablink_cli.commands.deploy_compose.subprocess.run")
    def test_purge_removes_volumes_and_workdir(self, mock_run, tmp_path):
        from lablink_cli.commands.deploy_compose import run_destroy_compose

        cfg = _manual_cfg()
        workdir = tmp_path / "compose" / "testlab"
        workdir.mkdir(parents=True)
        (workdir / "docker-compose.yml").write_text("")
        mock_run.return_value = MagicMock(returncode=0)

        run_destroy_compose(
            cfg, yes=True, purge=True, workdir_root=tmp_path / "compose"
        )

        cmd = mock_run.call_args[0][0]
        assert "down" in cmd
        assert "--volumes" in cmd
        assert not workdir.exists()  # removed on purge

    def test_noop_when_workdir_missing(self, tmp_path):
        from lablink_cli.commands.deploy_compose import run_destroy_compose

        cfg = _manual_cfg()
        # No directory created — should just print a message and return.
        run_destroy_compose(
            cfg, yes=True, purge=False, workdir_root=tmp_path / "compose"
        )


class TestExtractRegisterToken:
    @patch("lablink_cli.commands.deploy_compose.subprocess.run")
    def test_parses_uppercase_format(self, mock_run):
        from lablink_cli.commands.deploy_compose import _extract_register_token

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="INFO root REGISTER_TOKEN=abc123def456ghi789jklmnop\n",
        )
        assert _extract_register_token() == "abc123def456ghi789jklmnop"

    @patch("lablink_cli.commands.deploy_compose.subprocess.run")
    def test_parses_lowercase_assignment_format(self, mock_run):
        from lablink_cli.commands.deploy_compose import _extract_register_token

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='register_token = "abc123def456ghi789jklmnop"\n',
        )
        assert _extract_register_token() == "abc123def456ghi789jklmnop"

    @patch("lablink_cli.commands.deploy_compose.subprocess.run")
    def test_returns_none_when_docker_fails(self, mock_run):
        from lablink_cli.commands.deploy_compose import _extract_register_token

        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert _extract_register_token() is None

    @patch("lablink_cli.commands.deploy_compose.subprocess.run")
    def test_returns_none_when_no_match(self, mock_run):
        from lablink_cli.commands.deploy_compose import _extract_register_token

        mock_run.return_value = MagicMock(
            returncode=0, stdout="nothing relevant\n"
        )
        assert _extract_register_token() is None
