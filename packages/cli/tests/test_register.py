"""Tests for lablink_cli.commands.register — run_register orchestrator."""

from __future__ import annotations

import stat
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def tmp_env_file(tmp_path):
    return tmp_path / "client.env"


@pytest.fixture(autouse=True)
def isolate_startup_script_path(tmp_path, monkeypatch):
    """Redirect DEFAULT_STARTUP_SCRIPT into tmp_path for every test.

    `_write_startup_script` writes/unlinks at this path on every
    `run_register` call (including when the allocator returns an empty
    payload — it unlinks then). Without this fixture, tests that
    exercise the success path would touch the developer's real
    ``~/.lablink/client-custom-startup.sh``.
    """
    monkeypatch.setattr(
        "lablink_cli.commands.register.DEFAULT_STARTUP_SCRIPT",
        tmp_path / "client-custom-startup.sh",
    )


@pytest.fixture
def successful_response():
    return {
        "client_id": 42,
        "client_secret": "s",
        "agent_token": "a",
        "register_token": "r",
        "allocator_url": "https://lablink.example.com",
        "connectivity": "lan_direct",
        "client_image": "ghcr.io/talmolab/lablink-client:0.4.0",
        # New fields shipped by routes/registration.py. Defaults are
        # the "disabled" payload (empty b64 → no mount, no env vars),
        # which matches the existing tests' assumption that docker run
        # carries no --mount and no STARTUP_ON_ERROR.
        "startup_script_b64": "",
        "startup_on_error": "continue",
        "startup_max_attempts": 3,
        "startup_base_delay_seconds": 30,
        "startup_success_check_b64": "",
    }


def _kwargs(env_file, **overrides):
    base = dict(
        allocator_url="https://lablink.example.com",
        register_token="t",
        hostname=None,
        lan_ip=None,
        machine_identity=None,
        gpu_present=None,
        gpu_model=None,
        force=False,
        env_file=env_file,
        insecure=False,
    )
    base.update(overrides)
    return base


class TestResumePath:
    @patch("lablink_cli.commands.register._start_log_shipper")
    @patch("lablink_cli.commands.register.inspect_container_for_register")
    @patch("lablink_cli.commands.register._shipper_alive")
    @patch("lablink_cli.commands.register.subprocess.run")
    def test_everything_running_is_noop(
        self, mock_run, mock_alive, mock_inspect, mock_spawn, tmp_env_file
    ):
        from lablink_cli.commands.register import run_register
        tmp_env_file.write_text("CLIENT_ID=42\nCLIENT_SECRET=s\n")
        mock_inspect.return_value = "running"
        mock_alive.return_value = True

        run_register(**_kwargs(tmp_env_file))

        # Should NOT start a new container, NOT spawn a new shipper.
        mock_spawn.assert_not_called()
        # And should NOT do a fresh `docker run`.
        run_cmds = [
            c for call in mock_run.call_args_list
            for c in [call.args[0]]
            if "run" in c and "--env-file" in c
        ]
        assert run_cmds == []

    @patch("lablink_cli.commands.register._start_log_shipper")
    @patch("lablink_cli.commands.register.inspect_container_for_register")
    @patch("lablink_cli.commands.register._shipper_alive")
    @patch("lablink_cli.commands.register.subprocess.run")
    def test_dead_shipper_revived_no_re_register(
        self, mock_run, mock_alive, mock_inspect, mock_spawn, tmp_env_file
    ):
        from lablink_cli.commands.register import run_register
        tmp_env_file.write_text("CLIENT_ID=42\nCLIENT_SECRET=s\n")
        mock_inspect.return_value = "running"
        mock_alive.return_value = False

        run_register(**_kwargs(tmp_env_file))

        mock_spawn.assert_called_once()
        # The secret didn't change — env file content untouched.
        assert "CLIENT_SECRET=s" in tmp_env_file.read_text()

    @patch("lablink_cli.commands.register._start_log_shipper")
    @patch("lablink_cli.commands.register.inspect_container_for_register")
    @patch("lablink_cli.commands.register._shipper_alive")
    @patch("lablink_cli.commands.register.subprocess.run")
    def test_exited_container_restarted(
        self, mock_run, mock_alive, mock_inspect, mock_spawn, tmp_env_file
    ):
        from lablink_cli.commands.register import run_register
        tmp_env_file.write_text("CLIENT_ID=42\nCLIENT_SECRET=s\n")
        mock_inspect.return_value = "exited"
        mock_alive.return_value = False
        mock_run.return_value = MagicMock(returncode=0)

        run_register(**_kwargs(tmp_env_file))

        # docker start lablink-client invoked
        start_cmds = [
            c for call in mock_run.call_args_list
            for c in [call.args[0]]
            if c[:3] == ["docker", "start", "lablink-client"]
        ]
        assert start_cmds, (
            f"expected `docker start lablink-client` in {mock_run.call_args_list}"
        )
        mock_spawn.assert_called_once()

    def test_force_still_re_registers(
        self, tmp_env_file, successful_response,
    ):
        """--force must still mint a new secret (NOT enter resume path)."""
        from unittest.mock import patch
        from lablink_cli.commands.register import run_register
        tmp_env_file.write_text("CLIENT_ID=42\nCLIENT_SECRET=old\n")

        with patch(
            "lablink_cli.commands.register.RegistrationClient"
        ) as mock_client_cls, patch(
            "lablink_cli.commands.register.byo_detect"
        ) as mock_detect, patch(
            "lablink_cli.commands.register.shutil.which",
            return_value="/usr/bin/docker",
        ), patch(
            "lablink_cli.commands.register.subprocess.run"
        ) as mock_run, patch(
            "lablink_cli.commands.register.subprocess.Popen"
        ):
            mock_detect.detect_hostname.return_value = "byo-01"
            mock_detect.detect_lan_ip.return_value = "192.168.1.42"
            mock_detect.resolve_machine_identity.return_value = "mid"
            mock_detect.detect_gpu.return_value = (False, None)
            client = MagicMock()
            client.register.return_value = successful_response
            mock_client_cls.return_value = client
            mock_run.return_value = MagicMock(returncode=0, stdout="cgroupfs\n")

            run_register(**_kwargs(tmp_env_file, force=True))

            # A real `docker run` happened (not just `docker start`).
            run_cmds = [
                c for call in mock_run.call_args_list
                for c in [call.args[0]]
                if "run" in c and "--env-file" in c
            ]
            assert run_cmds, "expected `docker run` to be invoked under --force"
            # Env file was overwritten with the new secret.
            assert "CLIENT_SECRET=s" in tmp_env_file.read_text()


