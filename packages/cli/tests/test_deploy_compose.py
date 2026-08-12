"""Tests for lablink_cli.commands.deploy_compose."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.config.schema import Config
from lablink_cli.docker import Docker, DockerUnavailable, Result


class ComposeDocker(Docker):
    """Records compose invocations; reports no volumes and no containers."""

    def __init__(self, *, volumes=(), compose=Result(0), logs=Result(0)):
        self._volumes = set(volumes)
        self._compose = compose
        self._logs = logs
        self.compose_calls = []
        self.exec_calls = []
        self.removed_volumes = []

    def available(self):
        return True

    def require(self):
        return None

    def volume_exists(self, name):
        return name in self._volumes

    def remove_volume(self, name):
        self.removed_volumes.append(name)
        return Result(0)

    def inspect_format(self, name, template):
        return ""

    def logs(self, name, *, tail=None, merge_stderr=False, timeout=None):
        return self._logs

    def compose(self, workdir, *args, capture=True):
        # `capture` is recorded (not just workdir/args) because it is the
        # exact property that must stay False at both `_compose_up` and
        # `run_destroy_compose`'s "down" call — those are deliberately
        # per-call-site streamed output, not something a future edit
        # should be free to unify or flip without a test noticing.
        self.compose_calls.append((str(workdir) if workdir else None, args, capture))
        return self._compose

    def exec_in(self, container, argv):
        self.exec_calls.append(list(argv))
        return Result(0)


class _ExecQueueDocker(ComposeDocker):
    """ComposeDocker variant that answers `exec_in` from a fixed queue of
    Results, in call order — needed for the funnel helpers, which can
    issue more than one `docker exec` per call (a retry, then a status
    lookup)."""

    def __init__(self, exec_results):
        super().__init__()
        self._exec_results = list(exec_results)
        self.exec_containers = []

    def exec_in(self, container, argv):
        self.exec_containers.append(container)
        self.exec_calls.append(list(argv))
        return self._exec_results.pop(0)


class _LoggingDocker(ComposeDocker):
    """ComposeDocker variant recording every `logs()` call's kwargs — for
    the register-token/log-dump tests that pin merge_stderr=True."""

    def __init__(self, *, logs=Result(0)):
        super().__init__(logs=logs)
        self.log_calls = []

    def logs(self, name, *, tail=None, merge_stderr=False, timeout=None):
        self.log_calls.append(
            {"name": name, "tail": tail, "merge_stderr": merge_stderr}
        )
        return self._logs


class _InspectDocker(ComposeDocker):
    """ComposeDocker variant with a configurable `inspect_format` result,
    and `volume_exists` call tracking — for `_pgdata_volume_name`'s two
    branches (exact mount found vs. directory-basename fallback)."""

    def __init__(self, *, inspect_result="", **kwargs):
        super().__init__(**kwargs)
        self._inspect_result = inspect_result
        self.volume_exists_calls = []
        self.inspect_calls = []

    def inspect_format(self, name, template):
        self.inspect_calls.append((name, template))
        return self._inspect_result

    def volume_exists(self, name):
        self.volume_exists_calls.append(name)
        return super().volume_exists(name)


def test_tailscale_state_volume_detected(tmp_path):
    from lablink_cli.commands.deploy_compose import _tailscale_state_volume_exists

    fake = ComposeDocker(volumes={f"{tmp_path.name}_tailscale_state"})
    assert _tailscale_state_volume_exists(tmp_path, docker=fake) is True


def test_disable_funnel_is_silent_when_sidecar_absent(tmp_path):
    from lablink_cli.commands.deploy_compose import _disable_funnel

    fake = ComposeDocker()
    _disable_funnel(docker=fake)          # must not raise
    assert fake.exec_calls == [
        ["tailscale", "funnel", "--https=443", "off"]
    ]


def _manual_cfg(
    deployment_name="testlab",
    admin_user="admin",
    admin_password="pw",
    ssl_provider="none",
    image_tag="linux-amd64-latest",
    connectivity="lan_direct",
    overlay_tailnet="",
    participant_exposure="none",
    public_hostname="",
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
    cfg.manual.participant_exposure = participant_exposure
    cfg.manual.public_hostname = public_hostname
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
            "admin_user: admin" in config_text or "admin_user: 'admin'" in config_text
        )
        assert (
            "admin_password: pw" in config_text or "admin_password: 'pw'" in config_text
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
        # The sidecar arrives as Compose's auto-loaded override; its
        # absence is what keeps this stack single-service.
        assert not (target / "docker-compose.override.yml").exists()
        env_content = (target / ".env").read_text()
        assert "TS_AUTHKEY" not in env_content

    def test_mesh_overlay_renders_sidecar_and_authkey(self, tmp_path):
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(connectivity="mesh_overlay", overlay_tailnet="example.ts.net")
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-abc")

        # The base stack stays sidecar-free; the sidecar is layered on by
        # docker-compose.override.yml, which Compose auto-loads from the
        # project dir (so no CLI `docker compose` call passes -f).
        assert "tailscale" not in (target / "docker-compose.yml").read_text()
        override = (target / "docker-compose.override.yml").read_text()
        assert "tailscale:" in override
        assert 'network_mode: "service:allocator"' in override
        env_content = (target / ".env").read_text()
        assert "TS_AUTHKEY=tskey-abc" in env_content
        assert "TAILSCALE_HOSTNAME=lablink-allocator-testlab" in env_content

    def test_redeploy_without_sidecar_removes_stale_override(self, tmp_path):
        """Turning mesh_overlay off must delete the override, or Compose
        keeps merging it and the stack silently rejoins the tailnet."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        target = tmp_path / "compose"
        render_compose_dir(
            _manual_cfg(connectivity="mesh_overlay", overlay_tailnet="example.ts.net"),
            target,
            tailscale_authkey="tskey-abc",
        )
        assert (target / "docker-compose.override.yml").exists()

        render_compose_dir(_manual_cfg(), target)
        assert not (target / "docker-compose.override.yml").exists()

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

        cfg = _manual_cfg(connectivity="mesh_overlay", overlay_tailnet="example.ts.net")
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-abc")

        override = (target / "docker-compose.override.yml").read_text()
        # Split on the service key itself (2-space indent), not the bare
        # substring "tailscale:" — that also matches inside the image name
        # "tailscale/tailscale:latest" a few characters later and would
        # truncate the block before pull_policy.
        tailscale_service = override.split("\n  tailscale:\n")[1]
        assert "pull_policy: always" in tailscale_service

    def test_redeploy_without_authkey_carries_previous_value_forward(self, tmp_path):
        """A redeploy that omits --tailscale-authkey must not blank out an
        already-joined sidecar's key."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(connectivity="mesh_overlay", overlay_tailnet="example.ts.net")
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-first")
        render_compose_dir(cfg, target, tailscale_authkey=None)

        env_content = (target / ".env").read_text()
        assert "TS_AUTHKEY=tskey-first" in env_content

    def test_redeploy_with_new_authkey_overrides_previous_value(self, tmp_path):
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(connectivity="mesh_overlay", overlay_tailnet="example.ts.net")
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-first")
        render_compose_dir(cfg, target, tailscale_authkey="tskey-second")

        env_content = (target / ".env").read_text()
        assert "TS_AUTHKEY=tskey-second" in env_content
        assert "tskey-first" not in env_content


class TestRenderComposeDirParticipantExposure:
    def test_lan_direct_no_funnel_no_sidecar(self, tmp_path):
        """Baseline: neither axis active -> no sidecar, matching existing
        lan_direct behavior exactly."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(connectivity="lan_direct", participant_exposure="none")
        target = tmp_path / "compose"
        render_compose_dir(cfg, target)

        compose_yaml = (target / "docker-compose.yml").read_text()
        assert "tailscale" not in compose_yaml
        env_content = (target / ".env").read_text()
        assert "TS_AUTHKEY" not in env_content

    def test_lan_direct_with_funnel_renders_sidecar(self, tmp_path):
        """Unit-level coverage of _needs_tailscale_sidecar's OR logic in
        isolation: render_compose_dir itself doesn't enforce the
        connectivity/exposure business rule (run_deploy_compose's own
        preflight now rejects this exact combination — see
        TestLanDirectFunnelRejectedAtDeploy — since lan_direct + Funnel
        can't actually serve participant sessions), it just renders
        whatever config it's given."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(
            connectivity="lan_direct",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
        )
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-abc")

        override = (target / "docker-compose.override.yml").read_text()
        assert "tailscale:" in override
        assert 'network_mode: "service:allocator"' in override
        env_content = (target / ".env").read_text()
        assert "TS_AUTHKEY=tskey-abc" in env_content
        assert "TAILSCALE_HOSTNAME=lablink-allocator-testlab" in env_content

    def test_mesh_overlay_with_funnel_still_one_sidecar(self, tmp_path):
        """Both axes active at once must not error or duplicate anything —
        same sidecar serves both purposes."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
        )
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-abc")

        override = (target / "docker-compose.override.yml").read_text()
        assert override.count("\n  tailscale:\n") == 1
        env_content = (target / ".env").read_text()
        assert "TS_AUTHKEY=tskey-abc" in env_content


