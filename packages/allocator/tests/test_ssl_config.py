"""Unit tests for SSL configuration functionality."""

from lablink_allocator_service.conf.structured_config import SSLConfig


class TestSSLConfig:
    """Test SSL configuration dataclass."""

    def test_ssl_config_defaults(self):
        """Test SSLConfig default values."""
        config = SSLConfig()
        assert config.provider == "letsencrypt"
        assert config.email == ""
        assert config.certificate_arn == ""

    def test_ssl_config_letsencrypt(self):
        """Test SSLConfig for Let's Encrypt."""
        config = SSLConfig(
            provider="letsencrypt",
            email="admin@example.com",
        )
        assert config.provider == "letsencrypt"
        assert config.email == "admin@example.com"
        assert config.certificate_arn == ""

    def test_ssl_config_cloudflare(self):
        """Test SSLConfig for CloudFlare."""
        config = SSLConfig(
            provider="cloudflare",
            email="",
        )
        assert config.provider == "cloudflare"
        assert config.email == ""
        assert config.certificate_arn == ""

    def test_ssl_config_acm(self):
        """Test SSLConfig for AWS Certificate Manager."""
        config = SSLConfig(
            provider="acm",
            email="",
            certificate_arn="arn:aws:acm:us-west-2:123456789012:certificate/abc-123",
        )
        assert config.provider == "acm"
        assert config.email == ""
        assert config.certificate_arn == "arn:aws:acm:us-west-2:123456789012:certificate/abc-123"

    def test_ssl_config_no_ssl(self):
        """Test SSLConfig with SSL disabled."""
        config = SSLConfig(
            provider="none",
            email="",
        )
        assert config.provider == "none"
        assert config.email == ""
        assert config.certificate_arn == ""
