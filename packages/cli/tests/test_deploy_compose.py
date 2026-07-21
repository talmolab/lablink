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
    connectivity="lan_direct",
    overlay_tailnet="",
):
    cfg = Config()
    cfg.provider = "manual"
    cfg.deployment_name = deployment_name
    cfg.app.admin_user = admin_user
    cfg.app.admin_password = admin_password
    cfg.ssl.provider = ssl_provider
    cfg.allocator.image_tag = image_tag
    cfg.manual.connectivity = connectivity
    cfg.manual.overlay_tailnet = overlay_tailnet
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
        # No HTTPS_PORT — the container has no TLS terminator, so the
        # compose template no longer exposes 443.
        assert "HTTPS_PORT" not in env_content

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
        # Platform pinned to amd64 so Apple Silicon hosts emulate the
        # amd64-only image instead of failing on a missing arm64 manifest.
        assert "platform: linux/amd64" in compose_yaml
        # pull_policy: always — mutable tags like linux-amd64-latest are
        # republished by CI without changing the tag, so the local cache
        # would otherwise mask updates. Regression guard for the
        # "I pushed a new image but lablink deploy still runs the old one"
        # bug.
        assert "pull_policy: always" in compose_yaml
        # Host port → container 5000. The container's nginx (the only
        # listener) binds 5000 — mapping to :80 left the host port
        # pointing at nothing and produced ERR_CONNECTION_RESET.
        assert "${HTTP_PORT}:5000" in compose_yaml
        # No mapping to :443 — the container has no TLS terminator, so
        # any HTTPS port mapping would be a dead-end. Regression guard.
        assert ":443" not in compose_yaml

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


class TestRenderComposeDirMeshOverlay:
    def test_lan_direct_uses_plain_template_no_sidecar(self, tmp_path):
        """Default connectivity must not render the sidecar — byte-identical
        compose stack to every existing lan_direct deployment."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg()
        target = tmp_path / "compose"
        render_compose_dir(cfg, target)

        compose_yaml = (target / "docker-compose.yml").read_text()
        assert "tailscale" not in compose_yaml
        env_content = (target / ".env").read_text()
        assert "TS_AUTHKEY" not in env_content

    def test_mesh_overlay_renders_sidecar_and_authkey(self, tmp_path):
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(
            connectivity="mesh_overlay", overlay_tailnet="example.ts.net"
        )
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-abc")

        compose_yaml = (target / "docker-compose.yml").read_text()
        assert "tailscale:" in compose_yaml
        assert 'network_mode: "service:allocator"' in compose_yaml
        env_content = (target / ".env").read_text()
        assert "TS_AUTHKEY=tskey-abc" in env_content
        assert "TAILSCALE_HOSTNAME=lablink-allocator-testlab" in env_content

    def test_sidecar_always_pulls(self, tmp_path):
        """Regression guard: without pull_policy: always, a locally cached
        image from a prior pull silently wins even when it's the wrong
        architecture for the current host. Confirmed live: a stale amd64-
        cached tailscale/tailscale:latest ran QEMU-emulated on an Apple
        Silicon host and corrupted the Noise-protocol handshake
        (chacha20poly1305: message authentication failed), even though the
        image is genuinely published multi-arch and a native arm64 pull
        joins the tailnet immediately."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(
            connectivity="mesh_overlay", overlay_tailnet="example.ts.net"
        )
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-abc")

        compose_yaml = (target / "docker-compose.yml").read_text()
        # Split on the service key itself (2-space indent), not the bare
        # substring "tailscale:" — that also matches inside the image name
        # "tailscale/tailscale:latest" a few characters later and would
        # truncate the block before pull_policy.
        tailscale_service = compose_yaml.split("\n  tailscale:\n")[1]
        assert "pull_policy: always" in tailscale_service

    def test_redeploy_without_authkey_carries_previous_value_forward(
        self, tmp_path
    ):
        """A redeploy that omits --tailscale-authkey must not blank out an
        already-joined sidecar's key."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(
            connectivity="mesh_overlay", overlay_tailnet="example.ts.net"
        )
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-first")
        render_compose_dir(cfg, target, tailscale_authkey=None)

        env_content = (target / ".env").read_text()
        assert "TS_AUTHKEY=tskey-first" in env_content

    def test_redeploy_with_new_authkey_overrides_previous_value(self, tmp_path):
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(
            connectivity="mesh_overlay", overlay_tailnet="example.ts.net"
        )
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-first")
        render_compose_dir(cfg, target, tailscale_authkey="tskey-second")

        env_content = (target / ".env").read_text()
        assert "TS_AUTHKEY=tskey-second" in env_content
        assert "tskey-first" not in env_content


class TestDeployComposeMeshOverlayPreflight:
    def test_first_deploy_without_authkey_rejected(self, tmp_path):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(
            connectivity="mesh_overlay", overlay_tailnet="example.ts.net"
        )
        with pytest.raises(SystemExit):
            run_deploy_compose(cfg, yes=True, workdir_root=tmp_path)

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    def test_first_deploy_with_authkey_proceeds(
        self, mock_up, mock_poll, mock_summary, tmp_path
    ):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(
            connectivity="mesh_overlay", overlay_tailnet="example.ts.net"
        )
        run_deploy_compose(
            cfg,
            yes=True,
            workdir_root=tmp_path,
            tailscale_authkey="tskey-abc",
        )
        mock_up.assert_called_once()

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    def test_redeploy_without_authkey_proceeds(
        self, mock_up, mock_poll, mock_summary, tmp_path
    ):
        """Second deploy call must not require --tailscale-authkey again —
        the .env from the first deploy already carries a value forward."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(
            connectivity="mesh_overlay", overlay_tailnet="example.ts.net"
        )
        run_deploy_compose(
            cfg,
            yes=True,
            workdir_root=tmp_path,
            tailscale_authkey="tskey-abc",
        )
        run_deploy_compose(cfg, yes=True, workdir_root=tmp_path)
        assert mock_up.call_count == 2