class TestDeployComposeMeshOverlayPreflight:
    @patch("lablink_cli.commands.deploy_compose._tailscale_state_volume_exists")
    def test_first_deploy_without_authkey_rejected(self, mock_state_exists, tmp_path):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        mock_state_exists.return_value = False
        cfg = _manual_cfg(connectivity="mesh_overlay", overlay_tailnet="example.ts.net")
        with pytest.raises(SystemExit):
            run_deploy_compose(cfg, yes=True, workdir_root=tmp_path)

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    def test_first_deploy_with_authkey_proceeds(
        self, mock_up, mock_poll, mock_summary, tmp_path
    ):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(connectivity="mesh_overlay", overlay_tailnet="example.ts.net")
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
    @patch("lablink_cli.commands.deploy_compose._tailscale_state_volume_exists")
    def test_no_authkey_proceeds_when_tailscale_state_volume_already_exists(
        self, mock_state_exists, mock_up, mock_poll, mock_summary, tmp_path
    ):
        """Regression (P2 review finding): default `lablink destroy`
        preserves tailscale_state but removes the whole working
        directory, including .env's TS_AUTHKEY line. A subsequent deploy
        must not demand a fresh authkey purely because there's no .env to
        read one from — the sidecar's identity is already authenticated
        and sitting in that preserved volume."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        mock_state_exists.return_value = True
        cfg = _manual_cfg(connectivity="mesh_overlay", overlay_tailnet="example.ts.net")
        run_deploy_compose(cfg, yes=True, workdir_root=tmp_path)
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

        cfg = _manual_cfg(connectivity="mesh_overlay", overlay_tailnet="example.ts.net")
        run_deploy_compose(
            cfg,
            yes=True,
            workdir_root=tmp_path,
            tailscale_authkey="tskey-abc",
        )
        run_deploy_compose(cfg, yes=True, workdir_root=tmp_path)
        assert mock_up.call_count == 2

    @patch("lablink_cli.commands.deploy_compose._tailscale_state_volume_exists")
    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    def test_switch_from_lan_direct_without_authkey_rejected(
        self, mock_up, mock_poll, mock_summary, mock_state_exists, tmp_path
    ):
        """Regression guard: an existing lan_direct deployment (its .env
        has no TS_AUTHKEY line) that switches manual.connectivity to
        mesh_overlay must still be required to pass --tailscale-authkey.
        ".env exists" alone is not a valid proxy for "an authkey is on
        record" — without this guard the preflight silently skipped the
        check and render_compose_dir wrote TS_AUTHKEY= (empty)."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        mock_state_exists.return_value = False
        lan_cfg = _manual_cfg(connectivity="lan_direct")
        run_deploy_compose(lan_cfg, yes=True, workdir_root=tmp_path)

        mesh_cfg = _manual_cfg(
            connectivity="mesh_overlay", overlay_tailnet="example.ts.net"
        )
        with pytest.raises(SystemExit):
            run_deploy_compose(mesh_cfg, yes=True, workdir_root=tmp_path)
        mock_up.assert_called_once()  # only the first (lan_direct) deploy ran

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    def test_switch_from_lan_direct_with_authkey_proceeds(
        self, mock_up, mock_poll, mock_summary, tmp_path
    ):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        lan_cfg = _manual_cfg(connectivity="lan_direct")
        run_deploy_compose(lan_cfg, yes=True, workdir_root=tmp_path)

        mesh_cfg = _manual_cfg(
            connectivity="mesh_overlay", overlay_tailnet="example.ts.net"
        )
        run_deploy_compose(
            mesh_cfg,
            yes=True,
            workdir_root=tmp_path,
            tailscale_authkey="tskey-abc",
        )
        assert mock_up.call_count == 2


class TestDeployComposeParticipantExposurePreflight:
    @patch("lablink_cli.commands.deploy_compose._tailscale_state_volume_exists")
    def test_lan_direct_with_funnel_requires_authkey(self, mock_state_exists, tmp_path):
        """A lan_direct deployment that enables tailscale_funnel still
        needs the sidecar to join a tailnet — same requirement as
        mesh_overlay, generalized."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        mock_state_exists.return_value = False
        cfg = _manual_cfg(
            connectivity="lan_direct",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
            admin_password="a-strong-enough-password",
        )
        with pytest.raises(SystemExit):
            run_deploy_compose(cfg, yes=True, workdir_root=tmp_path)

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    @patch("lablink_cli.commands.deploy_compose._enable_funnel")
    def test_lan_direct_with_funnel_and_authkey_proceeds(
        self, mock_funnel, mock_up, mock_poll, mock_summary, tmp_path
    ):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        mock_funnel.return_value = (True, "https://lablink-allocator-testlab.example.ts.net")
        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
            admin_password="a-strong-enough-password",
        )
        run_deploy_compose(
            cfg,
            yes=True,
            workdir_root=tmp_path,
            tailscale_authkey="tskey-abc",
        )
        mock_up.assert_called_once()

    def test_weak_admin_password_rejected_when_funnel_enabled(self, tmp_path):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
            admin_password="123456",
        )
        with pytest.raises(SystemExit):
            run_deploy_compose(
                cfg,
                yes=True,
                workdir_root=tmp_path,
                tailscale_authkey="tskey-abc",
            )

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    @patch("lablink_cli.commands.deploy_compose._enable_funnel")
    def test_strong_admin_password_proceeds_when_funnel_enabled(
        self, mock_funnel, mock_up, mock_poll, mock_summary, tmp_path
    ):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        mock_funnel.return_value = (True, "https://lablink-allocator-testlab.example.ts.net")
        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
            admin_password="a-strong-enough-password",
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
    def test_weak_password_irrelevant_when_exposure_is_none(
        self, mock_up, mock_poll, mock_summary, tmp_path
    ):
        """The password gate is scoped to any public exposure, not to one
        tunnel — an unexposed lan_direct deployment must not be blocked."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(connectivity="lan_direct", admin_password="123456")
        run_deploy_compose(cfg, yes=True, workdir_root=tmp_path)
        mock_up.assert_called_once()


