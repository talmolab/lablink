"""Tests for configuration helper functions."""

from dataclasses import dataclass, field


from lablink_allocator_service.utils.config_helpers import (
    get_allocator_url,
    should_use_dns,
    should_use_https,
)


@dataclass
class MockSSLConfig:
    """Mock SSL configuration."""

    provider: str = "letsencrypt"
    email: str = "test@example.com"
    certificate_arn: str = ""


@dataclass
class MockDNSConfig:
    """Mock DNS configuration."""

    enabled: bool = True
    terraform_managed: bool = True
    domain: str = "example.com"
    zone_id: str = ""


@dataclass
class MockConfig:
    """Mock configuration object."""

    ssl: MockSSLConfig = field(default_factory=MockSSLConfig)
    dns: MockDNSConfig = field(default_factory=MockDNSConfig)


class TestGetAllocatorUrl:
    """Test get_allocator_url function."""

    def test_https_production_with_dns(self):
        """Test HTTPS URL with Let's Encrypt."""
        cfg = MockConfig(
            ssl=MockSSLConfig(provider="letsencrypt"),
            dns=MockDNSConfig(enabled=True, domain="prod.example.com"),
        )
        url, protocol = get_allocator_url(cfg, "1.2.3.4")
        assert url == "https://prod.example.com"
        assert protocol == "https"

    def test_http_no_ssl_with_dns(self):
        """Test HTTP URL with no SSL and DNS."""
        cfg = MockConfig(
            ssl=MockSSLConfig(provider="none"),
            dns=MockDNSConfig(enabled=True, domain="test.example.com"),
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
            dns=MockDNSConfig(enabled=True, domain="prod.example.com"),
        )
        url, protocol = get_allocator_url(cfg, "1.2.3.4")
        assert url == "https://prod.example.com"
        assert protocol == "https"

    def test_https_acm_with_dns(self):
        """Test HTTPS URL with ACM SSL and DNS."""
        cfg = MockConfig(
            ssl=MockSSLConfig(
                provider="acm",
                certificate_arn="arn:aws:acm:us-west-2:123456789012:certificate/abc-123",
            ),
            dns=MockDNSConfig(enabled=True, domain="prod.example.com"),
        )
        url, protocol = get_allocator_url(cfg, "1.2.3.4")
        assert url == "https://prod.example.com"
        assert protocol == "https"

    def test_sub_subdomain_support(self):
        """Test URL with sub-subdomain (e.g., test.lablink.sleap.ai)."""
        cfg = MockConfig(
            ssl=MockSSLConfig(provider="none"),
            dns=MockDNSConfig(enabled=True, domain="dev.lablink.example.com"),
        )
        url, protocol = get_allocator_url(cfg, "1.2.3.4")
        assert url == "http://dev.lablink.example.com"
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

    def test_acm_enabled(self):
        """Test when ACM is enabled."""
        cfg = MockConfig(ssl=MockSSLConfig(provider="acm"))
        assert should_use_https(cfg) is True

    def test_ssl_disabled(self):
        """Test when SSL is disabled."""
        cfg = MockConfig(ssl=MockSSLConfig(provider="none"))
        assert should_use_https(cfg) is False
