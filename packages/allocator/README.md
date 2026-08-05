# LabLink Allocator

VM allocation and management service for LabLink.

## Installation

```bash
pip install lablink-allocator-service
```

## Usage

```bash
lablink-allocator
```

## Configuration

The allocator uses Hydra for structured configuration.

**Key configuration options:**

- `provider` - `aws` (EC2 via Terraform) or `manual` (bring-your-own clients that
  register themselves)
- `ssl.provider` - `none` (HTTP only, for testing), `letsencrypt` (Caddy
  auto-HTTPS), `cloudflare`, or `acm`
- `dns.enabled: true` - Use DNS-based URLs
- `db.password` - Database password (change from default)

See [Configuration Guide](../../docs/configuration.md) for complete reference.

## Documentation

Full documentation at https://talmolab.github.io/lablink/

- [Configuration](../../docs/configuration.md)
- [Troubleshooting](../../docs/troubleshooting.md)
- [Security](../../docs/security.md)