class TestLanDirectFunnelRejectedAtDeploy:
    """`get_config_errors` rejects lan_direct + tailscale_funnel too (see
    TestLanDirectFunnelRejected in test_validate_config.py), but
    `lablink deploy` never calls that validator for the manual provider —
    this is the actual enforcement point for a hand-edited config.yaml
    deployed directly, without going through the wizard."""

    def test_rejected_even_with_authkey_and_strong_password(self, tmp_path):
        """Regression: must fire even when every OTHER preflight check
        would otherwise pass (authkey present, password strong) — the
        combination itself is what's rejected, not a missing prerequisite."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(
            connectivity="lan_direct",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
            admin_password="a-strong-enough-password",
        )
        with pytest.raises(SystemExit):
            run_deploy_compose(
                cfg, yes=True, workdir_root=tmp_path, tailscale_authkey="tskey-abc",
            )

    def test_error_message_explains_why(self, tmp_path, capsys):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(
            connectivity="lan_direct",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
            admin_password="a-strong-enough-password",
        )
        with pytest.raises(SystemExit):
            run_deploy_compose(
                cfg, yes=True, workdir_root=tmp_path, tailscale_authkey="tskey-abc",
            )
        out = capsys.readouterr().out
        assert "'tailscale_funnel'" in out
        assert "'lan_direct'" in out
        assert "mesh_overlay" in out


class TestComposeUp:
    def test_uses_remove_orphans(self, tmp_path):
        """Regression: without --remove-orphans, a sidecar that's no
        longer declared in the rendered compose file (needs_sidecar
        became False) is left running untouched forever, still serving
        whatever it was serving before (e.g. Funnel) — see the P1
        finding this guards against."""
        from lablink_cli.commands.deploy_compose import _compose_up

        fake = ComposeDocker()
        _compose_up(tmp_path, docker=fake)
        _, args, capture = fake.compose_calls[0]
        assert args == ("up", "-d", "--remove-orphans")
        # Streamed to the terminal deliberately — the operator watches
        # deploy progress. Must not silently become buffered-and-discarded.
        assert capture is False


class TestFunnelStatusUrl:
    def test_extracts_url_from_status_output(self):
        from lablink_cli.commands.deploy_compose import _funnel_status_url

        fake = _ExecQueueDocker(
            [
                Result(
                    0,
                    stdout=(
                        "# Funnel on:\n"
                        "#     - https://lablink-allocator-sleap-lablink-3."
                        "tail9f6f81.ts.net\n"
                        "\n"
                        "https://lablink-allocator-sleap-lablink-3.tail9f6f81.ts.net "
                        "(Funnel on)\n"
                        "|-- / proxy http://127.0.0.1:5000\n"
                    ),
                )
            ]
        )
        assert (
            _funnel_status_url(docker=fake)
            == "https://lablink-allocator-sleap-lablink-3.tail9f6f81.ts.net"
        )
        assert fake.exec_calls == [["tailscale", "funnel", "status"]]
        assert fake.exec_containers == ["lablink-allocator-tailscale"]

    def test_returns_none_when_funnel_not_on(self):
        from lablink_cli.commands.deploy_compose import _funnel_status_url

        fake = _ExecQueueDocker([Result(0, stdout="Funnel off.\n")])
        assert _funnel_status_url(docker=fake) is None


class TestEnableFunnel:
    def test_already_enabled_or_newly_enabled_returns_success_and_url(self):
        from lablink_cli.commands.deploy_compose import _enable_funnel

        fake = _ExecQueueDocker(
            [
                Result(
                    0, stdout="Available on the internet:\nhttps://x.tailnet.ts.net/\n"
                ),
                Result(
                    0,
                    stdout="https://x.tailnet.ts.net (Funnel on)\n"
                    "|-- / proxy http://127.0.0.1:5000\n",
                ),
            ]
        )

        assert _enable_funnel(docker=fake) == (True, "https://x.tailnet.ts.net")

    def test_acl_not_granted_returns_false_and_prints_url(self, capsys):
        from lablink_cli.commands.deploy_compose import _enable_funnel

        fake = _ExecQueueDocker(
            [
                Result(
                    1,
                    stderr=(
                        "Funnel is not enabled on your tailnet.\nTo enable, visit:"
                        "\n\n         https://login.tailscale.com/f/funnel?node=abc123\n"
                    ),
                )
            ]
        )
        assert _enable_funnel(docker=fake) == (False, None)
        captured = capsys.readouterr()
        assert "login.tailscale.com/f/funnel" in captured.out
        # ACL-not-granted is a hard stop — never follows up with a status
        # lookup, since there's no URL to find.
        assert len(fake.exec_calls) == 1

    def test_uses_correct_container_and_port(self):
        from lablink_cli.commands.deploy_compose import _enable_funnel

        fake = _ExecQueueDocker([Result(0), Result(0)])
        _enable_funnel(docker=fake)
        assert fake.exec_calls[0] == ["tailscale", "funnel", "--bg", "5000"]
        assert fake.exec_containers[0] == "lablink-allocator-tailscale"

    @patch("lablink_cli.commands.deploy_compose.time.sleep")
    def test_unexpected_failure_returns_false(self, mock_sleep):
        from lablink_cli.commands.deploy_compose import (
            _enable_funnel,
            FUNNEL_ENABLE_MAX_ATTEMPTS,
        )

        fake = _ExecQueueDocker(
            [Result(1, stderr="some other docker error")]
            * FUNNEL_ENABLE_MAX_ATTEMPTS
        )
        assert _enable_funnel(docker=fake) == (False, None)
        assert len(fake.exec_calls) == FUNNEL_ENABLE_MAX_ATTEMPTS

    @patch("lablink_cli.commands.deploy_compose.time.sleep")
    def test_retries_on_transient_failure_then_succeeds(self, mock_sleep):
        from lablink_cli.commands.deploy_compose import _enable_funnel

        fake = _ExecQueueDocker(
            [
                Result(1, stderr="not ready yet"),
                Result(1, stderr="not ready yet"),
                Result(0, stdout="Available on the internet:\n"),
                Result(0, stdout="https://x.tailnet.ts.net (Funnel on)\n"),
            ]
        )

        assert _enable_funnel(docker=fake) == (True, "https://x.tailnet.ts.net")
        assert len(fake.exec_calls) == 4
        assert mock_sleep.call_count == 2


class TestDisableFunnel:
    def test_uses_correct_container_and_command(self):
        from lablink_cli.commands.deploy_compose import _disable_funnel

        fake = ComposeDocker()
        _disable_funnel(docker=fake)
        assert fake.exec_calls == [["tailscale", "funnel", "--https=443", "off"]]

    def test_prints_message_on_success(self, capsys):
        from lablink_cli.commands.deploy_compose import _disable_funnel

        _disable_funnel(docker=ComposeDocker())
        assert "disabled" in capsys.readouterr().out.lower()

    def test_silent_and_no_exception_when_sidecar_missing(self, capsys):
        """Best-effort: a fresh deployment that never enabled Funnel has
        no sidecar to disable it on — must not raise or print an error."""
        from lablink_cli.commands.deploy_compose import _disable_funnel

        fake = _ExecQueueDocker(
            [
                Result(
                    1,
                    stderr="Error response from daemon: No such container: "
                    "lablink-allocator-tailscale",
                )
            ]
        )
        _disable_funnel(docker=fake)  # must not raise
        out = capsys.readouterr().out
        assert "disabled" not in out.lower()
        assert "error" not in out.lower()


class TestRunDeployComposeFunnelWiring:
    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    @patch("lablink_cli.commands.deploy_compose._enable_funnel")
    def test_calls_enable_funnel_when_participant_exposure_is_funnel(
        self, mock_funnel, mock_up, mock_poll, mock_summary, tmp_path
    ):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        mock_funnel.return_value = (True, "https://lablink-allocator-testlab.example.ts.net")
        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
            admin_password="a-strong-enough-password",
        )
        run_deploy_compose(
            cfg,
            yes=True,
            workdir_root=tmp_path,
            tailscale_authkey="tskey-abc",
        )
        mock_funnel.assert_called_once()

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    @patch("lablink_cli.commands.deploy_compose._disable_funnel")
    @patch("lablink_cli.commands.deploy_compose._enable_funnel")
    def test_does_not_call_enable_funnel_when_disabled(
        self, mock_funnel, mock_disable, mock_up, mock_poll, mock_summary, tmp_path
    ):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(connectivity="lan_direct", participant_exposure="none")
        run_deploy_compose(cfg, yes=True, workdir_root=tmp_path)
        mock_funnel.assert_not_called()

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    @patch("lablink_cli.commands.deploy_compose._disable_funnel")
    @patch("lablink_cli.commands.deploy_compose._enable_funnel")
    def test_calls_disable_funnel_when_participant_exposure_is_none(
        self, mock_funnel, mock_disable, mock_up, mock_poll, mock_summary, tmp_path
    ):
        """Regression: participant_exposure going back to "none" must
        actively turn Funnel off, not just stop re-enabling it — Funnel
        persists in the sidecar's own state otherwise (P1 finding).
        Called twice (before and after _compose_up — see
        test_disable_funnel_called_before_and_after_compose_up) since a
        stopped-but-not-removed sidecar can't be `docker exec`'d into
        until _compose_up restarts it."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(connectivity="lan_direct", participant_exposure="none")
        run_deploy_compose(cfg, yes=True, workdir_root=tmp_path)
        assert mock_disable.call_count == 2

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    @patch("lablink_cli.commands.deploy_compose._disable_funnel")
    @patch("lablink_cli.commands.deploy_compose._enable_funnel")
    def test_calls_disable_funnel_when_connectivity_stays_mesh_overlay(
        self, mock_funnel, mock_disable, mock_up, mock_poll, mock_summary, tmp_path
    ):
        """Regression: the sidecar staying alive for an unrelated reason
        (connectivity=mesh_overlay) must not skip disabling Funnel — the
        sidecar is still running the whole time, so its persisted Funnel
        config would otherwise keep serving indefinitely."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            participant_exposure="none",
            overlay_tailnet="example.ts.net",
        )
        run_deploy_compose(
            cfg, yes=True, workdir_root=tmp_path, tailscale_authkey="tskey-abc",
        )
        assert mock_disable.call_count == 2

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    @patch("lablink_cli.commands.deploy_compose._disable_funnel")
    @patch("lablink_cli.commands.deploy_compose._enable_funnel")
    def test_does_not_call_disable_funnel_when_funnel_active(
        self, mock_funnel, mock_disable, mock_up, mock_poll, mock_summary, tmp_path
    ):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        mock_funnel.return_value = (True, "https://lablink-allocator-testlab.example.ts.net")
        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
            admin_password="a-strong-enough-password",
        )
        run_deploy_compose(
            cfg, yes=True, workdir_root=tmp_path, tailscale_authkey="tskey-abc",
        )
        mock_disable.assert_not_called()

    def test_disable_funnel_runs_before_and_after_compose_up(self, tmp_path):
        """Ordering regression: _disable_funnel must run both before
        _compose_up (since --remove-orphans could delete the sidecar
        container it needs to `docker exec` into) and after (since a
        stopped-but-not-removed sidecar can't be `docker exec`'d into
        until _compose_up restarts it — the P1 finding this second call
        guards against: Compose reattaching a restarted sidecar to
        tailscale_state with Funnel's last-known "on" config still
        intact, if the first disable call silently no-op'd)."""
        from lablink_cli.commands import deploy_compose
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        call_order = []
        with patch.object(
            deploy_compose,
            "_disable_funnel",
            side_effect=lambda **_: call_order.append("disable"),
        ), patch.object(
            deploy_compose,
            "_compose_up",
            side_effect=lambda target, **_: call_order.append("compose_up"),
        ), patch.object(
            deploy_compose, "_health_poll"
        ), patch.object(
            deploy_compose, "_print_summary"
        ):
            cfg = _manual_cfg(connectivity="lan_direct", participant_exposure="none")
            run_deploy_compose(cfg, yes=True, workdir_root=tmp_path)

        assert call_order == ["disable", "compose_up", "disable"]

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    @patch("lablink_cli.commands.deploy_compose._enable_funnel")
    def test_exits_nonzero_when_funnel_not_enabled_but_summary_still_prints(
        self, mock_funnel, mock_up, mock_poll, mock_summary, tmp_path
    ):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        mock_funnel.return_value = (False, None)
        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
            admin_password="a-strong-enough-password",
        )
        with pytest.raises(SystemExit):
            run_deploy_compose(
                cfg,
                yes=True,
                workdir_root=tmp_path,
                tailscale_authkey="tskey-abc",
            )
        mock_summary.assert_called_once()


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
        monkeypatch.setattr(deploy_compose.Path, "home", lambda: fake_home)

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

    def test_rejects_when_docker_missing(self, tmp_path, capsys):
        """Preflight is `docker.require()`, not `shutil.which` — inject a
        fake whose `require()` raises so this actually exercises the
        "Compose plugin" message instead of relying on a patch the
        production code no longer consults."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        class Unavailable(ComposeDocker):
            def require(self):
                raise DockerUnavailable()

        with pytest.raises(SystemExit):
            run_deploy_compose(
                _manual_cfg(), yes=True, workdir_root=tmp_path, docker=Unavailable()
            )
        assert "Compose plugin" in capsys.readouterr().out


class TestTailscaleStateVolumeExists:
    def test_true_when_volume_found(self, tmp_path):
        from lablink_cli.commands.deploy_compose import _tailscale_state_volume_exists

        target = tmp_path / "testlab"
        target.mkdir()
        fake = ComposeDocker(volumes={"testlab_tailscale_state"})

        assert _tailscale_state_volume_exists(target, docker=fake) is True

    def test_false_when_volume_missing(self, tmp_path):
        from lablink_cli.commands.deploy_compose import _tailscale_state_volume_exists

        target = tmp_path / "testlab"
        target.mkdir()

        assert _tailscale_state_volume_exists(target, docker=ComposeDocker()) is False


class TestPgdataVolumeName:
    def test_returns_resolved_name_from_running_container(self, tmp_path):
        from lablink_cli.commands.deploy_compose import (
            ALLOCATOR_CONTAINER_NAME,
            _pgdata_volume_name,
        )

        fake = _InspectDocker(inspect_result="sleap-lablink_allocator_pgdata")

        assert (
            _pgdata_volume_name(tmp_path, docker=fake)
            == "sleap-lablink_allocator_pgdata"
        )
        # Pins the container name and the Postgres-mount Go-template — a
        # wrong container or a broken template would still return the
        # canned inspect_result above without this assertion.
        assert fake.inspect_calls[0][0] == ALLOCATOR_CONTAINER_NAME
        assert '"/var/lib/postgresql"' in fake.inspect_calls[0][1]
        # found on the first try, no directory-basename fallback needed
        assert fake.volume_exists_calls == []

    def test_falls_back_to_directory_basename_guess_when_container_missing(
        self, tmp_path
    ):
        """Regression (P1 review finding): if the allocator container was
        already removed (e.g. an earlier manual `docker compose down`),
        the volume itself can still exist — falling back to Compose's own
        directory-basename naming convention (verified via `docker volume
        inspect` before trusting it) finds it instead of silently
        reporting nothing to remove."""
        from lablink_cli.commands.deploy_compose import _pgdata_volume_name

        target = tmp_path / "testlab"
        target.mkdir()
        fake = _InspectDocker(volumes={"testlab_allocator_pgdata"})

        assert (
            _pgdata_volume_name(target, docker=fake) == "testlab_allocator_pgdata"
        )
        assert fake.volume_exists_calls == ["testlab_allocator_pgdata"]

    def test_returns_none_when_neither_container_nor_guess_finds_it(self, tmp_path):
        """Genuinely nothing to remove — this deployment never actually
        created a volume (e.g. `docker compose up` never ran)."""
        from lablink_cli.commands.deploy_compose import _pgdata_volume_name

        target = tmp_path / "testlab"
        target.mkdir()
        fake = _InspectDocker()

        assert _pgdata_volume_name(target, docker=fake) is None
        assert fake.volume_exists_calls == ["testlab_allocator_pgdata"]


class TestDestroyCompose:
    def test_default_removes_pgdata_volume_by_name(self, tmp_path):
        """Default behavior wipes the Postgres volume — matches what
        "destroy" means for every other provider, and what most operators
        expect (a subsequent `lablink deploy` starts from an empty
        database). It's removed by resolved name via `docker volume rm`,
        NOT via `docker compose down --volumes` — that would also delete
        the mesh-overlay `tailscale_state` volume, which is the tailnet
        node's identity, not "data"."""
        from lablink_cli.commands.deploy_compose import run_destroy_compose

        cfg = _manual_cfg()
        workdir = tmp_path / "compose" / "testlab"
        workdir.mkdir(parents=True)
        (workdir / "docker-compose.yml").write_text("")

        fake = _InspectDocker(inspect_result="testlab_allocator_pgdata")
        run_destroy_compose(
            cfg, yes=True, workdir_root=tmp_path / "compose", docker=fake
        )

        # capture=False: streamed to the terminal deliberately, so the
        # operator watches teardown progress. Must not silently flip to
        # buffered-and-discarded.
        assert fake.compose_calls == [(str(workdir), ("down",), False)]
        assert fake.removed_volumes == ["testlab_allocator_pgdata"]
        assert not workdir.exists()  # removed by default

    def test_falls_back_to_guess_when_container_not_found(self, tmp_path):
        """Regression (P1 review finding): the allocator container being
        already removed must not silently skip volume removal — the
        directory-basename fallback (verified via `docker volume
        inspect`) still finds and removes it."""
        from lablink_cli.commands.deploy_compose import run_destroy_compose

        cfg = _manual_cfg()
        workdir = tmp_path / "compose" / "testlab"
        workdir.mkdir(parents=True)
        (workdir / "docker-compose.yml").write_text("")

        fake = _InspectDocker(volumes={"testlab_allocator_pgdata"})
        run_destroy_compose(
            cfg, yes=True, workdir_root=tmp_path / "compose", docker=fake
        )

        assert fake.removed_volumes == ["testlab_allocator_pgdata"]
        assert not workdir.exists()

    def test_skips_volume_rm_when_genuinely_nothing_found(self, tmp_path):
        """Container missing AND the directory-basename guess doesn't
        exist either — genuinely nothing to remove (this deployment
        never actually created a volume); destroy still completes."""
        from lablink_cli.commands.deploy_compose import run_destroy_compose

        cfg = _manual_cfg()
        workdir = tmp_path / "compose" / "testlab"
        workdir.mkdir(parents=True)
        (workdir / "docker-compose.yml").write_text("")

        fake = _InspectDocker()
        run_destroy_compose(
            cfg, yes=True, workdir_root=tmp_path / "compose", docker=fake
        )

        assert fake.removed_volumes == []  # no docker volume rm call
        assert not workdir.exists()

    def test_aborts_without_deleting_workdir_when_volume_rm_fails(self, tmp_path):
        """Regression (P1 review finding): a resolved volume that
        `docker volume rm` fails to actually remove must not be reported
        as success — the workdir stays in place (rather than being
        deleted alongside a false "Removed" message) so a retry can pick
        up where this left off, and a later deploy can't silently
        reattach to surviving data."""
        from lablink_cli.commands.deploy_compose import run_destroy_compose

        cfg = _manual_cfg()
        workdir = tmp_path / "compose" / "testlab"
        workdir.mkdir(parents=True)
        (workdir / "docker-compose.yml").write_text("")

        class _FailingRemoveDocker(_InspectDocker):
            def remove_volume(self, name):
                self.removed_volumes.append(name)
                return Result(1, stderr="volume is in use")

        fake = _FailingRemoveDocker(inspect_result="testlab_allocator_pgdata")

        with pytest.raises(SystemExit):
            run_destroy_compose(
                cfg, yes=True, workdir_root=tmp_path / "compose", docker=fake
            )

        assert workdir.exists()  # NOT removed — removal wasn't confirmed

    def test_keep_data_preserves_volumes_and_workdir(self, tmp_path):
        from lablink_cli.commands.deploy_compose import run_destroy_compose

        cfg = _manual_cfg()
        workdir = tmp_path / "compose" / "testlab"
        workdir.mkdir(parents=True)
        (workdir / "docker-compose.yml").write_text("")

        fake = ComposeDocker()
        run_destroy_compose(
            cfg,
            yes=True,
            keep_data=True,
            workdir_root=tmp_path / "compose",
            docker=fake,
        )

        # No volume-name lookup and no volume rm — keep_data skips both.
        assert fake.compose_calls == [(str(workdir), ("down",), False)]
        assert fake.removed_volumes == []
        assert workdir.exists()  # NOT removed with --keep-data

    def test_noop_when_workdir_missing(self, tmp_path):
        from lablink_cli.commands.deploy_compose import run_destroy_compose

        cfg = _manual_cfg()
        # No directory created — should just print a message and return.
        run_destroy_compose(cfg, yes=True, workdir_root=tmp_path / "compose")

    def test_destroy_compose_prints_unregister_reminder_on_success(
        self, tmp_path, capsys
    ):
        """After a successful manual destroy, remind the operator about BYO clients."""
        from lablink_cli.commands import deploy_compose

        workdir_root = tmp_path
        target = workdir_root / "testlab"
        target.mkdir(parents=True)

        cfg = _manual_cfg()

        deploy_compose.run_destroy_compose(
            cfg, yes=True, workdir_root=workdir_root, docker=ComposeDocker(),
        )

        out = capsys.readouterr().out
        assert "lablink client unregister" in out

    def test_destroy_compose_skips_reminder_when_already_destroyed(
        self, tmp_path, capsys
    ):
        """Early-return path (no compose dir) → no reminder."""
        from lablink_cli.commands import deploy_compose

        workdir_root = tmp_path  # 'testlab' subdir intentionally not created

        cfg = _manual_cfg()

        deploy_compose.run_destroy_compose(
            cfg, yes=True, workdir_root=workdir_root,
        )

        out = capsys.readouterr().out
        assert "lablink client unregister" not in out

    def test_destroy_compose_skips_reminder_on_failure(self, tmp_path, capsys):
        """`docker compose down` failure → SystemExit, no reminder printed."""
        from lablink_cli.commands import deploy_compose

        workdir_root = tmp_path
        target = workdir_root / "testlab"
        target.mkdir(parents=True)

        cfg = _manual_cfg()

        with pytest.raises(SystemExit):
            deploy_compose.run_destroy_compose(
                cfg,
                yes=True,
                workdir_root=workdir_root,
                docker=ComposeDocker(compose=Result(1)),
            )

        out = capsys.readouterr().out
        assert "lablink client unregister" not in out


