"""Unit tests for SSL configuration functionality."""

from lablink_allocator.conf.structured_config import SSLConfig


class TestSSLConfig:
    """Test SSL configuration dataclass."""

    def test_ssl_config_defaults(self):
        """Test SSLConfig default values."""
        config = SSLConfig()
        assert config.provider == "letsencrypt"
        assert config.email == ""
        assert config.staging is False

    def test_ssl_config_custom_values(self):
        """Test SSLConfig with custom values."""
        config = SSLConfig(
            provider="cloudflare",
            email="admin@example.com",
            staging=True,
        )
        assert config.provider == "cloudflare"
        assert config.email == "admin@example.com"
        assert config.staging is True

    def test_ssl_config_letsencrypt_production(self):
        """Test SSLConfig for Let's Encrypt production mode."""
        config = SSLConfig(
            provider="letsencrypt",
            email="admin@example.com",
            staging=False,
        )
        assert config.provider == "letsencrypt"
        assert config.email == "admin@example.com"
        assert config.staging is False

    def test_ssl_config_letsencrypt_staging(self):
        """Test SSLConfig for Let's Encrypt staging mode."""
        config = SSLConfig(
            provider="letsencrypt",
            email="admin@example.com",
            staging=True,
        )
        assert config.provider == "letsencrypt"
        assert config.email == "admin@example.com"
        assert config.staging is True

    def test_ssl_config_no_ssl(self):
        """Test SSLConfig with SSL disabled."""
        config = SSLConfig(
            provider="none",
            email="",
            staging=False,
        )
        assert config.provider == "none"
        assert config.email == ""
        assert config.staging is False