class TestOverlayHostnamePath:
    def test_requires_tailscale_authkey(self, tmp_env_file):
        from lablink_cli.commands.register import run_register

        try:
            run_register(**_kwargs(
                tmp_env_file,
                overlay_hostname="classroom-gpu-3",
                hostname="classroom-gpu-3",
                machine_identity="classroom-gpu-3",
            ))
            assert False, "expected SystemExit"
        except SystemExit as e:
            assert e.code == 1
        assert not tmp_env_file.exists()

    def test_requires_hostname_no_autodetect(self, tmp_env_file):
        """--hostname is required with --overlay-hostname --no-run-locally
        — auto-detect would silently report the admin's own laptop, not
        the future client. (run_locally defaults to True, where hostname
        IS auto-detected — this test exercises the hand-off opt-out.)"""
        from lablink_cli.commands.register import run_register

        try:
            run_register(**_kwargs(
                tmp_env_file,
                overlay_hostname="classroom-gpu-3",
                tailscale_authkey="tskey-abc",
                machine_identity="classroom-gpu-3",
                run_locally=False,
            ))
            assert False, "expected SystemExit"
        except SystemExit as e:
            assert e.code == 1
        assert not tmp_env_file.exists()

    def test_requires_machine_identity_no_autodetect(self, tmp_env_file):
        from lablink_cli.commands.register import run_register

        try:
            run_register(**_kwargs(
                tmp_env_file,
                overlay_hostname="classroom-gpu-3",
                tailscale_authkey="tskey-abc",
                hostname="classroom-gpu-3",
                run_locally=False,
            ))
            assert False, "expected SystemExit"
        except SystemExit as e:
            assert e.code == 1
        assert not tmp_env_file.exists()

    @patch("lablink_cli.commands.register.byo_detect")
    @patch("lablink_cli.commands.register.RegistrationClient")
    def test_success_skips_docker_and_prints_env(
        self, mock_client_cls, mock_detect, tmp_env_file, successful_response, capsys,
    ):
        from lablink_cli.commands.register import run_register

        resp = dict(successful_response, connectivity="mesh_overlay")
        mock_client = MagicMock()
        mock_client.register.return_value = resp
        mock_client_cls.return_value = mock_client

        run_register(**_kwargs(
            tmp_env_file,
            overlay_hostname="classroom-gpu-3",
            tailscale_authkey="tskey-abc",
            hostname="classroom-gpu-3",
            machine_identity="classroom-gpu-3",
            run_locally=False,
        ))

        # byo_detect must never be consulted on this path — it would
        # report facts about the admin's own laptop, not the future client.
        mock_detect.detect_hostname.assert_not_called()
        mock_detect.detect_lan_ip.assert_not_called()
        mock_detect.resolve_machine_identity.assert_not_called()
        mock_detect.detect_gpu.assert_not_called()

        # register() called with overlay_hostname, no lan_ip.
        mock_client.register.assert_called_once_with(
            hostname="classroom-gpu-3",
            machine_identity="classroom-gpu-3",
            overlay_hostname="classroom-gpu-3",
            gpu_present=False,
            gpu_model=None,
        )

        # env file still written.
        assert tmp_env_file.exists()

        # No docker/container output — instead, the env block + overlay
        # values are printed for the admin to paste into their own
        # Run:AI workload submission.
        out = capsys.readouterr().out
        assert "OVERLAY_HOSTNAME=classroom-gpu-3" in out
        assert "TAILSCALE_AUTHKEY=tskey-abc" in out
        assert "CLIENT_SECRET=s" in out

    @patch("lablink_cli.commands.register.subprocess.Popen")
    @patch("lablink_cli.commands.register.subprocess.run")
    @patch("lablink_cli.commands.register.shutil.which")
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_run_locally_default_autodetects_and_execs_docker(
        self, mock_detect, mock_client_cls, mock_which, mock_subproc_run,
        mock_popen, tmp_env_file, successful_response,
    ):
        """run_locally defaults to True: with --overlay-hostname alone
        (no --hostname/--machine-identity), the client is auto-detected
        exactly like real BYO, and the container is docker-run
        immediately with OVERLAY_HOSTNAME/TAILSCALE_AUTHKEY wired into
        its env file so start.sh's tailscale join fires."""
        from lablink_cli.commands.register import run_register

        mock_detect.detect_hostname.return_value = "runai-pod-7"
        mock_detect.resolve_machine_identity.return_value = "mid-runai-7"
        mock_detect.detect_gpu.return_value = (True, "NVIDIA A100")

        resp = dict(successful_response, connectivity="mesh_overlay")
        mock_client = MagicMock()
        mock_client.register.return_value = resp
        mock_client_cls.return_value = mock_client
        mock_which.return_value = "/usr/bin/docker"
        mock_subproc_run.return_value = MagicMock(
            returncode=0, stdout="cgroupfs\n"
        )

        run_register(**_kwargs(
            tmp_env_file,
            overlay_hostname="classroom-gpu-3",
            tailscale_authkey="tskey-abc",
        ))

        # lan_ip is never consulted for the overlay path, run_locally or not.
        mock_detect.detect_lan_ip.assert_not_called()

        mock_client.register.assert_called_once_with(
            hostname="runai-pod-7",
            machine_identity="mid-runai-7",
            overlay_hostname="classroom-gpu-3",
            gpu_present=True,
            gpu_model="NVIDIA A100",
        )

        content = tmp_env_file.read_text()
        assert "OVERLAY_HOSTNAME=classroom-gpu-3" in content
        assert "TAILSCALE_AUTHKEY=tskey-abc" in content

        all_cmds = [call.args[0] for call in mock_subproc_run.call_args_list]
        run_cmds = [c for c in all_cmds if "run" in c and "--env-file" in c]
        assert run_cmds, f"Expected a `docker run` call; got {all_cmds}"

        # tailscaled (started by start.sh) needs to create a TUN network
        # interface — without NET_ADMIN + /dev/net/tun it dies immediately
        # and `tailscale up` fails with "failed to connect to local
        # tailscaled; it doesn't appear to be running".
        cmd = run_cmds[0]
        cap_adds = [
            cmd[i + 1] for i, v in enumerate(cmd)
            if v == "--cap-add" and i + 1 < len(cmd)
        ]
        assert "NET_ADMIN" in cap_adds, f"missing --cap-add NET_ADMIN in {cmd}"
        assert "NET_RAW" in cap_adds, f"missing --cap-add NET_RAW in {cmd}"
        assert "--device" in cmd, f"missing --device in {cmd}"
        device_idx = cmd.index("--device")
        assert cmd[device_idx + 1] == "/dev/net/tun"

    def test_no_run_locally_without_overlay_hostname_aborts(self, tmp_env_file):
        """--no-run-locally only makes sense alongside --overlay-hostname
        — real BYO has no hand-off mode to opt into."""
        from lablink_cli.commands.register import run_register

        try:
            run_register(**_kwargs(tmp_env_file, run_locally=False))
            assert False, "expected SystemExit"
        except SystemExit as e:
            assert e.code == 1
        assert not tmp_env_file.exists()