class TestPrintSummary:
    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_next_step_uses_lan_url_when_detected(self, mock_extract, mock_lan, capsys):
        """The 'Next step' hint must use the operator's LAN IP, not
        localhost — BYO clients on other boxes can't route to localhost.
        Regression guard for the original copy-paste-with-localhost
        footgun."""
        from lablink_cli.commands.deploy_compose import _print_summary

        token = "abc123def456ghi789jklmnop"
        mock_extract.return_value = token
        mock_lan.return_value = "192.168.1.42"

        _print_summary(_manual_cfg(), docker=ComposeDocker())

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

        _print_summary(_manual_cfg(), docker=ComposeDocker())

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

        _print_summary(_manual_cfg(), docker=ComposeDocker())

        out = capsys.readouterr().out
        assert "--register-token <token>" in out
        # The recovery hint must redirect stderr (`2>&1`) before the
        # pipe — Python's logging writes the token line to stderr, and
        # `docker logs … | grep …` only sees stdout. Regression guard
        # for the empty-grep footgun.
        assert "docker logs lablink-allocator 2>&1 | grep" in out


class TestPrintSummaryMeshOverlay:
    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_next_step_shows_overlay_flags(self, mock_extract, mock_lan, capsys):
        """mesh_overlay clients aren't on the allocator's LAN — the
        lan_direct wording ('on each BYO box on the same LAN') is wrong
        here, and the command must include --overlay-hostname/
        --tailscale-authkey, which the lan_direct message never
        mentions since that connectivity has no such flags. hostname/machine-
        identity are no longer shown as required — run_locally defaults
        to on and auto-detects them; a --no-run-locally note points at
        the opt-out instead."""
        from lablink_cli.commands.deploy_compose import _print_summary

        token = "abc123def456ghi789jklmnop"
        mock_extract.return_value = token
        mock_lan.return_value = "192.168.1.42"

        _print_summary(
            _manual_cfg(connectivity="mesh_overlay", overlay_tailnet="example.ts.net"),
            docker=ComposeDocker(),
        )

        out = capsys.readouterr().out
        assert "on the same LAN" not in out
        assert "--overlay-hostname" in out
        assert "--tailscale-authkey" in out
        assert "--hostname <name>" not in out
        assert "--machine-identity <name>" not in out
        assert "--no-run-locally" in out
        assert f"--allocator-url http://192.168.1.42 --register-token {token}" in out

    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_lan_direct_next_step_unchanged(self, mock_extract, mock_lan, capsys):
        """Regression guard: the default lan_direct connectivity keeps
        its original BYO-on-the-LAN wording, with no overlay flags
        leaking into a connectivity mode that doesn't use them."""
        from lablink_cli.commands.deploy_compose import _print_summary

        mock_extract.return_value = "tok"
        mock_lan.return_value = "192.168.1.42"

        _print_summary(_manual_cfg(connectivity="lan_direct"), docker=ComposeDocker())

        out = capsys.readouterr().out
        assert "on each BYO box on the same LAN" in out
        assert "--overlay-hostname" not in out
        assert "--tailscale-authkey" not in out
        assert "--no-run-locally" not in out


