# LabLink Allocator

VM allocation and management service for LabLink.

## Installation

```bash
pip install lablink-allocator
```

## Usage

```bash
lablink-allocator
```

## Configuration

The allocator uses Hydra for structured configuration.

**Key configuration options:**

- `ssl.staging: true` - HTTP only for testing (unlimited deployments)
- `ssl.staging: false` - HTTPS with trusted certificates (production)
- `dns.enabled: true` - Use DNS-based URLs
- `db.password` - Database password (change from default)

See [Configuration Guide](../../docs/configuration.md) for complete reference.

## Documentation

Full documentation at https://talmolab.github.io/lablink/

- [Configuration](../../docs/configuration.md)
- [Troubleshooting](../../docs/troubleshooting.md)
- [Security](../../docs/security.md)