class TestStartupScriptStaging:
    """`render_compose_dir` is responsible for putting custom-startup.sh
    into the compose workdir so the docker-compose bind mount (added in
    the template) resolves and the allocator container can read the
    script at /config/custom-startup.sh. The file MUST exist on every
    deploy — disabled or not — because docker-compose refuses a missing
    bind-mount source. The allocator gates content delivery on a
    separate non-empty check, not on file existence.
    """

    @pytest.fixture(autouse=True)
    def isolate_home(self, tmp_path, monkeypatch):
        """Redirect ``Path.home()`` away from the developer's real
        ``~/.lablink/custom-startup.sh`` for every test in this class —
        otherwise tests that exercise non-override branches accidentally
        pick up the developer's real override file and assert against
        its content. The dedicated override test plants its own file
        inside ``fake_home`` to exercise that branch deliberately.
        """
        from lablink_cli.commands import deploy_compose

        fake_home = tmp_path / "fake-home"
        fake_home.mkdir()
        monkeypatch.setattr(
            deploy_compose.Path, "home", lambda: fake_home
        )

    def test_creates_empty_file_when_disabled(self, tmp_path):
        """Default config (startup_script.enabled=false) → file is
        present but empty so the compose bind mount resolves; the
        allocator reads it and ships ``startup_script_b64=""`` to BYO
        clients."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg()
        # Sanity: default-disabled — guard against a schema flip
        # making this test silently exercise the wrong branch.
        assert cfg.startup_script.enabled is False

        target = tmp_path / "compose"
        render_compose_dir(cfg, target)

        script = target / "custom-startup.sh"
        assert script.exists(), (
            "custom-startup.sh must always be materialized so the "
            "docker-compose bind mount resolves"
        )
        assert script.read_bytes() == b""

    def test_copies_script_from_config_path(self, tmp_path):
        """enabled=true + path on the operator's filesystem → contents
        copied verbatim into the compose dir."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        # Source script lives on the operator's machine; the path in
        # the config points to it directly.
        src = tmp_path / "operator-script.sh"
        body = "#!/bin/bash\necho operator script\n"
        src.write_text(body)

        cfg = _manual_cfg()
        cfg.startup_script.enabled = True
        cfg.startup_script.path = str(src)

        target = tmp_path / "compose"
        render_compose_dir(cfg, target)

        assert (target / "custom-startup.sh").read_text() == body

    def test_user_override_at_home_wins(self, tmp_path):
        """If ``~/.lablink/custom-startup.sh`` exists, it overrides
        ``cfg.startup_script.path`` (mirrors deploy.py:101-103 for the
        AWS path so operators have one mental model regardless of
        provider). The autouse ``isolate_home`` fixture has already
        redirected ``Path.home()`` to a fresh tmp dir; this test plants
        the override there.
        """
        from lablink_cli.commands import deploy_compose

        fake_home = deploy_compose.Path.home()
        (fake_home / ".lablink").mkdir(parents=True)
        override_body = "#!/bin/bash\necho FROM OVERRIDE\n"
        (fake_home / ".lablink" / "custom-startup.sh").write_text(override_body)

        # cfg.startup_script.path points at a real but DIFFERENT script;
        # the override must still win.
        cfg_src = tmp_path / "from-config.sh"
        cfg_src.write_text("#!/bin/bash\necho FROM CONFIG\n")

        cfg = _manual_cfg()
        cfg.startup_script.enabled = True
        cfg.startup_script.path = str(cfg_src)

        target = tmp_path / "compose"
        deploy_compose.render_compose_dir(cfg, target)

        assert (target / "custom-startup.sh").read_text() == override_body

    def test_falls_back_to_empty_when_configured_path_missing(self, tmp_path):
        """enabled=true but the path doesn't exist on disk → warn and
        materialize an empty file so the deploy doesn't crash. Operator
        sees the yellow warning; the allocator's register handler will
        also log + return empty b64."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg()
        cfg.startup_script.enabled = True
        cfg.startup_script.path = str(tmp_path / "does-not-exist.sh")

        target = tmp_path / "compose"
        render_compose_dir(cfg, target)

        script = target / "custom-startup.sh"
        assert script.exists()
        assert script.read_bytes() == b""

    def test_compose_template_mounts_startup_script(self, tmp_path):
        """The rendered compose YAML must declare the bind mount —
        otherwise the staged file at ./custom-startup.sh would not
        reach the allocator container at /config/custom-startup.sh and
        the registration handler would silently always ship empty b64."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg()
        target = tmp_path / "compose"
        render_compose_dir(cfg, target)

        compose_yaml = (target / "docker-compose.yml").read_text()
        assert "./custom-startup.sh:/config/custom-startup.sh" in compose_yaml


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

    def test_rejects_self_signed(self, tmp_path):
        """self_signed is not (yet) supported — the allocator image has
        no TLS terminator, so accepting it would let an operator deploy
        a stack whose HTTPS port maps to nothing."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(ssl_provider="self_signed")
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

    def test_destroy_compose_prints_unregister_reminder_on_success(
        self, tmp_path, capsys, monkeypatch
    ):
        """After a successful manual destroy, remind the operator about BYO clients."""
        from lablink_cli.commands import deploy_compose

        workdir_root = tmp_path
        target = workdir_root / "testlab"
        target.mkdir(parents=True)

        cfg = _manual_cfg()

        fake_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr(deploy_compose.subprocess, "run", fake_run)

        deploy_compose.run_destroy_compose(
            cfg, yes=True, purge=False, workdir_root=workdir_root,
        )

        out = capsys.readouterr().out
        assert "lablink client unregister" in out

    def test_destroy_compose_skips_reminder_when_already_destroyed(
        self, tmp_path, capsys, monkeypatch
    ):
        """Early-return path (no compose dir) → no reminder."""
        from lablink_cli.commands import deploy_compose

        workdir_root = tmp_path  # 'testlab' subdir intentionally not created

        cfg = _manual_cfg()

        deploy_compose.run_destroy_compose(
            cfg, yes=True, purge=False, workdir_root=workdir_root,
        )

        out = capsys.readouterr().out
        assert "lablink client unregister" not in out

    def test_destroy_compose_skips_reminder_on_failure(
        self, tmp_path, capsys, monkeypatch
    ):
        """`docker compose down` failure → SystemExit, no reminder printed."""
        from lablink_cli.commands import deploy_compose

        workdir_root = tmp_path
        target = workdir_root / "testlab"
        target.mkdir(parents=True)

        cfg = _manual_cfg()

        fake_run = MagicMock(return_value=MagicMock(returncode=1))
        monkeypatch.setattr(deploy_compose.subprocess, "run", fake_run)

        with pytest.raises(SystemExit):
            deploy_compose.run_destroy_compose(
                cfg, yes=True, purge=False, workdir_root=workdir_root,
            )

        out = capsys.readouterr().out
        assert "lablink client unregister" not in out


class TestPrintSummary:
    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_next_step_uses_lan_url_when_detected(
        self, mock_extract, mock_lan, capsys
    ):
        """The 'Next step' hint must use the operator's LAN IP, not
        localhost — BYO clients on other boxes can't route to localhost.
        Regression guard for the original copy-paste-with-localhost
        footgun."""
        from lablink_cli.commands.deploy_compose import _print_summary

        token = "abc123def456ghi789jklmnop"
        mock_extract.return_value = token
        mock_lan.return_value = "192.168.1.42"

        _print_summary(_manual_cfg())

        out = capsys.readouterr().out
        # The LAN URL must drive the copy-paste command.
        assert (
            f"lablink client register --allocator-url http://192.168.1.42 "
            f"--register-token {token}"
        ) in out
        # And the summary should surface both URLs so the operator can
        # also browse the dashboard locally.
        assert "Allocator URL (local): http://localhost" in out
        assert "Allocator URL (LAN):   http://192.168.1.42" in out

    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_next_step_falls_back_to_localhost_when_no_lan(
        self, mock_extract, mock_lan, capsys
    ):
        """When LAN detection fails (only loopback, no default route,
        …) the command falls back to localhost — and a warning tells
        the operator that's only valid for same-host registration."""
        from lablink_cli.commands.deploy_compose import _print_summary

        mock_extract.return_value = "abc123def456ghi789jklmnop"
        mock_lan.return_value = None

        _print_summary(_manual_cfg())

        out = capsys.readouterr().out
        assert "--allocator-url http://localhost" in out
        # The note must explicitly call out the same-machine limitation.
        assert "only" in out.lower() and "same machine" in out.lower()

    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_falls_back_to_placeholder_when_token_unparseable(
        self, mock_extract, mock_lan, capsys
    ):
        """If the allocator's logs don't yield a token (rotated, schema
        change, …), the hint still renders with a placeholder so the
        operator is not left with a malformed command line."""
        from lablink_cli.commands.deploy_compose import _print_summary

        mock_extract.return_value = None
        mock_lan.return_value = "192.168.1.42"

        _print_summary(_manual_cfg())

        out = capsys.readouterr().out
        assert "--register-token <token>" in out
        # The recovery hint must redirect stderr (`2>&1`) before the
        # pipe — Python's logging writes the token line to stderr, and
        # `docker logs … | grep …` only sees stdout. Regression guard
        # for the empty-grep footgun.
        assert "docker logs lablink-allocator 2>&1 | grep" in out