class TestPrintSummaryFunnel:
    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_mesh_overlay_register_hint_uses_public_url_when_funnel_active(
        self, mock_extract, mock_lan, capsys
    ):
        """Regression: a mesh-overlay client (e.g. a Run:AI workload) is
        never on the allocator's LAN, so the LAN IP was always the wrong
        address for it — Funnel's public URL actually is reachable from
        anywhere, so prefer it here once Funnel is live. Uses the real
        URL passed in via funnel_url, not a guess from deployment_name/
        overlay_tailnet — Tailscale can assign a different hostname (e.g.
        a numeric suffix on a name collision)."""
        from lablink_cli.commands.deploy_compose import _print_summary

        token = "abc123def456ghi789jklmnop"
        mock_extract.return_value = token
        mock_lan.return_value = "192.168.1.42"
        real_url = "https://lablink-allocator-testlab-2.example.ts.net"

        _print_summary(
            _manual_cfg(
                connectivity="mesh_overlay",
                overlay_tailnet="example.ts.net",
            ),
            funnel_active=True,
            funnel_url=real_url,
            docker=ComposeDocker(),
        )

        out = capsys.readouterr().out
        assert f"--allocator-url {real_url} --register-token {token}" in out
        assert "--allocator-url http://192.168.1.42" not in out

    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_shows_public_url_line_when_funnel_active(
        self, mock_extract, mock_lan, capsys
    ):
        from lablink_cli.commands.deploy_compose import _print_summary

        mock_extract.return_value = "tok"
        mock_lan.return_value = "192.168.1.42"
        real_url = "https://lablink-allocator-testlab-2.example.ts.net"

        _print_summary(
            _manual_cfg(
                connectivity="mesh_overlay",
                overlay_tailnet="example.ts.net",
            ),
            funnel_active=True,
            funnel_url=real_url,
            docker=ComposeDocker(),
        )

        out = capsys.readouterr().out
        assert f"Allocator URL (public): {real_url}" in out

    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_public_url_line_honest_when_url_undetermined(
        self, mock_extract, mock_lan, capsys
    ):
        """funnel_active can be True while funnel_url is None (enable
        succeeded but the `tailscale funnel status` lookup didn't match
        the expected output). Must not fall back to a guessed URL — that
        was the actual bug (P2 review finding) this whole funnel_url
        plumbing replaces. Say we don't know, rather than guess wrong."""
        from lablink_cli.commands.deploy_compose import _print_summary

        mock_extract.return_value = "tok"
        mock_lan.return_value = "192.168.1.42"

        _print_summary(
            _manual_cfg(
                connectivity="mesh_overlay",
                overlay_tailnet="example.ts.net",
            ),
            funnel_active=True,
            funnel_url=None,
            docker=ComposeDocker(),
        )

        out = capsys.readouterr().out
        assert "lablink-allocator-testlab.example.ts.net" not in out
        assert "Allocator URL (public): (enabled, but the URL" in out
        # No real Funnel URL to substitute — the mesh-overlay register
        # hint falls back to the LAN URL, same as funnel_active=False.
        assert "--allocator-url http://192.168.1.42" in out

    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_no_public_url_line_when_funnel_inactive(
        self, mock_extract, mock_lan, capsys
    ):
        """Default funnel_active=False (participant_exposure: none, or
        Funnel enable failed) — no public URL line, unchanged output."""
        from lablink_cli.commands.deploy_compose import _print_summary

        mock_extract.return_value = "tok"
        mock_lan.return_value = "192.168.1.42"

        _print_summary(_manual_cfg(connectivity="mesh_overlay"), docker=ComposeDocker())

        out = capsys.readouterr().out
        assert "Allocator URL (public)" not in out

    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_no_localhost_warning_when_funnel_substituted(
        self, mock_extract, mock_lan, capsys
    ):
        """When no LAN IP is detected but Funnel supplies a real public
        URL for the mesh-overlay hint, the 'only valid for same machine'
        warning (which describes a localhost fallback that didn't
        happen here) must not fire."""
        from lablink_cli.commands.deploy_compose import _print_summary

        mock_extract.return_value = "tok"
        mock_lan.return_value = None

        _print_summary(
            _manual_cfg(
                connectivity="mesh_overlay",
                overlay_tailnet="example.ts.net",
            ),
            funnel_active=True,
            funnel_url="https://lablink-allocator-testlab.example.ts.net",
            docker=ComposeDocker(),
        )

        out = capsys.readouterr().out
        assert "only" not in out.lower() or "same machine" not in out.lower()

    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_localhost_warning_fires_when_url_undetermined_and_no_lan(
        self, mock_extract, mock_lan, capsys
    ):
        """funnel_active=True but funnel_url=None, and no LAN IP either —
        the register hint genuinely fell back to localhost, so the
        warning must still fire (it was wrongly suppressed by an earlier
        version of this check that only looked at funnel_active)."""
        from lablink_cli.commands.deploy_compose import _print_summary

        mock_extract.return_value = "tok"
        mock_lan.return_value = None

        _print_summary(
            _manual_cfg(
                connectivity="mesh_overlay",
                overlay_tailnet="example.ts.net",
            ),
            funnel_active=True,
            funnel_url=None,
            docker=ComposeDocker(),
        )

        out = capsys.readouterr().out
        assert "only valid for a BYO client running on this same machine" in out

    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_lan_direct_register_hint_unaffected_by_funnel(
        self, mock_extract, mock_lan, capsys
    ):
        """lan_direct clients genuinely are on the LAN — funnel_active
        must not redirect their register hint to the public URL, only
        mesh_overlay's."""
        from lablink_cli.commands.deploy_compose import _print_summary

        token = "abc123def456ghi789jklmnop"
        mock_extract.return_value = token
        mock_lan.return_value = "192.168.1.42"

        _print_summary(
            _manual_cfg(
                connectivity="lan_direct",
                overlay_tailnet="example.ts.net",
            ),
            funnel_active=True,
            funnel_url="https://lablink-allocator-testlab.example.ts.net",
            docker=ComposeDocker(),
        )

        out = capsys.readouterr().out
        assert (
            f"--allocator-url http://192.168.1.42 --register-token {token}" in out
        )


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
    def test_parses_uppercase_format(self):
        from lablink_cli.commands.deploy_compose import _extract_register_token

        fake = ComposeDocker(
            logs=Result(
                0, stdout="INFO root REGISTER_TOKEN=abc123def456ghi789jklmnop\n"
            )
        )
        assert _extract_register_token(docker=fake) == "abc123def456ghi789jklmnop"

    def test_parses_lowercase_assignment_format(self):
        from lablink_cli.commands.deploy_compose import _extract_register_token

        fake = ComposeDocker(
            logs=Result(0, stdout='register_token = "abc123def456ghi789jklmnop"\n')
        )
        assert _extract_register_token(docker=fake) == "abc123def456ghi789jklmnop"

    def test_merges_stderr_into_stdout(self):
        """The allocator's REGISTER_TOKEN log line is emitted via Python
        logging, which writes to stderr. `Docker.logs` preserves the
        container's stdout/stderr split, so the extractor must request
        `merge_stderr=True` — otherwise the token line is captured into
        the stderr half and the regex (which scans stdout) silently
        misses it. Regression guard."""
        from lablink_cli.commands.deploy_compose import _extract_register_token

        fake = _LoggingDocker(
            logs=Result(
                0, stdout="INFO root REGISTER_TOKEN=abc123def456ghi789jklmnop\n"
            )
        )
        _extract_register_token(docker=fake)
        assert fake.log_calls[0]["merge_stderr"] is True, (
            "merge_stderr must be True so the logger's stderr output is "
            "searched too"
        )

    def test_returns_none_when_docker_fails(self):
        from lablink_cli.commands.deploy_compose import _extract_register_token

        fake = ComposeDocker(logs=Result(1, stdout=""))
        assert _extract_register_token(docker=fake) is None

    def test_returns_none_when_no_match(self):
        from lablink_cli.commands.deploy_compose import _extract_register_token

        fake = ComposeDocker(logs=Result(0, stdout="nothing relevant\n"))
        assert _extract_register_token(docker=fake) is None