class TestSuccessFlow:
    @patch("lablink_cli.commands.register.subprocess.Popen")
    @patch("lablink_cli.commands.register.subprocess.run")
    @patch("lablink_cli.commands.register.shutil.which")
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_full_success_writes_env_file_and_execs_docker(
        self, mock_detect, mock_client_cls, mock_which, mock_subproc_run,
        mock_popen, tmp_env_file, successful_response,
    ):
        from lablink_cli.commands.register import run_register
        mock_detect.detect_hostname.return_value = "byo-01"
        mock_detect.detect_lan_ip.return_value = "192.168.1.42"
        mock_detect.resolve_machine_identity.return_value = "mid-abc"
        mock_detect.detect_gpu.return_value = (True, "NVIDIA T4")

        mock_client = MagicMock()
        mock_client.register.return_value = successful_response
        mock_client_cls.return_value = mock_client
        mock_which.return_value = "/usr/bin/docker"
        mock_subproc_run.return_value = MagicMock(returncode=0, stdout="cgroupfs\n")

        run_register(**_kwargs(tmp_env_file))

        # env file written with 0600
        assert tmp_env_file.exists()
        mode = stat.S_IMODE(tmp_env_file.stat().st_mode)
        assert mode == 0o600
        content = tmp_env_file.read_text()
        assert "CLIENT_ID=42" in content
        assert "VM_NAME=42" in content
        assert "CLIENT_SECRET=s" in content
        assert "AGENT_TOKEN=a" in content
        assert "API_TOKEN" not in content
        assert "REGISTER_TOKEN=r" in content
        assert "ALLOCATOR_URL=https://lablink.example.com" in content
        assert "ALLOCATOR_HOST=lablink.example.com" in content
        assert "CONNECTIVITY=lan_direct" in content
        assert "CLIENT_IMAGE=ghcr.io/talmolab/lablink-client:0.4.0" in content

        # client.register called with resolved values
        mock_client.register.assert_called_once_with(
            hostname="byo-01",
            machine_identity="mid-abc",
            lan_ip="192.168.1.42",
            gpu_present=True,
            gpu_model="NVIDIA T4",
        )

        # docker run invoked with the expected command shape.
        # subprocess.run is called twice: once for `docker rm -f` (cleanup),
        # then `docker run …`. Pick out the run command for assertions.
        all_cmds = [call.args[0] for call in mock_subproc_run.call_args_list]
        run_cmds = [c for c in all_cmds if "run" in c and "--env-file" in c]
        assert run_cmds, f"Expected a `docker run` call; got {all_cmds}"
        cmd = run_cmds[0]
        assert cmd[0] == "docker"
        assert "run" in cmd
        assert "--env-file" in cmd
        assert "--gpus" in cmd  # gpu_present=True
        # 7070/6080 published; see ports-not-network-host test below.
        assert "--publish" in cmd
        # `--pull always` so a republished tag (same name, new layers)
        # is fetched on re-register — `--pull missing` (Docker default)
        # would silently reuse the local cache and ship stale bits.
        pull_idx = cmd.index("--pull")
        assert cmd[pull_idx + 1] == "always"
        assert "ghcr.io/talmolab/lablink-client:0.4.0" in cmd

        # Log shipper spawned exactly once with the env file
        assert mock_popen.call_count == 1
        shipper_cmd = mock_popen.call_args.args[0]
        assert "lablink_cli.log_shipper" in shipper_cmd
        assert str(tmp_env_file) in shipper_cmd

    @patch("lablink_cli.commands.register.subprocess.Popen")
    @patch("lablink_cli.commands.register.subprocess.run")
    @patch("lablink_cli.commands.register.shutil.which")
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_user_overrides_beat_detection(
        self, mock_detect, mock_client_cls, mock_which, mock_subproc_run,
        mock_popen, tmp_env_file, successful_response,
    ):
        from lablink_cli.commands.register import run_register
        mock_detect.detect_hostname.return_value = "auto-host"
        mock_detect.detect_lan_ip.return_value = "10.0.0.1"
        mock_detect.resolve_machine_identity.return_value = "auto-mid"
        # Detection returns no GPU — user's overrides for non-GPU fields are
        # what's under test here; GPU fallback behavior is covered separately.
        mock_detect.detect_gpu.return_value = (False, None)

        mock_client = MagicMock()
        mock_client.register.return_value = successful_response
        mock_client_cls.return_value = mock_client
        mock_which.return_value = "/usr/bin/docker"
        mock_subproc_run.return_value = MagicMock(returncode=0, stdout="cgroupfs\n")

        run_register(**_kwargs(
            tmp_env_file,
            hostname="user-host",
            lan_ip="172.16.0.5",
            machine_identity="user-mid",
            gpu_present=False,
            gpu_model=None,
        ))

        mock_client.register.assert_called_once_with(
            hostname="user-host",
            machine_identity="user-mid",
            lan_ip="172.16.0.5",
            gpu_present=False,
            gpu_model=None,
        )

    @patch("lablink_cli.commands.register.byo_detect")
    def test_missing_hostname_aborts(self, mock_detect, tmp_env_file):
        from lablink_cli.commands.register import run_register
        mock_detect.detect_hostname.return_value = None
        with pytest.raises(SystemExit):
            run_register(**_kwargs(tmp_env_file))

    @patch("lablink_cli.commands.register.byo_detect")
    def test_missing_lan_ip_aborts(self, mock_detect, tmp_env_file):
        from lablink_cli.commands.register import run_register
        mock_detect.detect_hostname.return_value = "h"
        mock_detect.detect_lan_ip.return_value = None
        with pytest.raises(SystemExit):
            run_register(**_kwargs(tmp_env_file))

    @patch("lablink_cli.commands.register.subprocess.Popen")
    @patch("lablink_cli.commands.register.subprocess.run")
    @patch("lablink_cli.commands.register.shutil.which")
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_gpu_present_override_keeps_detected_model(
        self, mock_detect, mock_client_cls, mock_which, mock_subproc_run,
        mock_popen, tmp_env_file, successful_response,
    ):
        """User passes --gpu-present (no --gpu-model); detection still provides
        the model. Fixes a previous gap where this combination dropped the model."""
        from lablink_cli.commands.register import run_register
        mock_detect.detect_hostname.return_value = "h"
        mock_detect.detect_lan_ip.return_value = "1.2.3.4"
        mock_detect.resolve_machine_identity.return_value = "m"
        mock_detect.detect_gpu.return_value = (True, "NVIDIA A100")  # detected
        mock_client = MagicMock()
        mock_client.register.return_value = successful_response
        mock_client_cls.return_value = mock_client
        mock_which.return_value = "/usr/bin/docker"
        mock_subproc_run.return_value = MagicMock(returncode=0, stdout="cgroupfs\n")

        run_register(**_kwargs(
            tmp_env_file,
            gpu_present=True,  # user override; no gpu_model passed
        ))

        mock_client.register.assert_called_once_with(
            hostname="h",
            machine_identity="m",
            lan_ip="1.2.3.4",
            gpu_present=True,
            gpu_model="NVIDIA A100",  # detection-supplied fallback
        )

    @patch("lablink_cli.commands.register.subprocess.Popen")
    @patch("lablink_cli.commands.register.subprocess.run")
    @patch("lablink_cli.commands.register.shutil.which")
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_gpu_model_override_wins_over_detection(
        self, mock_detect, mock_client_cls, mock_which, mock_subproc_run,
        mock_popen, tmp_env_file, successful_response,
    ):
        from lablink_cli.commands.register import run_register
        mock_detect.detect_hostname.return_value = "h"
        mock_detect.detect_lan_ip.return_value = "1.2.3.4"
        mock_detect.resolve_machine_identity.return_value = "m"
        mock_detect.detect_gpu.return_value = (True, "DETECTED")
        mock_client = MagicMock()
        mock_client.register.return_value = successful_response
        mock_client_cls.return_value = mock_client
        mock_which.return_value = "/usr/bin/docker"
        mock_subproc_run.return_value = MagicMock(returncode=0, stdout="cgroupfs\n")

        run_register(**_kwargs(
            tmp_env_file,
            gpu_model="USER_PROVIDED",  # explicit model; no gpu_present arg
        ))

        # gpu_present picks up from detection (True), gpu_model takes user override
        mock_client.register.assert_called_once_with(
            hostname="h",
            machine_identity="m",
            lan_ip="1.2.3.4",
            gpu_present=True,
            gpu_model="USER_PROVIDED",
        )

    @patch("lablink_cli.commands.register.subprocess.Popen")
    @patch("lablink_cli.commands.register.subprocess.run")
    @patch("lablink_cli.commands.register.shutil.which")
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_publishes_agent_and_kasmvnc_ports_not_network_host(
        self, mock_detect, mock_client_cls, mock_which, mock_subproc_run,
        mock_popen, tmp_env_file, successful_response,
    ):
        """The allocator reaches the BYO client over the LAN at
        ``<lan_ip>:7070`` (agent) and proxies KasmVNC over ``:6080``.

        ``--network host`` shares the host's network namespace on Linux,
        so those ports land on the LAN IP directly. On Docker Desktop
        (Windows/macOS) ``--network host`` instead drops the container
        into the Docker VM's network — the host never binds the ports
        and the allocator's password-rotation call times out at the
        container's :7070. Explicit ``--publish`` works the same on
        every platform, so we always publish 7070 and 6080 and never
        ask for ``--network host``.
        """
        from lablink_cli.commands.register import run_register
        mock_detect.detect_hostname.return_value = "byo-01"
        mock_detect.detect_lan_ip.return_value = "192.168.1.42"
        mock_detect.resolve_machine_identity.return_value = "mid-abc"
        mock_detect.detect_gpu.return_value = (False, None)

        mock_client = MagicMock()
        mock_client.register.return_value = successful_response
        mock_client_cls.return_value = mock_client
        mock_which.return_value = "/usr/bin/docker"
        mock_subproc_run.return_value = MagicMock(returncode=0, stdout="cgroupfs\n")

        run_register(**_kwargs(tmp_env_file))

        all_cmds = [call.args[0] for call in mock_subproc_run.call_args_list]
        run_cmds = [c for c in all_cmds if "run" in c and "--env-file" in c]
        assert run_cmds, f"Expected a `docker run` call; got {all_cmds}"
        cmd = run_cmds[0]

        # Both ports published with host:container mapping.
        assert "--publish" in cmd or "-p" in cmd, (
            f"expected port publishing in docker run, got {cmd}"
        )
        # Look at every value following a publish flag.
        published = [
            cmd[i + 1] for i, v in enumerate(cmd)
            if v in ("--publish", "-p") and i + 1 < len(cmd)
        ]
        assert "7070:7070" in published, (
            f"agent port 7070 not published; published={published}"
        )
        assert "6080:6080" in published, (
            f"kasmvnc port 6080 not published; published={published}"
        )
        # Must not request host networking — defeats the purpose on
        # Windows/macOS Docker Desktop and is unnecessary on Linux.
        assert "--network" not in cmd, (
            f"--network must not be passed (was: {cmd})"
        )
        # A real-BYO (lan_direct) client never runs `tailscale up` — the
        # NET_ADMIN/tun grant is overlay-only and must not leak here.
        assert "--cap-add" not in cmd, (
            f"real-BYO docker run must not request any capabilities: {cmd}"
        )
        assert "--device" not in cmd, (
            f"real-BYO docker run must not request any devices: {cmd}"
        )


