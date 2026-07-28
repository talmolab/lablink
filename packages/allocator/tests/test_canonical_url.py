"""Tests for the canonical allocator-URL override (issue #396).

Behind Tailscale Funnel the allocator cannot determine its own public URL from
the request: manual deployments run ssl.provider='none', so the ProxyFix gate
that would trust X-Forwarded-Proto stays shut — and Funnel injects no such
header anyway. request.host_url therefore reports http://, and a client that
believes it gets only a 302 from Funnel, which downgrades its POSTs to GET
(surfacing as 405s on heartbeat/gpu_health).

The fix is an out-of-band file, written by `lablink deploy` from
`tailscale funnel status` and bind-mounted next to config.yaml. These tests
cover the allocator half: preferring the file when it is usable, and falling
back to request.host_url in every other case so the AWS/nginx topology is
untouched.
"""

from types import SimpleNamespace

import pytest

from lablink_allocator_service.utils.config_helpers import (
    CANONICAL_URL_FILENAME,
    canonical_base_url,
)


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    return tmp_path


def _request(host_url="http://10.0.0.5/"):
    return SimpleNamespace(host_url=host_url)


def _write(config_dir, content):
    (config_dir / CANONICAL_URL_FILENAME).write_text(content)


class TestCanonicalBaseUrl:
    def test_prefers_file_over_request_host(self, config_dir):
        _write(config_dir, "https://lablink-allocator-lab.tailnet.ts.net\n")
        assert (
            canonical_base_url(_request())
            == "https://lablink-allocator-lab.tailnet.ts.net"
        )

    def test_strips_trailing_slash_and_whitespace(self, config_dir):
        _write(config_dir, "  https://foo.tailnet.ts.net/  \n")
        assert canonical_base_url(_request()) == "https://foo.tailnet.ts.net"

    def test_accepts_http_scheme_too(self, config_dir):
        """The file is the operator's declared public URL; it is not the
        allocator's business to insist on https (a plain reverse proxy in front
        is a legitimate topology)."""
        _write(config_dir, "http://lablink.internal:8080")
        assert canonical_base_url(_request()) == "http://lablink.internal:8080"

    def test_falls_back_when_file_missing(self, config_dir):
        assert canonical_base_url(_request("http://10.0.0.5/")) == "http://10.0.0.5"

    def test_falls_back_when_file_empty(self, config_dir):
        """The non-Funnel case: render_compose_dir always materializes the file
        so the bind mount resolves, but leaves it empty."""
        _write(config_dir, "")
        assert canonical_base_url(_request("http://10.0.0.5/")) == "http://10.0.0.5"

    def test_falls_back_when_file_is_whitespace_only(self, config_dir):
        _write(config_dir, "\n\n  \n")
        assert canonical_base_url(_request("http://10.0.0.5/")) == "http://10.0.0.5"

    def test_falls_back_when_content_is_not_a_url(self, config_dir, caplog):
        _write(config_dir, "lablink-allocator-lab.tailnet.ts.net")  # no scheme
        assert canonical_base_url(_request("http://10.0.0.5/")) == "http://10.0.0.5"
        assert "not an http(s) URL" in caplog.text

    def test_falls_back_when_config_dir_does_not_exist(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "nope"))
        assert canonical_base_url(_request("http://10.0.0.5/")) == "http://10.0.0.5"

    def test_reads_file_per_call_not_cached(self, config_dir):
        """The CLI writes this file *after* `docker compose up` (Funnel can
        only be enabled once the sidecar runs), so a value cached at import
        would never be seen without restarting the allocator."""
        assert canonical_base_url(_request("http://10.0.0.5/")) == "http://10.0.0.5"
        _write(config_dir, "https://later.tailnet.ts.net")
        assert canonical_base_url(_request()) == "https://later.tailnet.ts.net"

    def test_rejects_scheme_lookalike(self, config_dir):
        """Guards against a partial/garbled write being accepted as a URL."""
        _write(config_dir, "https:/typo.tailnet.ts.net")
        assert canonical_base_url(_request("http://10.0.0.5/")) == "http://10.0.0.5"


class TestRegisterResponseUsesCanonicalUrl:
    """The register response's allocator_url is what a BYO client writes into
    client.env as ALLOCATOR_URL, so this is the value that has to be right."""

    def test_register_response_prefers_canonical_url(self, reg_client, config_dir):
        _write(config_dir, "https://lablink-allocator-lab.tailnet.ts.net")
        client, _ = reg_client
        r = client.post(
            "/api/v1/clients/register",
            json={"hostname": "vm-1", "machine_identity": "i-1"},
            headers={"Authorization": "Bearer tk_test_register"},
        )
        assert r.status_code == 200
        assert (
            r.get_json()["allocator_url"]
            == "https://lablink-allocator-lab.tailnet.ts.net"
        )

    def test_canonical_url_beats_spoofed_forwarded_headers(
        self, reg_client, config_dir
    ):
        """The file is operator-supplied and local; a client-supplied
        X-Forwarded-Host must not displace it."""
        _write(config_dir, "https://real.tailnet.ts.net")
        client, _ = reg_client
        r = client.post(
            "/api/v1/clients/register",
            json={"hostname": "vm-1", "machine_identity": "i-1"},
            headers={
                "Authorization": "Bearer tk_test_register",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "evil.example.com",
            },
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body["allocator_url"] == "https://real.tailnet.ts.net"
        assert "evil.example.com" not in body["allocator_url"]

    def test_register_falls_back_without_file(self, reg_client, config_dir):
        """No file → unchanged pre-existing behaviour (the AWS/nginx path)."""
        client, _ = reg_client
        r = client.post(
            "/api/v1/clients/register",
            json={"hostname": "vm-1", "machine_identity": "i-1"},
            headers={"Authorization": "Bearer tk_test_register"},
        )
        assert r.status_code == 200
        assert r.get_json()["allocator_url"].startswith("http://")


class TestByoOnboardingUsesCanonicalUrl:
    """The worse of the two call sites: the admin copy-pastes this URL into
    `lablink client register`, so a wrong scheme here breaks the registration
    POST itself — the CLI-side ALLOCATOR_URL precedence fix can't rescue it,
    because the broken URL *is* the caller's input."""

    def test_page_renders_canonical_url(self, client, admin_headers, config_dir):
        _write(config_dir, "https://lablink-allocator-lab.tailnet.ts.net")
        response = client.get("/admin/byo-onboarding", headers=admin_headers)
        assert response.status_code == 200
        html = response.data.decode()
        assert "https://lablink-allocator-lab.tailnet.ts.net" in html

    def test_page_falls_back_without_file(self, client, admin_headers, config_dir):
        response = client.get("/admin/byo-onboarding", headers=admin_headers)
        assert response.status_code == 200
        assert "--allocator-url" in response.data.decode()