class TestCanonicalUrlFile:
    """The allocator-url file (issue #396): the out-of-band channel carrying
    the allocator's real public URL, since behind Funnel it can't derive one
    from the request (no X-Forwarded-Proto, and ssl.provider=none keeps the
    header-trust gate shut), and would otherwise hand clients an http:// URL
    that only 302-redirects — downgrading their POSTs to GET."""

    def test_filename_matches_allocator_constant(self):
        """The name is duplicated rather than imported, because each package's
        CI job installs only its own dependencies. Parse the allocator source
        with `ast` instead of importing it, so this check works in that
        isolated env too."""
        import ast

        from lablink_cli.commands.deploy_compose import CANONICAL_URL_FILENAME

        helpers = (
            Path(__file__).resolve().parents[2]
            / "allocator"
            / "src"
            / "lablink_allocator_service"
            / "utils"
            / "config_helpers.py"
        )
        assert helpers.exists(), helpers
        tree = ast.parse(helpers.read_text())
        found = {
            t.id: node.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            for t in node.targets
            if isinstance(t, ast.Name)
        }
        assert found.get("CANONICAL_URL_FILENAME") == CANONICAL_URL_FILENAME

    def test_file_materialized_empty_when_exposure_off(self, tmp_path):
        """Always created so the compose bind mount resolves; empty means the
        allocator falls back to the request host, which is right here."""
        from lablink_cli.commands.deploy_compose import (
            CANONICAL_URL_FILENAME,
            render_compose_dir,
        )

        cfg = _manual_cfg(connectivity="lan_direct", participant_exposure="none")
        target = tmp_path / "compose"
        render_compose_dir(cfg, target)

        path = target / CANONICAL_URL_FILENAME
        assert path.exists()
        assert path.read_text() == ""

    def test_file_materialized_when_funnel_enabled(self, tmp_path):
        from lablink_cli.commands.deploy_compose import (
            CANONICAL_URL_FILENAME,
            render_compose_dir,
        )

        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
        )
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-abc")

        assert (target / CANONICAL_URL_FILENAME).exists()

    def test_redeploy_preserves_url_while_funnel_stays_on(self, tmp_path):
        """Otherwise the window between container start and _enable_funnel
        would serve a fallback http:// URL to any client registering then."""
        from lablink_cli.commands.deploy_compose import (
            CANONICAL_URL_FILENAME,
            _write_canonical_url,
            render_compose_dir,
        )

        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
        )
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-abc")
        _write_canonical_url(target, "https://lablink-allocator-testlab.example.ts.net")

        render_compose_dir(cfg, target, tailscale_authkey="tskey-abc")
        content = (target / CANONICAL_URL_FILENAME).read_text()
        assert "https://lablink-allocator-testlab.example.ts.net" in content

    def test_turning_exposure_off_clears_the_url(self, tmp_path):
        """A stale public URL must not keep being handed to clients after the
        operator sets participant_exposure back to none."""
        from lablink_cli.commands.deploy_compose import (
            CANONICAL_URL_FILENAME,
            _write_canonical_url,
            render_compose_dir,
        )

        target = tmp_path / "compose"
        funnel_cfg = _manual_cfg(
            connectivity="mesh_overlay",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
        )
        render_compose_dir(funnel_cfg, target, tailscale_authkey="tskey-abc")
        _write_canonical_url(target, "https://old.example.ts.net")

        off_cfg = _manual_cfg(
            connectivity="mesh_overlay",
            participant_exposure="none",
            overlay_tailnet="example.ts.net",
        )
        render_compose_dir(off_cfg, target, tailscale_authkey="tskey-abc")
        assert (target / CANONICAL_URL_FILENAME).read_text() == ""

    def test_write_strips_trailing_slash(self, tmp_path):
        from lablink_cli.commands.deploy_compose import (
            CANONICAL_URL_FILENAME,
            _write_canonical_url,
        )

        target = tmp_path / "compose"
        target.mkdir()
        _write_canonical_url(target, "https://foo.example.ts.net/")
        assert (target / CANONICAL_URL_FILENAME).read_text() == (
            "https://foo.example.ts.net\n"
        )

    def test_write_is_in_place_not_a_rename(self, tmp_path):
        """docker bind-mounts a single file by inode: replacing the file via
        temp+rename would leave the running container reading the old one
        forever. Pin the inode so nobody 'improves' this into a rename."""
        from lablink_cli.commands.deploy_compose import (
            CANONICAL_URL_FILENAME,
            _write_canonical_url,
        )

        target = tmp_path / "compose"
        target.mkdir()
        path = target / CANONICAL_URL_FILENAME
        path.write_text("")
        before = path.stat().st_ino

        _write_canonical_url(target, "https://foo.example.ts.net")
        assert path.stat().st_ino == before

    @pytest.mark.parametrize(
        "connectivity,exposure",
        [
            ("lan_direct", "none"),
            ("mesh_overlay", "none"),
        ],
    )
    def test_every_non_funnel_topology_leaves_the_file_empty(
        self, connectivity, exposure, tmp_path
    ):
        """Blast-radius guard. The valid deployment topologies are: aws (which
        never renders a compose dir at all), manual+lan_direct+none,
        manual+mesh_overlay+none, and manual+mesh_overlay+tailscale_funnel
        (lan_direct+funnel is rejected by validate_config). Only the last one
        may ever get a URL here — every other manual topology must leave the
        file empty so the allocator falls back to request.host_url exactly as
        it did before this feature existed."""
        from lablink_cli.commands.deploy_compose import (
            CANONICAL_URL_FILENAME,
            render_compose_dir,
        )

        cfg = _manual_cfg(
            connectivity=connectivity,
            participant_exposure=exposure,
            overlay_tailnet="example.ts.net" if connectivity == "mesh_overlay" else "",
        )
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-abc")
        assert (target / CANONICAL_URL_FILENAME).read_text() == ""

    def test_sidecar_stack_still_mounts_the_file(self, tmp_path):
        """The sidecar stack must see the same /config layout as the plain
        one. Structurally guaranteed now that the sidecar is an override
        that never mentions the allocator service — this pins that: the
        override must not shadow the allocator's volumes."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(connectivity="mesh_overlay", overlay_tailnet="example.ts.net")
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-abc")

        assert (
            "./allocator-url:/config/allocator-url:ro"
            in (target / "docker-compose.yml").read_text()
        )
        assert "allocator" not in (
            target / "docker-compose.override.yml"
        ).read_text().split("volumes:")[-1]

    def test_rendered_compose_mount_resolves(self, tmp_path):
        """The mount source must exist after render, or docker refuses the
        run — the same trap custom-startup.sh's always-materialize avoids."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(connectivity="lan_direct", participant_exposure="none")
        target = tmp_path / "compose"
        render_compose_dir(cfg, target)

        compose = (target / "docker-compose.yml").read_text()
        assert "./allocator-url:/config/allocator-url:ro" in compose
        assert (target / "allocator-url").exists()

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    @patch("lablink_cli.commands.deploy_compose._enable_funnel")
    def test_deploy_writes_url_reported_by_funnel_status(
        self, mock_funnel, mock_up, mock_poll, mock_summary, tmp_path
    ):
        """The written value comes from `tailscale funnel status`, not from the
        configured hostname — that's what picks up the numeric suffixes (-2,
        -3, ...) a name collision with an offline prior-deploy node produces."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        mock_funnel.return_value = (True, "https://lablink-allocator-testlab-3.example.ts.net")
        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
            admin_password="a-strong-enough-password",
        )
        run_deploy_compose(
            cfg, yes=True, workdir_root=tmp_path, tailscale_authkey="tskey-abc"
        )

        written = (tmp_path / "testlab" / "allocator-url").read_text()
        assert written == "https://lablink-allocator-testlab-3.example.ts.net\n"

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    @patch("lablink_cli.commands.deploy_compose._enable_funnel")
    def test_deploy_leaves_file_alone_when_status_url_unknown(
        self, mock_funnel, mock_up, mock_poll, mock_summary, tmp_path
    ):
        """Funnel enabled but the URL couldn't be parsed: keep the last known
        value rather than clearing it, since an empty file falls back to the
        known-broken http:// host URL."""
        from lablink_cli.commands.deploy_compose import (
            _write_canonical_url,
            run_deploy_compose,
        )

        mock_funnel.return_value = (True, None)
        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
            admin_password="a-strong-enough-password",
        )
        target = tmp_path / "testlab"
        target.mkdir(parents=True)
        _write_canonical_url(target, "https://known.example.ts.net")

        run_deploy_compose(
            cfg, yes=True, workdir_root=tmp_path, tailscale_authkey="tskey-abc"
        )
        assert "https://known.example.ts.net" in (target / "allocator-url").read_text()


class TestRenderComposeDirCloudflareTunnel:
    def test_env_carries_mode_and_token(self, tmp_path):
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            overlay_tailnet="example.ts.net",
            participant_exposure="cloudflare_tunnel",
            public_hostname="lab.example.org",
        )
        target = tmp_path / "compose"
        render_compose_dir(
            cfg,
            target,
            tailscale_authkey="tskey-abc",
            cloudflare_tunnel_token="eyJhIjoiTOKEN",
        )

        env_content = (target / ".env").read_text()
        assert "PARTICIPANT_EXPOSURE=cloudflare_tunnel" in env_content
        assert "CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoiTOKEN" in env_content

    def test_env_always_declares_the_mode(self, tmp_path):
        """Compose templates have no conditionals, so the key must exist on
        every render or `docker compose up` warns about an unset variable."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(participant_exposure="none")
        target = tmp_path / "compose"
        render_compose_dir(cfg, target)

        env_content = (target / ".env").read_text()
        assert "PARTICIPANT_EXPOSURE=none" in env_content
        assert "CLOUDFLARE_TUNNEL_TOKEN" not in env_content

    def test_token_is_carried_forward_when_flag_omitted(self, tmp_path):
        """Mirrors TS_AUTHKEY: a redeploy without the flag must not blank
        out a working token."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            overlay_tailnet="example.ts.net",
            participant_exposure="cloudflare_tunnel",
            public_hostname="lab.example.org",
        )
        target = tmp_path / "compose"
        render_compose_dir(
            cfg,
            target,
            tailscale_authkey="tskey-abc",
            cloudflare_tunnel_token="eyJhIjoiFIRST",
        )
        render_compose_dir(cfg, target, tailscale_authkey="tskey-abc")

        assert "CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoiFIRST" in (target / ".env").read_text()

    def test_new_token_overrides_the_carried_one(self, tmp_path):
        """Rotation path: an explicitly supplied token must win."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            overlay_tailnet="example.ts.net",
            participant_exposure="cloudflare_tunnel",
            public_hostname="lab.example.org",
        )
        target = tmp_path / "compose"
        render_compose_dir(
            cfg,
            target,
            tailscale_authkey="tskey-abc",
            cloudflare_tunnel_token="eyJhIjoiOLD",
        )
        render_compose_dir(
            cfg,
            target,
            tailscale_authkey="tskey-abc",
            cloudflare_tunnel_token="eyJhIjoiNEW",
        )

        env_content = (target / ".env").read_text()
        assert "CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoiNEW" in env_content
        assert "eyJhIjoiOLD" not in env_content

    def test_canonical_url_written_at_render_time(self, tmp_path):
        """Unlike Funnel, the hostname is known before anything starts, so
        there is no after-the-fact write."""
        from lablink_cli.commands.deploy_compose import (
            CANONICAL_URL_FILENAME,
            render_compose_dir,
        )

        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            overlay_tailnet="example.ts.net",
            participant_exposure="cloudflare_tunnel",
            public_hostname="lab.example.org",
        )
        target = tmp_path / "compose"
        render_compose_dir(
            cfg,
            target,
            tailscale_authkey="tskey-abc",
            cloudflare_tunnel_token="eyJhIjoiTOKEN",
        )

        assert (
            target / CANONICAL_URL_FILENAME
        ).read_text() == "https://lab.example.org"

    def test_switching_away_clears_the_canonical_url(self, tmp_path):
        """A stale public URL handed to clients is worse than none."""
        from lablink_cli.commands.deploy_compose import (
            CANONICAL_URL_FILENAME,
            render_compose_dir,
        )

        target = tmp_path / "compose"
        render_compose_dir(
            _manual_cfg(
                connectivity="mesh_overlay",
                overlay_tailnet="example.ts.net",
                participant_exposure="cloudflare_tunnel",
                public_hostname="lab.example.org",
            ),
            target,
            tailscale_authkey="tskey-abc",
            cloudflare_tunnel_token="eyJhIjoiTOKEN",
        )
        render_compose_dir(_manual_cfg(participant_exposure="none"), target)

        assert (target / CANONICAL_URL_FILENAME).read_text() == ""

    def test_no_extra_compose_service_is_rendered(self, tmp_path):
        """The connector runs inside the allocator container, so the
        template count stays at two and no sidecar appears."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(
            connectivity="lan_direct",
            participant_exposure="cloudflare_tunnel",
            public_hostname="lab.example.org",
        )
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, cloudflare_tunnel_token="eyJhIjoiTOKEN")

        compose_yaml = (target / "docker-compose.yml").read_text()
        assert "cloudflared:" not in compose_yaml
        assert "PARTICIPANT_EXPOSURE" in compose_yaml
        assert "CLOUDFLARE_TUNNEL_TOKEN" in compose_yaml