class TestGpuRuntimePreflight:
    """systemd cgroup driver revokes GPU device permissions from running
    containers asynchronously. The pre-flight refuses to launch a GPU
    container on a host whose docker daemon isn't configured for cgroupfs.
    """

    @patch("lablink_cli.commands.register.subprocess.run")
    @patch("lablink_cli.commands.register.shutil.which")
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_aborts_when_cgroup_driver_systemd_and_gpu_present(
        self, mock_detect, mock_client_cls, mock_which, mock_subproc_run,
        tmp_env_file, successful_response,
    ):
        from lablink_cli.commands.register import run_register
        mock_detect.detect_hostname.return_value = "h"
        mock_detect.detect_lan_ip.return_value = "1.2.3.4"
        mock_detect.resolve_machine_identity.return_value = "m"
        mock_detect.detect_gpu.return_value = (True, "Tesla T4")
        mock_client = MagicMock()
        mock_client.register.return_value = successful_response
        mock_client_cls.return_value = mock_client
        mock_which.return_value = "/usr/bin/docker"
        # docker info returns "systemd" — the unstable default.
        mock_subproc_run.return_value = MagicMock(
            returncode=0, stdout="systemd\n"
        )

        with pytest.raises(SystemExit) as exc:
            run_register(**_kwargs(tmp_env_file))
        assert exc.value.code != 0

        # Env file is preserved so admin can fix daemon.json + re-run --force
        # without re-minting secrets.
        assert tmp_env_file.exists()

        # docker info was called; docker run was NOT.
        all_cmds = [c.args[0] for c in mock_subproc_run.call_args_list]
        assert any("info" in c for c in all_cmds), (
            f"Expected docker info call; got {all_cmds}"
        )
        assert not any("run" in c and "--env-file" in c for c in all_cmds), (
            f"docker run must not fire when cgroup driver check fails; "
            f"got {all_cmds}"
        )

    @patch("lablink_cli.commands.register.subprocess.Popen")
    @patch("lablink_cli.commands.register.subprocess.run")
    @patch("lablink_cli.commands.register.shutil.which")
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_skips_cgroup_check_when_gpu_absent(
        self, mock_detect, mock_client_cls, mock_which, mock_subproc_run,
        mock_popen, tmp_env_file, successful_response,
    ):
        """CPU-only BYO clients don't need GPU runtime — never query
        docker info, never block on cgroup driver. Even if the host is
        in the unstable systemd config, a CPU client still works."""
        from lablink_cli.commands.register import run_register
        mock_detect.detect_hostname.return_value = "h"
        mock_detect.detect_lan_ip.return_value = "1.2.3.4"
        mock_detect.resolve_machine_identity.return_value = "m"
        mock_detect.detect_gpu.return_value = (False, None)
        mock_client = MagicMock()
        mock_client.register.return_value = successful_response
        mock_client_cls.return_value = mock_client
        mock_which.return_value = "/usr/bin/docker"
        mock_subproc_run.return_value = MagicMock(
            returncode=0, stdout="systemd\n"
        )

        run_register(**_kwargs(tmp_env_file))

        all_cmds = [c.args[0] for c in mock_subproc_run.call_args_list]
        assert not any("info" in c for c in all_cmds), (
            f"docker info should not be called for CPU clients; got {all_cmds}"
        )

    @patch("lablink_cli.commands.register.subprocess.run")
    @patch("lablink_cli.commands.register.shutil.which")
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_aborts_when_docker_info_fails(
        self, mock_detect, mock_client_cls, mock_which, mock_subproc_run,
        tmp_env_file, successful_response,
    ):
        """If docker is on PATH but the daemon isn't running, docker info
        errors. Abort with a clear message rather than launching a
        container that will fail to start."""
        import subprocess as _sp
        from lablink_cli.commands.register import run_register
        mock_detect.detect_hostname.return_value = "h"
        mock_detect.detect_lan_ip.return_value = "1.2.3.4"
        mock_detect.resolve_machine_identity.return_value = "m"
        mock_detect.detect_gpu.return_value = (True, "Tesla T4")
        mock_client = MagicMock()
        mock_client.register.return_value = successful_response
        mock_client_cls.return_value = mock_client
        mock_which.return_value = "/usr/bin/docker"
        mock_subproc_run.side_effect = _sp.CalledProcessError(
            1, ["docker", "info"], stderr="daemon not running"
        )

        with pytest.raises(SystemExit) as exc:
            run_register(**_kwargs(tmp_env_file))
        assert exc.value.code != 0


