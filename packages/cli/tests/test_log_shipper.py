"""Tests for lablink_cli.log_shipper."""

from __future__ import annotations

import json

import pytest


class TestLoadEnv:
    def test_parses_key_value_lines(self, tmp_path):
        from lablink_cli.log_shipper import load_env

        env_file = tmp_path / "client.env"
        env_file.write_text(
            "# Comment line\n"
            "CLIENT_ID=42\n"
            "VM_NAME=42\n"
            "CLIENT_SECRET=s3cr3t\n"
            "ALLOCATOR_URL=https://lablink.example.com\n"
            "\n"
        )

        env = load_env(env_file)

        assert env["CLIENT_ID"] == "42"
        assert env["VM_NAME"] == "42"
        assert env["CLIENT_SECRET"] == "s3cr3t"
        assert env["ALLOCATOR_URL"] == "https://lablink.example.com"
        assert "# Comment line" not in env

    def test_missing_file_raises(self, tmp_path):
        from lablink_cli.log_shipper import load_env

        with pytest.raises(FileNotFoundError):
            load_env(tmp_path / "nope.env")

    def test_value_with_equals_sign_preserved(self, tmp_path):
        from lablink_cli.log_shipper import load_env

        env_file = tmp_path / "client.env"
        env_file.write_text("WEIRD=a=b=c\n")

        assert load_env(env_file)["WEIRD"] == "a=b=c"


class TestStateFile:
    def test_read_missing_returns_none(self, tmp_path):
        from lablink_cli.log_shipper import read_last_shipped_ts

        assert read_last_shipped_ts(tmp_path / "missing.state") is None

    def test_round_trip(self, tmp_path):
        from lablink_cli.log_shipper import (
            read_last_shipped_ts,
            write_last_shipped_ts,
        )

        state = tmp_path / "log_shipper.state"
        write_last_shipped_ts(state, "2026-05-28T14:23:01Z")

        assert read_last_shipped_ts(state) == "2026-05-28T14:23:01Z"

    def test_corrupt_state_returns_none(self, tmp_path):
        from lablink_cli.log_shipper import read_last_shipped_ts

        state = tmp_path / "bad.state"
        state.write_text("{not json")

        assert read_last_shipped_ts(state) is None

    def test_state_dir_created(self, tmp_path):
        from lablink_cli.log_shipper import write_last_shipped_ts

        nested = tmp_path / "subdir" / "log_shipper.state"
        write_last_shipped_ts(nested, "2026-05-28T14:23:01Z")

        assert nested.exists()