class TestFunnelCanonicalUrlUnchanged:
    def test_funnel_still_preserves_the_previous_url(self, tmp_path):
        """Regression guard: Funnel's URL is unknown until _enable_funnel
        runs, so render must preserve whatever is already there."""
        from lablink_cli.commands.deploy_compose import (
            CANONICAL_URL_FILENAME,
            render_compose_dir,
        )

        cfg = _manual_cfg(
            connectivity="mesh_overlay",
            overlay_tailnet="example.ts.net",
            participant_exposure="tailscale_funnel",
        )
        target = tmp_path / "compose"
        render_compose_dir(cfg, target, tailscale_authkey="tskey-abc")
        (target / CANONICAL_URL_FILENAME).write_text("https://box.example.ts.net")
        render_compose_dir(cfg, target, tailscale_authkey="tskey-abc")

        assert (
            target / CANONICAL_URL_FILENAME
        ).read_text() == "https://box.example.ts.net"


class TestCloudflareTunnelPreflights:
    def _cf_cfg(self, **kw):
        return _manual_cfg(
            connectivity="mesh_overlay",
            overlay_tailnet="example.ts.net",
            participant_exposure="cloudflare_tunnel",
            public_hostname=kw.pop("public_hostname", "lab.example.org"),
            # _manual_cfg's default ("pw") is weak, and the exposure
            # password gate would then be what raises in every test here.
            admin_password=kw.pop("admin_password", "a-strong-password-1"),
            **kw,
        )

    def test_first_deploy_without_token_is_rejected(self, tmp_path):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        with pytest.raises(SystemExit):
            run_deploy_compose(
                self._cf_cfg(),
                yes=True,
                workdir_root=tmp_path,
                # Supplied so the sidecar's own authkey preflight can't be
                # what raises — this test is about the tunnel token.
                tailscale_authkey="tskey-abc",
            )

    def test_empty_public_hostname_is_rejected(self, tmp_path):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        with pytest.raises(SystemExit):
            run_deploy_compose(
                self._cf_cfg(public_hostname=""),
                yes=True,
                workdir_root=tmp_path,
                tailscale_authkey="tskey-abc",
                cloudflare_tunnel_token="eyJhIjoiTOKEN",
            )

    @pytest.mark.parametrize(
        "hostname",
        [
            "https://lab.example.org",
            "lab.example.org/",
            "lab.example.org:5000",
            "lab.example.org\nevil.example",
            "localhost",
        ],
    )
    # Everything downstream of the preflight is patched, including
    # _health_poll: if this check ever regresses, run_deploy_compose would
    # otherwise fall through to a real 300s health poll and this test would
    # hang for five minutes per case instead of failing immediately.
    @patch("lablink_cli.commands.deploy_compose._verify_public_hostname")
    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    def test_malformed_public_hostname_is_rejected(
        self, mock_up, mock_poll, mock_summary, mock_verify, tmp_path, hostname
    ):
        """`lablink deploy` never calls get_config_errors() for the manual
        provider, so this is the only gate a hand-edited config.yaml passes
        through. Without it a pasted scheme reaches the allocator-url file as
        "https://https://host" and every client is handed that."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        with pytest.raises(SystemExit):
            run_deploy_compose(
                self._cf_cfg(public_hostname=hostname),
                yes=True,
                workdir_root=tmp_path,
                tailscale_authkey="tskey-abc",
                cloudflare_tunnel_token="eyJhIjoiTOKEN",
            )
        # Rejected before anything starts, not after a half-built stack.
        mock_up.assert_not_called()

    @patch("lablink_cli.commands.deploy_compose._verify_public_hostname")
    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    def test_first_deploy_with_token_proceeds(
        self, mock_up, mock_poll, mock_summary, mock_verify, tmp_path
    ):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        mock_verify.return_value = True
        run_deploy_compose(
            self._cf_cfg(),
            yes=True,
            workdir_root=tmp_path,
            tailscale_authkey="tskey-abc",
            cloudflare_tunnel_token="eyJhIjoiTOKEN",
        )
        mock_up.assert_called_once()

    @patch("lablink_cli.commands.deploy_compose._verify_public_hostname")
    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    def test_redeploy_without_token_uses_the_recorded_one(
        self, mock_up, mock_poll, mock_summary, mock_verify, tmp_path
    ):
        """The token is on record in .env from the first deploy, so the
        preflight must not demand it again."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        mock_verify.return_value = True
        run_deploy_compose(
            self._cf_cfg(),
            yes=True,
            workdir_root=tmp_path,
            tailscale_authkey="tskey-abc",
            cloudflare_tunnel_token="eyJhIjoiTOKEN",
        )
        run_deploy_compose(
            self._cf_cfg(),
            yes=True,
            workdir_root=tmp_path,
            tailscale_authkey="tskey-abc",
        )
        assert mock_up.call_count == 2

    def test_lan_direct_is_rejected(self, tmp_path):
        """Same reasoning as lan_direct + Funnel: participant sessions would
        point at a client's LAN IP, mixed-content-blocked from HTTPS."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = _manual_cfg(
            connectivity="lan_direct",
            participant_exposure="cloudflare_tunnel",
            public_hostname="lab.example.org",
        )
        with pytest.raises(SystemExit):
            run_deploy_compose(
                cfg,
                yes=True,
                workdir_root=tmp_path,
                cloudflare_tunnel_token="eyJhIjoiTOKEN",
            )

    def test_weak_admin_password_is_rejected(self, tmp_path):
        """A publicly exposed allocator is bot-scanned within minutes,
        whichever tunnel publishes it."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        cfg = self._cf_cfg(admin_password="123456")
        with pytest.raises(SystemExit):
            run_deploy_compose(
                cfg,
                yes=True,
                workdir_root=tmp_path,
                tailscale_authkey="tskey-abc",
                cloudflare_tunnel_token="eyJhIjoiTOKEN",
            )

    @patch("lablink_cli.commands.deploy_compose._verify_public_hostname")
    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    @patch("lablink_cli.commands.deploy_compose._disable_funnel")
    def test_no_funnel_disable_dance_for_this_mode(
        self, mock_disable, mock_up, mock_poll, mock_summary, mock_verify, tmp_path
    ):
        """_disable_funnel is still called (exposure isn't tailscale_funnel),
        which is correct — it clears any Funnel state left in a preserved
        sidecar volume. What must NOT happen is _enable_funnel running."""
        from lablink_cli.commands import deploy_compose

        mock_verify.return_value = True
        with patch.object(deploy_compose, "_enable_funnel") as mock_enable:
            deploy_compose.run_deploy_compose(
                self._cf_cfg(),
                yes=True,
                workdir_root=tmp_path,
                tailscale_authkey="tskey-abc",
                cloudflare_tunnel_token="eyJhIjoiTOKEN",
            )
        mock_enable.assert_not_called()


class TestVerifyPublicHostname:
    @patch("lablink_cli.commands.deploy_compose.check_health_endpoint")
    def test_returns_true_when_the_hostname_answers(self, mock_check):
        from lablink_cli.commands.deploy_compose import _verify_public_hostname

        mock_check.return_value = {"healthy": True}
        assert _verify_public_hostname("lab.example.org") is True
        # One check proves DNS + Cloudflare edge + tunnel + nginx + Flask.
        assert mock_check.call_args[0][0] == "https://lab.example.org"

    @patch("lablink_cli.commands.deploy_compose.time.sleep")
    @patch("lablink_cli.commands.deploy_compose.check_health_endpoint")
    def test_retries_until_the_tunnel_route_comes_up(self, mock_check, mock_sleep):
        """The local health poll clears before cloudflared has registered
        with the edge, so the first tries legitimately miss on a good
        deploy. Regression guard for the single-attempt version, which
        warned on every cloudflare_tunnel deploy."""
        from lablink_cli.commands.deploy_compose import _verify_public_hostname

        mock_check.side_effect = [
            {"healthy": False},
            OSError("connection refused"),
            {"healthy": True},
        ]
        assert _verify_public_hostname("lab.example.org") is True
        assert mock_check.call_count == 3
        # Stops as soon as it succeeds — no sleep after the last try.
        assert mock_sleep.call_count == 2

    @patch("lablink_cli.commands.deploy_compose.time.sleep")
    @patch("lablink_cli.commands.deploy_compose.check_health_endpoint")
    def test_returns_false_after_exhausting_attempts(self, mock_check, mock_sleep):
        """Bounded: a wrong origin in the Cloudflare dashboard is not
        something waiting fixes, so the poll gives up and the caller warns."""
        from lablink_cli.commands.deploy_compose import (
            PUBLIC_HOSTNAME_MAX_ATTEMPTS,
            _verify_public_hostname,
        )

        mock_check.return_value = {"healthy": False}
        assert _verify_public_hostname("lab.example.org") is False
        assert mock_check.call_count == PUBLIC_HOSTNAME_MAX_ATTEMPTS
        # No trailing sleep once the budget is spent.
        assert mock_sleep.call_count == PUBLIC_HOSTNAME_MAX_ATTEMPTS - 1

    @patch("lablink_cli.commands.deploy_compose.time.sleep")
    @patch("lablink_cli.commands.deploy_compose.check_health_endpoint")
    def test_survives_a_raising_check(self, mock_check, mock_sleep):
        """DNS for a brand-new record may not resolve yet; a raised
        exception must be a warning, not a crashed deploy."""
        from lablink_cli.commands.deploy_compose import _verify_public_hostname

        mock_check.side_effect = OSError("name or service not known")
        assert _verify_public_hostname("lab.example.org") is False


class TestRedactSecretsInLogDump:
    def test_redacts_token_and_authkey_by_name(self):
        """cloudflared logs its whole environment at INFO, so the log dump
        can carry credentials. Keyed on the variable name, since the value
        formats are the vendors' to change."""
        from lablink_cli.commands.deploy_compose import _redact_secrets

        raw = (
            "INF Environmental variables "
            "map[CLOUDFLARE_TUNNEL_TOKEN:eyJhIjoiZGVhZGJlZWY]\n"
            "TS_AUTHKEY=tskey-auth-kSecret123\n"
            "cloudflared tunnel run --token eyJhIjoiZGVhZGJlZWY\n"
            "ordinary log line, must survive\n"
        )
        out = _redact_secrets(raw)

        assert "eyJhIjoiZGVhZGJlZWY" not in out
        assert "tskey-auth-kSecret123" not in out
        assert out.count("<redacted>") == 3
        assert "ordinary log line, must survive" in out

    def test_dump_merges_stderr_and_redacts(self, capsys):
        """The allocator's Python logging goes to stderr, so the dump has to
        merge it — which is what makes the redaction load-bearing."""
        from lablink_cli.commands.deploy_compose import _print_last_log_lines

        fake = _LoggingDocker(
            logs=Result(
                0,
                stdout="CLOUDFLARE_TUNNEL_TOKEN:eyJhIjoiLEAKED\nTraceback here\n",
            )
        )
        _print_last_log_lines(docker=fake)

        assert fake.log_calls[0]["merge_stderr"] is True
        out = capsys.readouterr().out
        assert "eyJhIjoiLEAKED" not in out
        assert "<redacted>" in out
        # The whole point of merging stderr: tracebacks must still show.
        assert "Traceback here" in out


