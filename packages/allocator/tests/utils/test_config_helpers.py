"""Tests for configuration helper functions."""

from dataclasses import dataclass, field


from lablink_allocator.utils.config_helpers import (
    get_allocator_url,
    should_use_dns,
    should_use_https,
)


@dataclass
class MockSSLConfig:
    """Mock SSL configuration."""

    provider: str = "letsencrypt"
    email: str = "test@example.com"
    staging: bool = False


@dataclass
class MockDNSConfig:
    """Mock DNS configuration."""

    enabled: bool = True
    domain: str = "example.com"
    custom_subdomain: str = "test"
    pattern: str = "custom"


@dataclass
class MockConfig:
    """Mock configuration object."""

    ssl: MockSSLConfig = field(default_factory=MockSSLConfig)
    dns: MockDNSConfig = field(default_factory=MockDNSConfig)


class TestGetAllocatorUrl:
    """Test get_allocator_url function."""

    def test_https_production_with_dns(self):
        """Test HTTPS URL with production Let's Encrypt and DNS."""
        cfg = MockConfig(
            ssl=MockSSLConfig(provider="letsencrypt", staging=False),
            dns=MockDNSConfig(
                enabled=True, domain="example.com", custom_subdomain="prod"
            ),
        )
        url, protocol = get_allocator_url(cfg, "1.2.3.4")
        assert url == "https://prod.example.com"
        assert protocol == "https"

    def test_http_staging_with_dns(self):
        """Test HTTP URL with staging Let's Encrypt and DNS."""
        cfg = MockConfig(
            ssl=MockSSLConfig(provider="letsencrypt", staging=True),
            dns=MockDNSConfig(
                enabled=True, domain="example.com", custom_subdomain="test"
            ),
        )
        url, protocol = get_allocator_url(cfg, "1.2.3.4")
        assert url == "http://test.example.com"
        assert protocol == "http"

    def test_http_no_ssl_with_dns(self):
        """Test HTTP URL with no SSL and DNS."""
        cfg = MockConfig(
            ssl=MockSSLConfig(provider="none"),
            dns=MockDNSConfig(
                enabled=True, domain="example.com", custom_subdomain="test"
            ),
        )
        url, protocol = get_allocator_url(cfg, "1.2.3.4")
        assert url == "http://test.example.com"
        assert protocol == "http"

    def test_http_with_ip_only(self):
        """Test HTTP URL with IP address only (no DNS)."""
        cfg = MockConfig(
            ssl=MockSSLConfig(provider="none"), dns=MockDNSConfig(enabled=False)
        )
        url, protocol = get_allocator_url(cfg, "52.40.142.146")
        assert url == "http://52.40.142.146"
        assert protocol == "http"

    def test_https_cloudflare_with_dns(self):
        """Test HTTPS URL with CloudFlare SSL and DNS."""
        cfg = MockConfig(
            ssl=MockSSLConfig(provider="cloudflare"),
            dns=MockDNSConfig(
                enabled=True, domain="example.com", custom_subdomain="prod"
            ),
        )
        url, protocol = get_allocator_url(cfg, "1.2.3.4")
        assert url == "https://prod.example.com"
        assert protocol == "https"

    def test_auto_pattern(self):
        """Test URL with auto DNS pattern."""
        cfg = MockConfig(
            ssl=MockSSLConfig(provider="none"),
            dns=MockDNSConfig(
                enabled=True,
                domain="example.com",
                custom_subdomain="dev",
                pattern="auto",
            ),
        )
        url, protocol = get_allocator_url(cfg, "1.2.3.4")
        assert url == "http://dev.example.com"
        assert protocol == "http"


class TestShouldUseDns:
    """Test should_use_dns function."""

    def test_dns_enabled(self):
        """Test when DNS is enabled."""
        cfg = MockConfig(dns=MockDNSConfig(enabled=True))
        assert should_use_dns(cfg) is True

    def test_dns_disabled(self):
        """Test when DNS is disabled."""
        cfg = MockConfig(dns=MockDNSConfig(enabled=False))
        assert should_use_dns(cfg) is False


class TestShouldUseHttps:
    """Test should_use_https function."""

    def test_letsencrypt_enabled(self):
        """Test when Let's Encrypt is enabled."""
        cfg = MockConfig(ssl=MockSSLConfig(provider="letsencrypt"))
        assert should_use_https(cfg) is True

    def test_cloudflare_enabled(self):
        """Test when CloudFlare is enabled."""
        cfg = MockConfig(ssl=MockSSLConfig(provider="cloudflare"))
        assert should_use_https(cfg) is True

    def test_ssl_disabled(self):
        """Test when SSL is disabled."""
        cfg = MockConfig(ssl=MockSSLConfig(provider="none"))
        assert should_use_https(cfg) is False