class TestPostBatch:
    def _args(self, **overrides):
        base = dict(
            allocator_url="https://lablink.example.com",
            vm_name="42",
            client_secret="s3cr3t",
            messages=["[start] booting", "[agent] ready"],
        )
        base.update(overrides)
        return base

    def test_success_returns_ok(self):
        from unittest.mock import MagicMock
        from lablink_cli.log_shipper import post_batch

        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        resp.status = 200
        resp.read.return_value = b'{"ok": true}'
        urlopen = MagicMock(return_value=resp)
        sleep = MagicMock()

        result = post_batch(**self._args(), urlopen=urlopen, sleep=sleep)

        assert result == "ok"
        assert urlopen.call_count == 1
        sleep.assert_not_called()
        # verify request shape
        req = urlopen.call_args.args[0]
        assert req.full_url == "https://lablink.example.com/api/vm-logs/42"
        assert req.get_method() == "POST"
        assert req.get_header("Authorization") == "Bearer s3cr3t"
        assert req.get_header("Content-type") == "application/json"
        body = json.loads(req.data.decode())
        assert body == {
            "log_group": "docker",
            "messages": ["[start] booting", "[agent] ready"],
        }

    def test_retries_on_5xx_then_succeeds(self):
        from io import BytesIO
        from unittest.mock import MagicMock
        from urllib.error import HTTPError
        from lablink_cli.log_shipper import post_batch

        ok_resp = MagicMock()
        ok_resp.__enter__.return_value = ok_resp
        ok_resp.__exit__.return_value = False
        ok_resp.status = 200

        urlopen = MagicMock(
            side_effect=[
                HTTPError("u", 503, "boom", {}, BytesIO(b"")),
                HTTPError("u", 503, "boom", {}, BytesIO(b"")),
                ok_resp,
            ]
        )
        sleep = MagicMock()

        result = post_batch(**self._args(), urlopen=urlopen, sleep=sleep)

        assert result == "ok"
        assert urlopen.call_count == 3
        # backoffs: 1s before retry 1, 2s before retry 2
        sleep.assert_any_call(1)
        sleep.assert_any_call(2)

    def test_drops_on_3_consecutive_5xx(self):
        from io import BytesIO
        from unittest.mock import MagicMock
        from urllib.error import HTTPError
        from lablink_cli.log_shipper import post_batch

        urlopen = MagicMock(
            side_effect=HTTPError("u", 503, "boom", {}, BytesIO(b""))
        )
        sleep = MagicMock()

        result = post_batch(**self._args(), urlopen=urlopen, sleep=sleep)

        assert result == "drop"
        assert urlopen.call_count == 3  # initial + 2 retries

    def test_drops_on_network_errors(self):
        from unittest.mock import MagicMock
        from urllib.error import URLError
        from lablink_cli.log_shipper import post_batch

        urlopen = MagicMock(side_effect=URLError("connection refused"))
        sleep = MagicMock()

        result = post_batch(**self._args(), urlopen=urlopen, sleep=sleep)

        assert result == "drop"
        assert urlopen.call_count == 3

    def test_fatal_on_401(self):
        from io import BytesIO
        from unittest.mock import MagicMock
        from urllib.error import HTTPError
        from lablink_cli.log_shipper import post_batch

        urlopen = MagicMock(
            side_effect=HTTPError("u", 401, "unauthorized", {}, BytesIO(b""))
        )
        sleep = MagicMock()

        result = post_batch(**self._args(), urlopen=urlopen, sleep=sleep)

        assert result == "fatal"
        assert urlopen.call_count == 1  # no retry on 4xx
        sleep.assert_not_called()

    def test_fatal_on_404(self):
        from io import BytesIO
        from unittest.mock import MagicMock
        from urllib.error import HTTPError
        from lablink_cli.log_shipper import post_batch

        urlopen = MagicMock(
            side_effect=HTTPError("u", 404, "not found", {}, BytesIO(b""))
        )
        sleep = MagicMock()

        result = post_batch(**self._args(), urlopen=urlopen, sleep=sleep)

        assert result == "fatal"
        assert urlopen.call_count == 1


class TestShouldFlush:
    def test_empty_buffer_never_flushes(self):
        from lablink_cli.log_shipper import should_flush

        assert should_flush(buffer_len=0, elapsed_s=999) is False

    def test_flushes_at_batch_size(self):
        from lablink_cli.log_shipper import should_flush

        assert should_flush(buffer_len=50, elapsed_s=0) is True
        assert should_flush(buffer_len=49, elapsed_s=0) is False

    def test_flushes_at_time_threshold(self):
        from lablink_cli.log_shipper import should_flush

        assert should_flush(buffer_len=1, elapsed_s=15) is True
        assert should_flush(buffer_len=1, elapsed_s=14.9) is False


class TestInspectContainer:
    def test_running(self):
        from unittest.mock import MagicMock, patch
        from lablink_cli.log_shipper import inspect_container

        with patch("lablink_cli.log_shipper.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="running\n", stderr=""
            )
            assert inspect_container("lablink-client") == "running"

    def test_exited(self):
        from unittest.mock import MagicMock, patch
        from lablink_cli.log_shipper import inspect_container

        with patch("lablink_cli.log_shipper.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="exited\n", stderr=""
            )
            assert inspect_container("lablink-client") == "exited"

    def test_restarting(self):
        from unittest.mock import MagicMock, patch
        from lablink_cli.log_shipper import inspect_container

        with patch("lablink_cli.log_shipper.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="restarting\n", stderr=""
            )
            assert inspect_container("lablink-client") == "restarting"

    def test_missing_returns_missing(self):
        from unittest.mock import MagicMock, patch
        from lablink_cli.log_shipper import inspect_container

        with patch("lablink_cli.log_shipper.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Error: No such object: lablink-client\n",
            )
            assert inspect_container("lablink-client") == "missing"

    def test_daemon_error(self):
        from unittest.mock import MagicMock, patch
        from lablink_cli.log_shipper import inspect_container

        with patch("lablink_cli.log_shipper.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Cannot connect to the Docker daemon\n",
            )
            assert inspect_container("lablink-client") == "daemon_error"


