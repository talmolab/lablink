"""Tests for lablink_cli.manual — facts about a manual deployment."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from lablink_cli import manual


def _cfg(deployment_name="mylab"):
    cfg = MagicMock()
    cfg.deployment_name = deployment_name
    return cfg


# ---- workdir --------------------------------------------------------------

class TestWorkdir:
    def test_under_root_override(self, tmp_path):
        assert manual.workdir(_cfg(), tmp_path) == tmp_path / "mylab"

    def test_defaults_deployment_name(self, tmp_path):
        assert manual.workdir(_cfg(""), tmp_path) == tmp_path / "lablink"

    def test_default_root_is_home_compose_dir(self):
        assert manual.workdir(_cfg()) == (
            Path.home() / ".lablink" / "compose" / "mylab"
        )


# ---- base_url ---------------------------------------------------------------

class TestBaseUrl:
    def test_always_localhost_http(self):
        # Plain http on the published port regardless of cfg — the compose
        # stack has no TLS terminator.
        cfg = _cfg()
        cfg.ssl.provider = "self_signed"
        assert manual.base_url(cfg) == "http://localhost:80"


# ---- public_url -------------------------------------------------------------

class TestPublicUrl:
    def test_reads_canonical_url_file(self, tmp_path):
        (tmp_path / manual.CANONICAL_URL_FILENAME).write_text(
            "https://box.example.ts.net\n"
        )
        assert manual.public_url(tmp_path) == "https://box.example.ts.net"

    def test_none_when_file_missing(self, tmp_path):
        assert manual.public_url(tmp_path) is None

    def test_none_when_content_is_not_a_url(self, tmp_path):
        (tmp_path / manual.CANONICAL_URL_FILENAME).write_text("garbage")
        assert manual.public_url(tmp_path) is None


# ---- admin_credentials ------------------------------------------------------

class TestAdminCredentials:
    def test_uses_cfg_when_present(self, tmp_path):
        cfg = _cfg()
        cfg.app.admin_user = "admin"
        cfg.app.admin_password = "pw123"
        assert manual.admin_credentials(cfg, tmp_path) == ("admin", "pw123")

    def test_falls_back_to_workdir_config(self, tmp_path):
        cfg = _cfg()
        cfg.app.admin_user = ""
        cfg.app.admin_password = ""
        (tmp_path / "config.yaml").write_text(
            yaml.safe_dump(
                {"app": {"admin_user": "op", "admin_password": "fromfile"}}
            )
        )
        assert manual.admin_credentials(cfg, tmp_path) == ("op", "fromfile")

    def test_ignores_missing_sentinel(self, tmp_path):
        cfg = _cfg()
        cfg.app.admin_user = "MISSING"
        cfg.app.admin_password = "MISSING"
        assert manual.admin_credentials(cfg, tmp_path) is None

    def test_returns_none_when_nothing_available(self, tmp_path):
        cfg = _cfg()
        cfg.app.admin_user = ""
        cfg.app.admin_password = ""
        assert manual.admin_credentials(cfg, tmp_path) is None


# ---- registered_clients -------------------------------------------------

class TestRegisteredClients:
    @patch("lablink_cli.manual.urlopen")
    def test_sends_basic_auth_and_returns_clients(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = json.dumps(
            {"clients": [{"hostname": "byo-1"}]}
        ).encode()
        mock_urlopen.return_value = resp

        clients, err = manual.registered_clients(_cfg(), "admin", "pw")
        assert err == ""
        assert clients == [{"hostname": "byo-1"}]
        sent_req = mock_urlopen.call_args[0][0]
        # admin:pw → YWRtaW46cHc=
        assert sent_req.headers["Authorization"] == "Basic YWRtaW46cHc="
        assert sent_req.full_url == "http://localhost:80/api/v1/clients"

    @patch("lablink_cli.manual.urlopen")
    def test_sends_product_user_agent(self, mock_urlopen):
        # urllib's default agent is 403'd by Cloudflare-proxied
        # allocators (see api.USER_AGENT).
        resp = MagicMock()
        resp.read.return_value = b"{}"
        mock_urlopen.return_value = resp
        manual.registered_clients(_cfg(), "admin", "pw")
        sent_req = mock_urlopen.call_args[0][0]
        assert sent_req.headers["User-agent"] == manual.USER_AGENT

    @patch("lablink_cli.manual.urlopen")
    def test_returns_empty_list_when_response_missing_key(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = b"{}"
        mock_urlopen.return_value = resp
        clients, err = manual.registered_clients(_cfg(), "admin", "pw")
        assert clients == []
        assert err == ""

    @patch("lablink_cli.manual.urlopen")
    def test_returns_error_on_http_failure(self, mock_urlopen):
        from email.message import Message
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            "http://localhost:80/api/v1/clients",
            401,
            "Unauthorized",
            Message(),
            io.BytesIO(b""),
        )
        clients, err = manual.registered_clients(_cfg(), "admin", "wrong")
        assert clients is None
        assert "401" in err
        # A bare "HTTP 401" leaves the operator guessing. Name the
        # credentials that were rejected and where they come from.
        assert "admin_user" in err
        assert "admin_password" in err
        # Must name a file that actually exists: the config is
        # ~/.lablink/config.yaml (app.DEFAULT_CONFIG). "lablink.yaml"
        # appears nowhere in the project and sends people hunting.
        assert "config.yaml" in err
        assert "lablink.yaml" not in err

    @patch("lablink_cli.manual.urlopen")
    def test_non_401_http_error_stays_generic(self, mock_urlopen):
        from email.message import Message
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            "http://localhost:80/api/v1/clients",
            500,
            "Server Error",
            Message(),
            io.BytesIO(b""),
        )
        clients, err = manual.registered_clients(_cfg(), "admin", "pw")
        assert clients is None
        assert "500" in err
        # Credential guidance would be misleading here.
        assert "admin_password" not in err

    @patch("lablink_cli.manual.urlopen")
    def test_returns_error_on_url_failure(self, mock_urlopen):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("connection refused")
        clients, err = manual.registered_clients(_cfg(), "admin", "pw")
        assert clients is None
        assert "connection refused" in err