class TestDockerMissing:
    @patch("lablink_cli.commands.register.shutil.which")
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_aborts_when_docker_missing_but_preserves_env_file(
        self, mock_detect, mock_client_cls, mock_which,
        tmp_env_file, successful_response,
    ):
        """Exec aborts (non-zero) when docker missing; env file is preserved
        so the user can install docker + re-run with --force."""
        from lablink_cli.commands.register import run_register
        mock_detect.detect_hostname.return_value = "h"
        mock_detect.detect_lan_ip.return_value = "1.2.3.4"
        mock_detect.resolve_machine_identity.return_value = "m"
        mock_detect.detect_gpu.return_value = (False, None)
        mock_client = MagicMock()
        mock_client.register.return_value = successful_response
        mock_client_cls.return_value = mock_client
        mock_which.return_value = None

        with pytest.raises(SystemExit):
            run_register(**_kwargs(tmp_env_file))

        # env file still written so user can install docker + re-run later
        assert tmp_env_file.exists()


class TestForceFlag:
    @patch("lablink_cli.commands.register.subprocess.Popen")
    @patch("lablink_cli.commands.register.subprocess.run")
    @patch("lablink_cli.commands.register.shutil.which")
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_force_overwrites_env_file(
        self, mock_detect, mock_client_cls, mock_which, mock_subproc_run,
        mock_popen, tmp_env_file, successful_response,
    ):
        from lablink_cli.commands.register import run_register
        tmp_env_file.write_text("CLIENT_ID=99\n")  # stale
        mock_detect.detect_hostname.return_value = "h"
        mock_detect.detect_lan_ip.return_value = "1.2.3.4"
        mock_detect.resolve_machine_identity.return_value = "m"
        mock_detect.detect_gpu.return_value = (False, None)
        mock_client = MagicMock()
        mock_client.register.return_value = successful_response
        mock_client_cls.return_value = mock_client
        mock_which.return_value = "/usr/bin/docker"
        mock_subproc_run.return_value = MagicMock(returncode=0, stdout="cgroupfs\n")

        run_register(**_kwargs(tmp_env_file, force=True))

        assert "CLIENT_ID=42" in tmp_env_file.read_text()
        assert "CLIENT_ID=99" not in tmp_env_file.read_text()

    @patch("lablink_cli.commands.register.subprocess.Popen")
    @patch("lablink_cli.commands.register.subprocess.run")
    @patch("lablink_cli.commands.register.shutil.which")
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_force_removes_existing_container_before_run(
        self, mock_detect, mock_client_cls, mock_which, mock_subproc_run,
        mock_popen, tmp_env_file, successful_response,
    ):
        """With --force, the orchestrator must `docker rm -f` the old container
        before `docker run`, otherwise the new run hits a name collision."""
        from lablink_cli.commands.register import run_register
        tmp_env_file.write_text("CLIENT_ID=99\n")  # existing env file
        mock_detect.detect_hostname.return_value = "h"
        mock_detect.detect_lan_ip.return_value = "1.2.3.4"
        mock_detect.resolve_machine_identity.return_value = "m"
        mock_detect.detect_gpu.return_value = (False, None)
        mock_client = MagicMock()
        mock_client.register.return_value = successful_response
        mock_client_cls.return_value = mock_client
        mock_which.return_value = "/usr/bin/docker"
        mock_subproc_run.return_value = MagicMock(returncode=0, stdout="cgroupfs\n")

        run_register(**_kwargs(tmp_env_file, force=True))

        # subprocess.run should have been called at least twice:
        # one for `docker rm -f lablink-client`, one for `docker run …`.
        all_cmds = [call.args[0] for call in mock_subproc_run.call_args_list]
        rm_calls = [c for c in all_cmds if "rm" in c and "lablink-client" in c]
        run_calls = [c for c in all_cmds if "run" in c and "lablink-client" in c]
        assert rm_calls, f"Expected `docker rm -f lablink-client` call; got {all_cmds}"
        assert run_calls, f"Expected `docker run` call; got {all_cmds}"
        # rm must precede run
        rm_idx = all_cmds.index(rm_calls[0])
        run_idx = all_cmds.index(run_calls[0])
        assert rm_idx < run_idx, "docker rm must happen before docker run"


class TestErrorMapping:
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_auth_error_exits_nonzero(
        self, mock_detect, mock_client_cls,
        tmp_env_file,
    ):
        from lablink_cli.api import AllocatorAuthError
        from lablink_cli.commands.register import run_register
        mock_detect.detect_hostname.return_value = "h"
        mock_detect.detect_lan_ip.return_value = "1.2.3.4"
        mock_detect.resolve_machine_identity.return_value = "m"
        mock_detect.detect_gpu.return_value = (False, None)
        mock_client = MagicMock()
        mock_client.register.side_effect = AllocatorAuthError("nope")
        mock_client_cls.return_value = mock_client

        with pytest.raises(SystemExit) as exc:
            run_register(**_kwargs(tmp_env_file))
        assert exc.value.code != 0
        # env file NOT created on failed register
        assert not tmp_env_file.exists()


class TestStartLogShipper:
    @patch("lablink_cli.commands.register.subprocess.Popen")
    def test_spawns_detached_python_module(
        self, mock_popen, tmp_path, monkeypatch
    ):
        from lablink_cli.commands.register import _start_log_shipper
        from rich.console import Console

        # Point PID_FILE at tmp_path so _stop_existing_shipper doesn't
        # touch the real ~/.lablink/log_shipper.pid (would otherwise risk
        # terminating a live shipper on the developer's machine).
        monkeypatch.setattr(
            "lablink_cli.commands.register.PID_FILE",
            tmp_path / "log_shipper.pid",
        )

        env_file = tmp_path / "client.env"
        env_file.write_text("CLIENT_ID=1\n")
        mock_popen.return_value = MagicMock(pid=99999)

        _start_log_shipper(env_file, Console())

        assert mock_popen.call_count == 1
        cmd = mock_popen.call_args.args[0]
        # invoked as: python -m lablink_cli.log_shipper <env_file>
        assert cmd[0].endswith("python") or "python" in cmd[0]
        assert "-m" in cmd
        assert "lablink_cli.log_shipper" in cmd
        assert str(env_file) in cmd
        # detached: start_new_session on POSIX OR Windows creationflags
        kwargs = mock_popen.call_args.kwargs
        assert kwargs.get("start_new_session") is True or (
            kwargs.get("creationflags", 0) != 0
        )
        # stdin closed; stdout/stderr to log file
        assert kwargs.get("stdin") is not None  # DEVNULL

    @patch("lablink_cli.commands.register._stop_existing_shipper")
    @patch("lablink_cli.commands.register.subprocess.Popen")
    def test_terminates_existing_shipper_before_spawn(
        self, mock_popen, mock_stop, tmp_path
    ):
        """Guarantees there is no overlap between old and new shippers
        (which would POST duplicates under --force re-register)."""
        from unittest.mock import Mock
        from lablink_cli.commands.register import _start_log_shipper
        from rich.console import Console

        env_file = tmp_path / "client.env"
        env_file.write_text("CLIENT_ID=1\n")
        mock_popen.return_value = MagicMock(pid=99999)

        # Attach both mocks to a parent so we get a single ordered call
        # log. Asserting the call names appear in source order catches a
        # future refactor that moves Popen above _stop_existing_shipper.
        parent = Mock()
        parent.attach_mock(mock_stop, "stop")
        parent.attach_mock(mock_popen, "popen")

        _start_log_shipper(env_file, Console())

        call_names = [c[0] for c in parent.mock_calls]
        assert call_names == ["stop", "popen"], (
            f"expected stop -> popen, got {call_names}"
        )


