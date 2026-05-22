"""Tests for lablink_cli.byo_detect — BYO-box auto-detection helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestDetectHostname:
    @patch("lablink_cli.byo_detect.socket.gethostname")
    def test_returns_hostname(self, mock_get):
        from lablink_cli.byo_detect import detect_hostname
        mock_get.return_value = "byo-gpu-01"
        assert detect_hostname() == "byo-gpu-01"

    @patch("lablink_cli.byo_detect.socket.gethostname")
    def test_empty_returns_none(self, mock_get):
        from lablink_cli.byo_detect import detect_hostname
        mock_get.return_value = ""
        assert detect_hostname() is None


class TestDetectLanIp:
    @patch("lablink_cli.byo_detect.socket.socket")
    def test_returns_ip(self, mock_socket_cls):
        from lablink_cli.byo_detect import detect_lan_ip
        sock = MagicMock()
        sock.getsockname.return_value = ("192.168.1.42", 0)
        mock_socket_cls.return_value.__enter__.return_value = sock
        assert detect_lan_ip() == "192.168.1.42"

    @patch("lablink_cli.byo_detect.socket.socket")
    def test_oserror_returns_none(self, mock_socket_cls):
        from lablink_cli.byo_detect import detect_lan_ip
        mock_socket_cls.side_effect = OSError("no route")
        assert detect_lan_ip() is None


class TestDetectMachineIdentity:
    def test_reads_etc_machine_id(self, tmp_path):
        from lablink_cli import byo_detect
        machine_id = tmp_path / "machine-id"
        machine_id.write_text("e3b0c44298fc1c149afbf4c8996fb924\n")
        with patch.object(byo_detect, "_MACHINE_ID_PATHS", [machine_id]):
            assert byo_detect.detect_machine_identity(
                fallback_path=tmp_path / "fallback"
            ) == "e3b0c44298fc1c149afbf4c8996fb924"

    def test_falls_back_to_dbus_machine_id(self, tmp_path):
        from lablink_cli import byo_detect
        primary = tmp_path / "machine-id"  # does not exist
        dbus = tmp_path / "dbus-machine-id"
        dbus.write_text("abc123\n")
        with patch.object(byo_detect, "_MACHINE_ID_PATHS", [primary, dbus]):
            assert byo_detect.detect_machine_identity(
                fallback_path=tmp_path / "fallback"
            ) == "abc123"

    def test_writes_uuid_fallback_if_none_present(self, tmp_path):
        from lablink_cli import byo_detect
        primary = tmp_path / "machine-id"
        dbus = tmp_path / "dbus-machine-id"
        fallback = tmp_path / "fallback"
        with patch.object(byo_detect, "_MACHINE_ID_PATHS", [primary, dbus]):
            value = byo_detect.detect_machine_identity(fallback_path=fallback)
        assert fallback.exists()
        assert fallback.read_text().strip() == value
        assert len(value) >= 32  # UUID without dashes is 32 chars

    def test_reuses_existing_fallback(self, tmp_path):
        from lablink_cli import byo_detect
        primary = tmp_path / "machine-id"
        dbus = tmp_path / "dbus-machine-id"
        fallback = tmp_path / "fallback"
        fallback.write_text("persistent-uuid-value")
        with patch.object(byo_detect, "_MACHINE_ID_PATHS", [primary, dbus]):
            assert byo_detect.detect_machine_identity(
                fallback_path=fallback
            ) == "persistent-uuid-value"


class TestDetectGpu:
    @patch("lablink_cli.byo_detect.shutil.which")
    def test_no_nvidia_smi(self, mock_which):
        from lablink_cli.byo_detect import detect_gpu
        mock_which.return_value = None
        assert detect_gpu() == (False, None)

    @patch("lablink_cli.byo_detect.subprocess.run")
    @patch("lablink_cli.byo_detect.shutil.which")
    def test_parses_nvidia_smi_output(self, mock_which, mock_run):
        from lablink_cli.byo_detect import detect_gpu
        mock_which.return_value = "/usr/bin/nvidia-smi"
        result = MagicMock()
        result.returncode = 0
        result.stdout = "GPU 0: NVIDIA T4 (UUID: GPU-abc...)\n"
        mock_run.return_value = result
        assert detect_gpu() == (True, "NVIDIA T4")

    @patch("lablink_cli.byo_detect.subprocess.run")
    @patch("lablink_cli.byo_detect.shutil.which")
    def test_nonzero_exit(self, mock_which, mock_run):
        from lablink_cli.byo_detect import detect_gpu
        mock_which.return_value = "/usr/bin/nvidia-smi"
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        mock_run.return_value = result
        assert detect_gpu() == (False, None)

    @patch("lablink_cli.byo_detect.subprocess.run")
    @patch("lablink_cli.byo_detect.shutil.which")
    def test_subprocess_oserror(self, mock_which, mock_run):
        from lablink_cli.byo_detect import detect_gpu
        mock_which.return_value = "/usr/bin/nvidia-smi"
        mock_run.side_effect = OSError("boom")
        assert detect_gpu() == (False, None)