class TestParseDockerLine:
    def test_strips_nanoseconds(self):
        from lablink_cli.log_shipper import parse_docker_line

        ts, msg = parse_docker_line(
            "2026-05-28T14:23:01.123456789Z [agent] hello world"
        )
        assert ts == "2026-05-28T14:23:01Z"
        assert msg == "[agent] hello world"

    def test_whole_seconds_passthrough(self):
        from lablink_cli.log_shipper import parse_docker_line

        ts, msg = parse_docker_line("2026-05-28T14:23:01Z [start] boot")
        assert ts == "2026-05-28T14:23:01Z"
        assert msg == "[start] boot"

    def test_no_timestamp_returns_none_ts(self):
        from lablink_cli.log_shipper import parse_docker_line

        ts, msg = parse_docker_line("no timestamp here")
        assert ts is None
        assert msg == "no timestamp here"


class TestOpenDockerLogs:
    def test_builds_command_with_since(self):
        from unittest.mock import MagicMock, patch
        from lablink_cli.log_shipper import open_docker_logs

        with patch("lablink_cli.log_shipper.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            open_docker_logs("lablink-client", since="2026-05-28T14:00:00Z")

        cmd = mock_popen.call_args.args[0]
        assert cmd[:3] == ["docker", "logs", "--follow"]
        assert "--timestamps" in cmd
        assert "--since" in cmd
        assert "2026-05-28T14:00:00Z" in cmd
        assert "lablink-client" in cmd

    def test_omits_since_when_none(self):
        from unittest.mock import MagicMock, patch
        from lablink_cli.log_shipper import open_docker_logs

        with patch("lablink_cli.log_shipper.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            open_docker_logs("lablink-client", since=None)

        cmd = mock_popen.call_args.args[0]
        assert "--since" not in cmd


class TestSelfLog:
    def test_appends_line(self, tmp_path):
        from lablink_cli.log_shipper import self_log

        log = tmp_path / "log_shipper.log"
        self_log(log, "first")
        self_log(log, "second")

        content = log.read_text()
        assert "first" in content
        assert "second" in content
        # one line per call
        assert content.count("\n") == 2

    def test_rotates_at_size_cap(self, tmp_path):
        from lablink_cli.log_shipper import self_log

        log = tmp_path / "log_shipper.log"
        # Pre-fill above cap
        log.write_text("x" * 1_100_000)

        self_log(log, "new line")

        rotated = tmp_path / "log_shipper.log.1"
        assert rotated.exists()
        assert log.read_text().rstrip().endswith("new line")
        # the rotated file holds the old content
        assert len(rotated.read_text()) >= 1_000_000


class TestRunShipper:
    def _env(self, tmp_path):
        env_file = tmp_path / "client.env"
        env_file.write_text(
            "CLIENT_ID=42\n"
            "VM_NAME=42\n"
            "CLIENT_SECRET=s3cr3t\n"
            "ALLOCATOR_URL=https://lablink.example.com\n"
        )
        return env_file

    def test_flushes_full_batch_then_exits_on_missing_container(
        self, tmp_path, monkeypatch
    ):
        from unittest.mock import MagicMock
        from lablink_cli.log_shipper import run_shipper

        env_file = self._env(tmp_path)

        # 50 lines → triggers batch flush
        lines = [
            f"2026-05-28T14:23:{i:02d}Z [start] line-{i}" for i in range(50)
        ]
        post_calls = []

        def fake_post_batch(**kw):
            post_calls.append(kw)
            return "ok"

        def fake_iter():
            yield from lines

        monkeypatch.setattr(
            "lablink_cli.log_shipper.post_batch", fake_post_batch
        )
        monkeypatch.setattr(
            "lablink_cli.log_shipper.inspect_container",
            MagicMock(return_value="missing"),
        )
        # state_dir override so tests don't touch ~/.lablink
        monkeypatch.setattr(
            "lablink_cli.log_shipper.STATE_FILE",
            tmp_path / "log_shipper.state",
        )
        monkeypatch.setattr(
            "lablink_cli.log_shipper.SELF_LOG_FILE",
            tmp_path / "log_shipper.log",
        )

        run_shipper(env_file, _line_iter=fake_iter, _sleep=lambda s: None)

        assert len(post_calls) == 1
        assert len(post_calls[0]["messages"]) == 50
        # state updated with the timestamp of the last line in the batch
        state = (tmp_path / "log_shipper.state").read_text()
        assert "2026-05-28T14:23:49Z" in state

    def test_exits_on_fatal_post(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock
        from lablink_cli.log_shipper import run_shipper

        env_file = self._env(tmp_path)

        def fake_iter():
            for i in range(50):
                yield f"2026-05-28T14:23:{i:02d}Z [agent] x"

        monkeypatch.setattr(
            "lablink_cli.log_shipper.post_batch",
            lambda **kw: "fatal",
        )
        inspect = MagicMock(return_value="running")
        monkeypatch.setattr(
            "lablink_cli.log_shipper.inspect_container", inspect
        )
        monkeypatch.setattr(
            "lablink_cli.log_shipper.STATE_FILE",
            tmp_path / "log_shipper.state",
        )
        monkeypatch.setattr(
            "lablink_cli.log_shipper.SELF_LOG_FILE",
            tmp_path / "log_shipper.log",
        )

        run_shipper(env_file, _line_iter=fake_iter, _sleep=lambda s: None)

        log = (tmp_path / "log_shipper.log").read_text()
        assert "fatal" in log.lower() or "exiting" in log.lower()

    def test_resumes_from_last_shipped_ts(
        self, tmp_path, monkeypatch
    ):
        """When a state file exists, the docker logs --since arg matches it."""
        from unittest.mock import MagicMock
        from lablink_cli.log_shipper import run_shipper

        env_file = self._env(tmp_path)
        state_file = tmp_path / "log_shipper.state"
        state_file.write_text('{"last_shipped_ts": "2026-05-28T14:00:00Z"}')

        monkeypatch.setattr(
            "lablink_cli.log_shipper.STATE_FILE", state_file
        )
        monkeypatch.setattr(
            "lablink_cli.log_shipper.SELF_LOG_FILE",
            tmp_path / "log_shipper.log",
        )
        captured_since: list[str | None] = []

        def fake_open_logs(name, *, since):
            captured_since.append(since)
            # Yield no lines, end immediately
            mock = MagicMock()
            mock.stdout = iter([])
            mock.terminate = MagicMock()
            mock.wait = MagicMock()
            return mock

        monkeypatch.setattr(
            "lablink_cli.log_shipper.open_docker_logs", fake_open_logs
        )
        monkeypatch.setattr(
            "lablink_cli.log_shipper.inspect_container",
            MagicMock(return_value="missing"),
        )

        run_shipper(env_file, _sleep=lambda s: None)

        assert captured_since == ["2026-05-28T14:00:00Z"]


class TestMainEntry:
    def test_writes_pid_file_on_start(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock
        from lablink_cli import log_shipper

        env_file = tmp_path / "client.env"
        env_file.write_text(
            "CLIENT_ID=1\nVM_NAME=1\nCLIENT_SECRET=s\n"
            "ALLOCATOR_URL=https://x\n"
        )
        pid_file = tmp_path / "log_shipper.pid"
        monkeypatch.setattr(log_shipper, "PID_FILE", pid_file)
        monkeypatch.setattr(
            log_shipper, "STATE_FILE", tmp_path / "log_shipper.state"
        )
        monkeypatch.setattr(
            log_shipper, "SELF_LOG_FILE", tmp_path / "log_shipper.log"
        )
        monkeypatch.setattr(
            log_shipper, "run_shipper", MagicMock()
        )

        log_shipper.main([str(env_file)])

        # main() should have written the PID and then removed it on exit.
        assert log_shipper.run_shipper.call_count == 1
        # PID file cleaned up after run_shipper returns
        assert not pid_file.exists()

    def test_signal_handler_unlinks_pid_file(
        self, tmp_path, monkeypatch
    ):
        import signal
        from lablink_cli import log_shipper

        pid_file = tmp_path / "log_shipper.pid"
        pid_file.write_text("12345")
        monkeypatch.setattr(log_shipper, "PID_FILE", pid_file)
        monkeypatch.setattr(
            log_shipper, "SELF_LOG_FILE", tmp_path / "log_shipper.log"
        )

        with pytest.raises(SystemExit) as exc:
            log_shipper._handle_shutdown(signal.SIGTERM, None)

        assert exc.value.code == 0
        assert not pid_file.exists()