class TestStopExistingShipper:
    """Covers `_stop_existing_shipper` — the kill-old-shipper step that
    prevents double-shipper duplicate POSTs during --force re-register."""

    def _fake_psutil(self, monkeypatch, process_factory):
        """Install a fake psutil module whose `Process()` returns whatever
        process_factory() yields. Exceptions are re-exported as classes so
        ``except psutil.NoSuchProcess`` works in the SUT."""
        from unittest.mock import MagicMock
        from lablink_cli.commands import register

        fake = MagicMock()
        fake.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        fake.AccessDenied = type("AccessDenied", (Exception,), {})
        fake.TimeoutExpired = type("TimeoutExpired", (Exception,), {})
        fake.Process.side_effect = process_factory
        monkeypatch.setattr(register, "psutil", fake)
        return fake

    def test_no_pid_file_is_noop(self, tmp_path, monkeypatch):
        from lablink_cli.commands import register
        from rich.console import Console

        pid_file = tmp_path / "log_shipper.pid"
        monkeypatch.setattr(register, "PID_FILE", pid_file)

        # Should not raise; should not touch psutil at all.
        register._stop_existing_shipper(Console())

    def test_terminates_matching_shipper(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock
        from lablink_cli.commands import register
        from rich.console import Console

        pid_file = tmp_path / "log_shipper.pid"
        pid_file.write_text("12345")
        monkeypatch.setattr(register, "PID_FILE", pid_file)

        fake_proc = MagicMock()
        fake_proc.cmdline.return_value = [
            "/usr/bin/python", "-m",
            "lablink_cli.log_shipper", "/x/client.env",
        ]
        self._fake_psutil(monkeypatch, lambda _pid: fake_proc)

        register._stop_existing_shipper(Console())

        fake_proc.terminate.assert_called_once()
        fake_proc.wait.assert_called_once()
        # PID file cleared so a stale entry never confuses the next run.
        assert not pid_file.exists()

    def test_escalates_to_kill_on_timeout(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock
        from lablink_cli.commands import register
        from rich.console import Console

        pid_file = tmp_path / "log_shipper.pid"
        pid_file.write_text("12345")
        monkeypatch.setattr(register, "PID_FILE", pid_file)

        fake_proc = MagicMock()
        fake_proc.cmdline.return_value = [
            "python", "-m", "lablink_cli.log_shipper", "/x"
        ]
        fake = self._fake_psutil(monkeypatch, lambda _pid: fake_proc)
        # SIGTERM didn't take — wait() raises TimeoutExpired.
        fake_proc.wait.side_effect = fake.TimeoutExpired()

        register._stop_existing_shipper(Console())

        fake_proc.terminate.assert_called_once()
        fake_proc.kill.assert_called_once()
        # PID file still cleaned up after SIGKILL (handler never ran).
        assert not pid_file.exists()

    def test_does_not_kill_unrelated_pid(self, tmp_path, monkeypatch):
        """PID file points at a real but unrelated process (e.g. PID reuse
        after reboot). Cmdline guard must protect it."""
        from unittest.mock import MagicMock
        from lablink_cli.commands import register
        from rich.console import Console

        pid_file = tmp_path / "log_shipper.pid"
        pid_file.write_text("12345")
        monkeypatch.setattr(register, "PID_FILE", pid_file)

        fake_proc = MagicMock()
        fake_proc.cmdline.return_value = ["/usr/bin/vim", "notes.txt"]
        self._fake_psutil(monkeypatch, lambda _pid: fake_proc)

        register._stop_existing_shipper(Console())

        fake_proc.terminate.assert_not_called()
        fake_proc.kill.assert_not_called()
        # Stale PID file dropped so we don't keep skipping forever.
        assert not pid_file.exists()

    def test_stale_pid_removes_file_silently(self, tmp_path, monkeypatch):
        """PID file references a PID that no longer exists."""
        from lablink_cli.commands import register
        from rich.console import Console

        pid_file = tmp_path / "log_shipper.pid"
        pid_file.write_text("99999")
        monkeypatch.setattr(register, "PID_FILE", pid_file)

        fake = self._fake_psutil(monkeypatch, None)
        fake.Process.side_effect = fake.NoSuchProcess()

        register._stop_existing_shipper(Console())

        assert not pid_file.exists()

    def test_corrupt_pid_file_removed(self, tmp_path, monkeypatch):
        from lablink_cli.commands import register
        from rich.console import Console

        pid_file = tmp_path / "log_shipper.pid"
        pid_file.write_text("not-a-number")
        monkeypatch.setattr(register, "PID_FILE", pid_file)

        register._stop_existing_shipper(Console())

        assert not pid_file.exists()


class TestShipperAlive:
    def test_no_pid_file_returns_false(self, tmp_path, monkeypatch):
        from lablink_cli.commands import register

        pid_file = tmp_path / "log_shipper.pid"
        monkeypatch.setattr(register, "PID_FILE", pid_file)

        assert register._shipper_alive() is False

    def test_pid_with_matching_cmdline_returns_true(
        self, tmp_path, monkeypatch
    ):
        from unittest.mock import MagicMock
        from lablink_cli.commands import register

        pid_file = tmp_path / "log_shipper.pid"
        pid_file.write_text("12345")
        monkeypatch.setattr(register, "PID_FILE", pid_file)

        fake_proc = MagicMock()
        fake_proc.cmdline.return_value = [
            "/usr/bin/python", "-m",
            "lablink_cli.log_shipper", "/home/u/.lablink/client.env",
        ]
        fake_psutil = MagicMock()
        fake_psutil.Process.return_value = fake_proc
        fake_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        fake_psutil.AccessDenied = type("AccessDenied", (Exception,), {})
        monkeypatch.setattr(register, "psutil", fake_psutil)

        assert register._shipper_alive() is True

    def test_pid_with_wrong_cmdline_returns_false(
        self, tmp_path, monkeypatch
    ):
        from unittest.mock import MagicMock
        from lablink_cli.commands import register

        pid_file = tmp_path / "log_shipper.pid"
        pid_file.write_text("12345")
        monkeypatch.setattr(register, "PID_FILE", pid_file)

        fake_proc = MagicMock()
        fake_proc.cmdline.return_value = ["/usr/bin/vim"]
        fake_psutil = MagicMock()
        fake_psutil.Process.return_value = fake_proc
        fake_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        fake_psutil.AccessDenied = type("AccessDenied", (Exception,), {})
        monkeypatch.setattr(register, "psutil", fake_psutil)

        assert register._shipper_alive() is False

    def test_dead_pid_returns_false(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock
        from lablink_cli.commands import register

        pid_file = tmp_path / "log_shipper.pid"
        pid_file.write_text("12345")
        monkeypatch.setattr(register, "PID_FILE", pid_file)

        fake_psutil = MagicMock()
        fake_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        fake_psutil.AccessDenied = type("AccessDenied", (Exception,), {})
        fake_psutil.Process.side_effect = fake_psutil.NoSuchProcess()
        monkeypatch.setattr(register, "psutil", fake_psutil)

        assert register._shipper_alive() is False


class TestWriteStartupScript:
    """Covers `_write_startup_script` — decodes the allocator-shipped
    startup script to a host file the docker run can bind-mount.
    """

    def test_writes_decoded_bytes_when_payload_present(self, tmp_path, monkeypatch):
        import base64
        from lablink_cli.commands import register

        target = tmp_path / "client-custom-startup.sh"
        monkeypatch.setattr(register, "DEFAULT_STARTUP_SCRIPT", target)

        payload = b"#!/bin/bash\necho hi\n"
        resp = {"startup_script_b64": base64.b64encode(payload).decode()}
        result = register._write_startup_script(resp)

        assert result == target
        assert target.read_bytes() == payload

    def test_sets_executable_mode(self, tmp_path, monkeypatch):
        """0755 so root-in-container can ``bash`` the file (start.sh also
        chmod +x's it, but the source mode shouldn't be 0600 either —
        keeps `ls -l` and direct host-side debugging meaningful)."""
        import base64
        import stat
        from lablink_cli.commands import register

        target = tmp_path / "client-custom-startup.sh"
        monkeypatch.setattr(register, "DEFAULT_STARTUP_SCRIPT", target)

        resp = {"startup_script_b64": base64.b64encode(b"#!/bin/bash\n").decode()}
        register._write_startup_script(resp)

        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o755

    def test_returns_none_and_removes_stale_when_payload_empty(
        self, tmp_path, monkeypatch
    ):
        """Re-register after the operator disables the script: a previous
        registration left the file at DEFAULT_STARTUP_SCRIPT — must be
        unlinked so we don't silently keep mounting old content. Without
        this cleanup, a `--force` rerun would still bind-mount the prior
        script even though the new register response says "no script"."""
        from lablink_cli.commands import register

        target = tmp_path / "client-custom-startup.sh"
        target.write_text("stale content from a prior register")
        monkeypatch.setattr(register, "DEFAULT_STARTUP_SCRIPT", target)

        result = register._write_startup_script({"startup_script_b64": ""})

        assert result is None
        assert not target.exists()

    def test_returns_none_when_field_absent(self, tmp_path, monkeypatch):
        """Belt-and-suspenders: the allocator always emits the field, but
        if a downstream proxy/transformer drops it, the CLI must treat
        "missing key" the same as "empty payload" rather than KeyError."""
        from lablink_cli.commands import register

        target = tmp_path / "client-custom-startup.sh"
        monkeypatch.setattr(register, "DEFAULT_STARTUP_SCRIPT", target)

        # Response with NO startup_script_b64 key at all.
        assert register._write_startup_script({}) is None
        assert not target.exists()


class TestDockerRunMountsStartupScript:
    """End-to-end shape check via run_register: an enabled startup script
    on the allocator side must produce a docker-run that bind-mounts it
    at /docker_scripts/custom-startup.sh and forwards STARTUP_ON_ERROR.
    This is the actual delivery path the bug fix is closing.
    """

    @patch("lablink_cli.commands.register.subprocess.Popen")
    @patch("lablink_cli.commands.register.subprocess.run")
    @patch("lablink_cli.commands.register.shutil.which")
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_run_register_mounts_script_when_allocator_ships_one(
        self, mock_detect, mock_client_cls, mock_which, mock_subproc_run,
        mock_popen, tmp_env_file, successful_response,
    ):
        import base64

        from lablink_cli.commands.register import run_register

        # Allocator-side response carrying a script and "fail" semantics.
        payload = b"#!/bin/bash\necho hi from startup\n"
        successful_response["startup_script_b64"] = base64.b64encode(payload).decode()
        successful_response["startup_on_error"] = "fail"
        successful_response["startup_max_attempts"] = 5
        successful_response["startup_base_delay_seconds"] = 15
        successful_response["startup_success_check_b64"] = base64.b64encode(
            b"sleap --version"
        ).decode()

        mock_detect.detect_hostname.return_value = "byo-01"
        mock_detect.detect_lan_ip.return_value = "192.168.1.42"
        mock_detect.resolve_machine_identity.return_value = "mid"
        mock_detect.detect_gpu.return_value = (False, None)
        mock_client = MagicMock()
        mock_client.register.return_value = successful_response
        mock_client_cls.return_value = mock_client
        mock_which.return_value = "/usr/bin/docker"
        mock_subproc_run.return_value = MagicMock(returncode=0, stdout="cgroupfs\n")

        run_register(**_kwargs(tmp_env_file))

        all_cmds = [call.args[0] for call in mock_subproc_run.call_args_list]
        run_cmds = [c for c in all_cmds if "run" in c and "--env-file" in c]
        assert run_cmds, f"Expected `docker run` call; got {all_cmds}"
        cmd = run_cmds[0]

        # The mount target inside the container MUST be the same path
        # start.sh:64 reads from — AWS already mounts /docker_scripts/
        # via Terraform/user_data; the BYO path mirrors it so start.sh
        # has a single, provider-independent contract.
        mount_args = [
            cmd[i + 1] for i, v in enumerate(cmd)
            if v == "--mount" and i + 1 < len(cmd)
        ]
        assert mount_args, f"expected --mount in docker run, got {cmd}"
        assert any(
            "dst=/docker_scripts/custom-startup.sh" in m for m in mount_args
        ), f"mount target wrong; mounts={mount_args}"

        # STARTUP_ON_ERROR must be forwarded — start.sh:73 gates fail-vs-
        # continue on this env var. Picked up from the allocator's
        # cfg.startup_script.on_error via the register response so the
        # operator's "fail" choice actually reaches the client.
        env_args = [
            cmd[i + 1] for i, v in enumerate(cmd)
            if v == "-e" and i + 1 < len(cmd)
        ]
        assert "STARTUP_ON_ERROR=fail" in env_args, (
            f"STARTUP_ON_ERROR not forwarded; -e args={env_args}"
        )
        assert "STARTUP_MAX_ATTEMPTS=5" in env_args, (
            f"STARTUP_MAX_ATTEMPTS not forwarded; -e args={env_args}"
        )
        assert "STARTUP_BASE_DELAY_SECONDS=15" in env_args, (
            f"STARTUP_BASE_DELAY_SECONDS not forwarded; -e args={env_args}"
        )
        assert (
            f"STARTUP_SUCCESS_CHECK_B64="
            f"{successful_response['startup_success_check_b64']}"
        ) in env_args, (
            f"STARTUP_SUCCESS_CHECK_B64 not forwarded; -e args={env_args}"
        )

    @patch("lablink_cli.commands.register.subprocess.Popen")
    @patch("lablink_cli.commands.register.subprocess.run")
    @patch("lablink_cli.commands.register.shutil.which")
    @patch("lablink_cli.commands.register.RegistrationClient")
    @patch("lablink_cli.commands.register.byo_detect")
    def test_run_register_skips_mount_when_no_script(
        self, mock_detect, mock_client_cls, mock_which, mock_subproc_run,
        mock_popen, tmp_env_file, successful_response,
    ):
        """Allocator returned empty payload (script disabled) → no
        --mount, no -e STARTUP_ON_ERROR. Docker would refuse the run
        with a missing bind-mount source, so the skip must be on the
        client side, not just "rely on docker to reject"."""
        from lablink_cli.commands.register import run_register

        # Fixture default is already empty — make it explicit for clarity.
        successful_response["startup_script_b64"] = ""

        mock_detect.detect_hostname.return_value = "byo-01"
        mock_detect.detect_lan_ip.return_value = "192.168.1.42"
        mock_detect.resolve_machine_identity.return_value = "mid"
        mock_detect.detect_gpu.return_value = (False, None)
        mock_client = MagicMock()
        mock_client.register.return_value = successful_response
        mock_client_cls.return_value = mock_client
        mock_which.return_value = "/usr/bin/docker"
        mock_subproc_run.return_value = MagicMock(returncode=0, stdout="cgroupfs\n")

        run_register(**_kwargs(tmp_env_file))

        all_cmds = [call.args[0] for call in mock_subproc_run.call_args_list]
        run_cmds = [c for c in all_cmds if "run" in c and "--env-file" in c]
        assert run_cmds, f"Expected `docker run` call; got {all_cmds}"
        cmd = run_cmds[0]

        assert "--mount" not in cmd, (
            f"--mount must not appear when allocator ships no script; got {cmd}"
        )
        env_args = [
            cmd[i + 1] for i, v in enumerate(cmd)
            if v == "-e" and i + 1 < len(cmd)
        ]
        assert not any("STARTUP_ON_ERROR" in a for a in env_args), (
            f"STARTUP_ON_ERROR must not be forwarded when no script; got {env_args}"
        )
        assert not any("STARTUP_MAX_ATTEMPTS" in a for a in env_args), (
            f"STARTUP_MAX_ATTEMPTS must not be forwarded when no script; got {env_args}"
        )
        assert not any("STARTUP_BASE_DELAY_SECONDS" in a for a in env_args), (
            f"STARTUP_BASE_DELAY_SECONDS must not be forwarded when no "
            f"script; got {env_args}"
        )
        assert not any("STARTUP_SUCCESS_CHECK_B64" in a for a in env_args), (
            f"STARTUP_SUCCESS_CHECK_B64 must not be forwarded when no "
            f"script; got {env_args}"
        )

    def test_corrupt_pid_file_returns_false(self, tmp_path, monkeypatch):
        from lablink_cli.commands import register

        pid_file = tmp_path / "log_shipper.pid"
        pid_file.write_text("not-a-number")
        monkeypatch.setattr(register, "PID_FILE", pid_file)

        assert register._shipper_alive() is False


class TestWriteEnvFile:
    """`_write_env_file` must propagate the full register response so the
    client container's start.sh can extract the Tier 1 monitoring block
    (and any future server-shipped settings) from REGISTER_RESPONSE."""

    def _resp_with_monitoring(self):
        return {
            "client_id": 42,
            "client_secret": "s3cret",
            "agent_token": "a",
            "register_token": "r",
            "allocator_url": "https://lablink.example.com",
            "connectivity": "lan_direct",
            "client_image": "ghcr.io/talmolab/lablink-client:0.4.0",
            "startup_script_b64": "",
            "startup_on_error": "continue",
            "monitoring": {
                "enabled": True,
                "subject_window_patterns": [],
                "process_allowlist": [
                    "sleap-train", "sleap-track", "sleap-label",
                ],
                "watch_dir": "/home/client/Desktop",
                "sample_interval_seconds": 2,
                "push_interval_seconds": 60,
            },
        }

    def test_register_response_present_as_single_line(self, tmp_env_file):
        """env-file format is line-oriented: the JSON value must not
        contain a literal newline, or docker --env-file truncates it."""
        import json
        from lablink_cli.commands.register import _write_env_file

        _write_env_file(
            tmp_env_file, "https://lablink.example.com",
            self._resp_with_monitoring(),
        )

        text = tmp_env_file.read_text()
        # Find the REGISTER_RESPONSE line.
        register_lines = [
            line for line in text.splitlines()
            if line.startswith("REGISTER_RESPONSE=")
        ]
        assert len(register_lines) == 1
        value = register_lines[0].removeprefix("REGISTER_RESPONSE=")
        assert "\n" not in value
        # And the value must round-trip back to the original response.
        parsed = json.loads(value)
        assert parsed["monitoring"]["enabled"] is True
        assert parsed["client_secret"] == "s3cret"

    def test_other_env_vars_untouched(self, tmp_env_file):
        """The existing CLIENT_SECRET / VM_NAME / ALLOCATOR_URL lines
        must still be written unchanged."""
        from lablink_cli.commands.register import _write_env_file

        _write_env_file(
            tmp_env_file, "https://lablink.example.com",
            self._resp_with_monitoring(),
        )
        text = tmp_env_file.read_text()
        assert "CLIENT_SECRET=s3cret" in text
        assert "VM_NAME=42" in text
        assert "ALLOCATOR_URL=https://lablink.example.com" in text

    def test_overlay_fields_included_when_given(self, tmp_env_file):
        from lablink_cli.commands.register import _write_env_file

        _write_env_file(
            tmp_env_file, "https://lablink.example.com",
            self._resp_with_monitoring(),
            overlay_hostname="classroom-gpu-3",
            tailscale_authkey="tskey-abc",
        )

        content = tmp_env_file.read_text()
        assert "OVERLAY_HOSTNAME=classroom-gpu-3" in content
        assert "TAILSCALE_AUTHKEY=tskey-abc" in content

    def test_overlay_fields_absent_when_not_given(self, tmp_env_file):
        from lablink_cli.commands.register import _write_env_file

        _write_env_file(
            tmp_env_file, "https://lablink.example.com",
            self._resp_with_monitoring(),
        )

        content = tmp_env_file.read_text()
        assert "OVERLAY_HOSTNAME" not in content
        assert "TAILSCALE_AUTHKEY" not in content

    def test_prefers_caller_url_over_downgraded_response_url(self, tmp_env_file):
        """Regression (P1 review finding): a mesh-overlay/Funnel allocator's
        register response derives allocator_url from Flask's
        request.host_url, which can't detect it arrived over HTTPS behind
        Tailscale Funnel (Funnel adds no X-Forwarded-Proto) and so reports
        an http:// URL even for a registration that just succeeded over
        https://. That URL only 302-redirects under Funnel, which
        downgrades subsequent POSTs to GET — the actual cause of gpu_health/
        heartbeat 405s observed live. The caller's own allocator_url is
        proven reachable (registration just used it) and must win."""
        from lablink_cli.commands.register import _write_env_file

        resp = self._resp_with_monitoring()
        resp["allocator_url"] = "http://lablink-allocator.example.ts.net"

        _write_env_file(
            tmp_env_file,
            "https://lablink-allocator.example.ts.net",
            resp,
        )

        content = tmp_env_file.read_text()
        assert "ALLOCATOR_URL=https://lablink-allocator.example.ts.net" in content
        assert "ALLOCATOR_URL=http://lablink-allocator.example.ts.net" not in content

    def test_falls_back_to_response_url_when_caller_url_empty(self, tmp_env_file):
        """Defensive fallback only — allocator_url is a required str in
        practice, but the response's value still wins if it's ever empty."""
        from lablink_cli.commands.register import _write_env_file

        _write_env_file(
            tmp_env_file, "", self._resp_with_monitoring(),
        )

        content = tmp_env_file.read_text()
        assert "ALLOCATOR_URL=https://lablink.example.com" in content
