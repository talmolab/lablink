"""Unit tests for DNS configuration functionality."""

from conf.structured_config import DNSConfig
from main import generate_dns_name


class TestDNSConfig:
    """Test DNS configuration dataclass."""

    def test_dns_config_defaults(self):
        """Test DNSConfig default values."""
        config = DNSConfig()
        assert config.enabled is False
        assert config.domain == ""
        assert config.app_name == "lablink"
        assert config.pattern == "auto"
        assert config.custom_subdomain == ""
        assert config.create_zone is False

    def test_dns_config_custom_values(self):
        """Test DNSConfig with custom values."""
        config = DNSConfig(
            enabled=True,
            domain="example.com",
            app_name="myapp",
            pattern="custom",
            custom_subdomain="my.custom.example.com",
            create_zone=True,
        )
        assert config.enabled is True
        assert config.domain == "example.com"
        assert config.app_name == "myapp"
        assert config.pattern == "custom"
        assert config.custom_subdomain == "my.custom.example.com"
        assert config.create_zone is True


class TestGenerateDNSName:
    """Test generate_dns_name function."""

    def test_dns_disabled(self):
        """Test that empty string is returned when DNS is disabled."""
        config = DNSConfig(enabled=False, domain="example.com")
        result = generate_dns_name(config, "prod")
        assert result == ""

    def test_dns_no_domain(self):
        """Test that empty string is returned when domain is empty."""
        config = DNSConfig(enabled=True, domain="")
        result = generate_dns_name(config, "prod")
        assert result == ""

    def test_auto_pattern_prod(self):
        """Test auto pattern for production environment."""
        config = DNSConfig(
            enabled=True, domain="example.com", app_name="lablink", pattern="auto"
        )
        result = generate_dns_name(config, "prod")
        assert result == "lablink.example.com"

    def test_auto_pattern_test(self):
        """Test auto pattern for test environment."""
        config = DNSConfig(
            enabled=True, domain="example.com", app_name="lablink", pattern="auto"
        )
        result = generate_dns_name(config, "test")
        assert result == "test.lablink.example.com"

    def test_auto_pattern_dev(self):
        """Test auto pattern for dev environment."""
        config = DNSConfig(
            enabled=True, domain="example.com", app_name="lablink", pattern="auto"
        )
        result = generate_dns_name(config, "dev")
        assert result == "dev.lablink.example.com"

    def test_app_only_pattern_prod(self):
        """Test app-only pattern for production."""
        config = DNSConfig(
            enabled=True, domain="example.com", app_name="myapp", pattern="app-only"
        )
        result = generate_dns_name(config, "prod")
        assert result == "myapp.example.com"

    def test_app_only_pattern_test(self):
        """Test app-only pattern for test (should be same as prod)."""
        config = DNSConfig(
            enabled=True, domain="example.com", app_name="myapp", pattern="app-only"
        )
        result = generate_dns_name(config, "test")
        assert result == "myapp.example.com"

    def test_custom_pattern_with_subdomain(self):
        """Test custom pattern with valid custom subdomain."""
        config = DNSConfig(
            enabled=True,
            domain="example.com",
            pattern="custom",
            custom_subdomain="my.custom.example.com",
        )
        result = generate_dns_name(config, "prod")
        assert result == "my.custom.example.com"

    def test_custom_pattern_without_subdomain(self):
        """Test custom pattern with empty custom subdomain."""
        config = DNSConfig(
            enabled=True, domain="example.com", pattern="custom", custom_subdomain=""
        )
        result = generate_dns_name(config, "prod")
        assert result == ""

    def test_invalid_pattern(self):
        """Test that invalid pattern returns empty string."""
        config = DNSConfig(
            enabled=True, domain="example.com", pattern="invalid_pattern"
        )
        result = generate_dns_name(config, "prod")
        assert result == ""

    def test_talmo_lab_production_config(self):
        """Test Talmo Lab's actual production DNS configuration."""
        config = DNSConfig(
            enabled=True, domain="sleap.ai", app_name="lablink", pattern="auto"
        )
        result = generate_dns_name(config, "prod")
        assert result == "lablink.sleap.ai"

    def test_talmo_lab_test_config(self):
        """Test Talmo Lab's actual test DNS configuration."""
        config = DNSConfig(
            enabled=True, domain="sleap.ai", app_name="lablink", pattern="auto"
        )
        result = generate_dns_name(config, "test")
        assert result == "test.lablink.sleap.ai"

    def test_talmo_lab_dev_config(self):
        """Test Talmo Lab's actual dev DNS configuration."""
        config = DNSConfig(
            enabled=True, domain="sleap.ai", app_name="lablink", pattern="auto"
        )
        result = generate_dns_name(config, "dev")
        assert result == "dev.lablink.sleap.ai"