class TestVerificationIsAWarningNotAFailure:
    def _cf_cfg(self):
        return _manual_cfg(
            connectivity="mesh_overlay",
            overlay_tailnet="example.ts.net",
            participant_exposure="cloudflare_tunnel",
            public_hostname="lab.example.org",
            admin_password="a-strong-password-1",
        )

    @patch("lablink_cli.commands.deploy_compose._verify_public_hostname")
    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    def test_unreachable_hostname_does_not_exit_nonzero(
        self, mock_up, mock_poll, mock_summary, mock_verify, tmp_path
    ):
        """A fresh proxied CNAME can still be propagating. The stack is up
        and correct; warn, don't fail."""
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        mock_verify.return_value = False
        run_deploy_compose(
            self._cf_cfg(),
            yes=True,
            workdir_root=tmp_path,
            tailscale_authkey="tskey-abc",
            cloudflare_tunnel_token="eyJhIjoiTOKEN",
        )
        mock_summary.assert_called_once()

    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_summary_prints_the_public_url(self, mock_extract, mock_lan, capsys):
        """The URL is derived from cfg inside _print_summary rather than
        threaded in as a parameter, so the summary is what pins it down."""
        from lablink_cli.commands.deploy_compose import _print_summary

        mock_extract.return_value = "abc123def456ghi789jklmnop"
        mock_lan.return_value = "192.168.1.42"

        _print_summary(self._cf_cfg(), docker=ComposeDocker())
        assert (
            "Allocator URL (public): https://lab.example.org"
            in capsys.readouterr().out
        )

        # ...and only for this mode.
        _print_summary(_manual_cfg(participant_exposure="none"), docker=ComposeDocker())
        assert "URL (public)" not in capsys.readouterr().out

    @patch("lablink_cli.commands.deploy_compose._verify_public_hostname")
    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    def test_not_called_for_other_exposure_modes(
        self, mock_up, mock_poll, mock_summary, mock_verify, tmp_path
    ):
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        run_deploy_compose(
            _manual_cfg(participant_exposure="none"),
            yes=True,
            workdir_root=tmp_path,
        )
        mock_verify.assert_not_called()

class TestReverseTunnelDeploy:
    def test_renders_no_extra_port_or_env(self, tmp_path):
        """The mode needs no inbound port and no secrets in .env. If this
        fails, the transport has regressed toward frp's shape."""
        from lablink_cli.commands.deploy_compose import render_compose_dir

        cfg = _manual_cfg(connectivity="reverse_tunnel")
        target = tmp_path / "compose"
        render_compose_dir(cfg, target)

        env = (target / ".env").read_text()
        assert "TUNNEL" not in env and "TOKEN" not in env
        compose = (target / "docker-compose.yml").read_text()
        assert compose.count("ports:") == 1
        assert ":8080" not in compose
        assert not (target / "docker-compose.override.yml").exists()

    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_register_hint_uses_public_url_when_funnel_active(
        self, mock_extract, mock_lan, capsys
    ):
        """Regression: a reverse_tunnel client is behind a NAT/firewall that
        can't accept inbound connections at all — participant_exposure:
        tailscale_funnel is the only way an off-LAN one reaches this
        deployment, exactly like mesh_overlay. Before this fix,
        funnel_url_used (and the register_url substitution) were gated on
        mesh_overlay only, so this printed an unreachable LAN address even
        with Funnel live."""
        from lablink_cli.commands.deploy_compose import _print_summary

        token = "abc123def456ghi789jklmnop"
        mock_extract.return_value = token
        mock_lan.return_value = "192.168.1.42"
        real_url = "https://lablink-allocator-testlab.example.ts.net"

        _print_summary(
            _manual_cfg(connectivity="reverse_tunnel"),
            funnel_active=True,
            funnel_url=real_url,
            docker=ComposeDocker(),
        )

        out = capsys.readouterr().out
        assert (
            f"--allocator-url {real_url} --register-token {token} --tunnel" in out
        )
        assert "--allocator-url http://192.168.1.42" not in out
        # ...and the hint is the off-LAN one, not the BYO-box one.
        assert "on the same LAN" not in out
        assert "--no-run-locally" in out

    @pytest.mark.parametrize("connectivity", ["mesh_overlay", "reverse_tunnel"])
    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_register_hint_uses_public_url_when_cloudflare_active(
        self, mock_extract, mock_lan, capsys, connectivity
    ):
        """Regression: the substitution above was gated on Funnel, so a
        cloudflare_tunnel deployment printed the LAN address that an off-LAN
        client cannot reach — despite a verified public HTTPS URL existing.
        Both off-LAN connectivity modes are affected; mesh_overlay +
        cloudflare_tunnel is this feature's own documented example."""
        from lablink_cli.commands.deploy_compose import _print_summary

        token = "abc123def456ghi789jklmnop"
        mock_extract.return_value = token
        mock_lan.return_value = "192.168.1.42"

        _print_summary(
            _manual_cfg(
                connectivity=connectivity,
                overlay_tailnet="example.ts.net",
                participant_exposure="cloudflare_tunnel",
                public_hostname="lab.example.org",
            ),
            docker=ComposeDocker(),
        )

        out = capsys.readouterr().out
        assert (
            f"--allocator-url https://lab.example.org --register-token {token}" in out
        )
        assert "--allocator-url http://192.168.1.42" not in out

    @patch("lablink_cli.commands.deploy_compose._detect_lan_ip")
    @patch("lablink_cli.commands.deploy_compose._extract_register_token")
    def test_lan_direct_hint_keeps_the_lan_url(self, mock_extract, mock_lan, capsys):
        """The substitution must stay scoped to off-LAN clients: a lan_direct
        BYO box genuinely is on the LAN, so it keeps the LAN address. (This
        config is preflight-rejected at deploy time; _print_summary is
        checked directly to pin the branch.)"""
        from lablink_cli.commands.deploy_compose import _print_summary

        mock_extract.return_value = "abc123def456ghi789jklmnop"
        mock_lan.return_value = "192.168.1.42"

        _print_summary(
            _manual_cfg(
                participant_exposure="cloudflare_tunnel",
                public_hostname="lab.example.org",
            ),
            docker=ComposeDocker(),
        )

        out = capsys.readouterr().out
        assert "--allocator-url http://192.168.1.42" in out
        assert "--allocator-url https://lab.example.org" not in out


class TestComposeDeploymentMetrics:
    """The compose deploy records to the CLI-local cache, like the AWS path.

    Without this, `lablink export-metrics --allocator` had nothing to report
    for a BYO deployment — the read side worked, the write side never existed.
    """

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    def test_success_writes_record(
        self, mock_up, mock_poll, mock_summary, tmp_path
    ):
        from lablink_cli import deployment_metrics
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        run_deploy_compose(_manual_cfg(), yes=True, workdir_root=tmp_path)

        records = deployment_metrics.load_all_metrics()
        assert len(records) == 1
        rec = records[0]
        assert rec["deployment_name"] == "testlab"
        # provider is what keeps these out of an AWS export of the same name.
        assert rec["provider"] == "manual"
        assert rec["status"] == "success"
        assert rec["allocator_compose_up_duration_seconds"] is not None
        assert rec["allocator_health_check_duration_seconds"] is not None
        assert rec["allocator_total_deployment_duration_seconds"] is not None
        assert rec["allocator_deploy_end_time"]
        # AWS-only dimensions stay empty rather than being invented.
        assert rec["region"] is None
        assert rec["template_version"] is None

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    def test_health_timeout_records_failure(
        self, mock_up, mock_summary, tmp_path
    ):
        """A health-poll timeout must land as 'failed', not 'in_progress'.

        _health_poll raises SystemExit for a real failure, so the compose
        path has to catch SystemExit where the AWS path deliberately
        doesn't (there it means the operator cancelled).
        """
        from lablink_cli import deployment_metrics
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        with patch(
            "lablink_cli.commands.deploy_compose._health_poll",
            side_effect=SystemExit(1),
        ):
            with pytest.raises(SystemExit):
                run_deploy_compose(_manual_cfg(), yes=True, workdir_root=tmp_path)

        records = deployment_metrics.load_all_metrics()
        assert len(records) == 1
        assert records[0]["status"] == "failed"

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    def test_render_failure_records_failure(
        self, mock_up, mock_poll, mock_summary, tmp_path
    ):
        """A failure *outside* the timed phases still records 'failed'.

        The record is written before render_compose_dir, so anything that
        escapes between that write and the success write would strand it at
        in_progress with null timings — indistinguishable from a Ctrl-C.
        """
        from lablink_cli import deployment_metrics
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        with patch(
            "lablink_cli.commands.deploy_compose.render_compose_dir",
            side_effect=OSError("disk full"),
        ):
            with pytest.raises(OSError):
                run_deploy_compose(_manual_cfg(), yes=True, workdir_root=tmp_path)

        records = deployment_metrics.load_all_metrics()
        assert len(records) == 1
        assert records[0]["status"] == "failed"
        assert "disk full" in records[0]["error"]
        # Never reached the phases, so their timings stay empty.
        assert records[0]["allocator_compose_up_duration_seconds"] is None

    @patch("lablink_cli.commands.deploy_compose._print_summary")
    @patch("lablink_cli.commands.deploy_compose._health_poll")
    @patch("lablink_cli.commands.deploy_compose._compose_up")
    def test_declined_confirmation_writes_nothing(
        self, mock_up, mock_poll, mock_summary, tmp_path
    ):
        """Aborting at the "Proceed?" gate leaves no in_progress junk."""
        from lablink_cli import deployment_metrics
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        with patch(
            "lablink_cli.commands.deploy_compose.typer.confirm",
            return_value=False,
        ):
            with pytest.raises(SystemExit):
                run_deploy_compose(_manual_cfg(), workdir_root=tmp_path)

        assert deployment_metrics.load_all_metrics() == []