class TestDetectLanIp:
    @patch("lablink_cli.commands.deploy_compose.socket.socket")
    def test_returns_routing_ip(self, mock_socket):
        """Happy path: the kernel binds the socket to the outbound
        interface's address, which getsockname() returns."""
        from lablink_cli.commands.deploy_compose import _detect_lan_ip

        sock = MagicMock()
        sock.getsockname.return_value = ("192.168.1.42", 0)
        mock_socket.return_value = sock

        assert _detect_lan_ip() == "192.168.1.42"

    @patch("lablink_cli.commands.deploy_compose.socket.socket")
    def test_returns_none_on_loopback(self, mock_socket):
        """Loopback address means no usable LAN interface — treat as
        'no detection' rather than handing the operator 127.0.0.1 (which
        is just localhost in different clothing)."""
        from lablink_cli.commands.deploy_compose import _detect_lan_ip

        sock = MagicMock()
        sock.getsockname.return_value = ("127.0.0.1", 0)
        mock_socket.return_value = sock

        assert _detect_lan_ip() is None

    @patch("lablink_cli.commands.deploy_compose.socket.socket")
    def test_returns_none_on_oserror(self, mock_socket):
        """If connect() blows up (no route at all), surface None — the
        deploy summary handles that path with a manual-substitution
        hint."""
        from lablink_cli.commands.deploy_compose import _detect_lan_ip

        sock = MagicMock()
        sock.connect.side_effect = OSError("no route to host")
        mock_socket.return_value = sock

        assert _detect_lan_ip() is None


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
    def test_merges_stderr_into_stdout(self, mock_run):
        """The allocator's REGISTER_TOKEN log line is emitted via Python
        logging, which writes to stderr. `docker logs` preserves the
        container's stdout/stderr split, so the extractor must invoke
        `docker logs` with stderr merged into stdout — otherwise the
        token line is captured into result.stderr and the regex (which
        scans result.stdout) silently misses it. Regression guard."""
        import subprocess as _subprocess

        from lablink_cli.commands.deploy_compose import _extract_register_token

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="INFO root REGISTER_TOKEN=abc123def456ghi789jklmnop\n",
        )
        _extract_register_token()
        kwargs = mock_run.call_args.kwargs
        assert kwargs.get("stderr") is _subprocess.STDOUT, (
            "stderr must be merged into stdout via subprocess.STDOUT "
            "so the logger's stderr output is searched too"
        )

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
