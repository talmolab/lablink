# Deployment Verification Script

## Overview

The `verify-deployment.sh` script automates the verification of a LabLink deployment by checking:

1. **DNS Resolution** (if domain provided) - Verifies DNS propagates to public resolvers
2. **HTTP Connectivity** - Tests HTTP access to the allocator
3. **HTTPS/SSL** (if configured) - Verifies SSL certificate acquisition and HTTPS access

The script adapts based on your deployment configuration:
- **DNS disabled**: Skips DNS checks, tests IP directly
- **SSL = "none"**: Skips HTTPS checks
- **SSL = "cloudflare"**: Skips Let's Encrypt verification
- **SSL = "letsencrypt"**: Full HTTPS/SSL verification

## Requirements

- Standard Unix tools: `curl`, `nslookup`, `openssl`
- Bash shell (Linux, macOS, WSL, Git Bash)
- AWS CLI (optional, only for Route53 checks)

## Usage

### Basic Usage

```bash
./verify-deployment.sh <domain-name> <expected-ip>
```

### Examples

```bash
# Verify with domain and IP
./verify-deployment.sh test.lablink.sleap.ai 52.10.119.234

# IP-only deployment (no DNS)
./verify-deployment.sh "" 52.10.119.234
```

### Getting the Values

After deploying with Terraform, get the values from the outputs:

```bash
# Get the domain name and IP
DOMAIN=$(terraform output -raw allocator_fqdn)
IP=$(terraform output -raw ec2_public_ip)

# Run verification
./verify-deployment.sh "$DOMAIN" "$IP"
```

Or combine them:

```bash
./verify-deployment.sh \
  $(terraform output -raw allocator_fqdn) \
  $(terraform output -raw ec2_public_ip)
```

## What the Script Does

### Step 1: DNS Resolution (Conditional)

**When domain is provided:**
- Waits for DNS propagation to Google DNS (8.8.8.8)
- Max wait: 5 minutes
- Check interval: 10 seconds

**Output (in progress):**
```
[1/3] Verifying DNS resolution...
  Waiting for DNS propagation...
  Elapsed: 30s / 300s (resolved: NXDOMAIN)
```

**Output (success):**
```
✓ DNS propagated successfully
  test.lablink.sleap.ai → 52.10.119.234
```

**When domain is NOT provided (IP-only):**
```
[1/3] Skipping DNS verification (IP-only deployment)
```

### Step 2: HTTP Connectivity (Always)

Tests HTTP access to the allocator.

**For domain-based deployments:**
```
[2/3] Verifying HTTP connectivity...
  Waiting for allocator container to start (60s)...
  Testing: http://test.lablink.sleap.ai
✓ HTTP responding (status 308)
```

**For IP-only deployments:**
```
[2/3] Verifying HTTP connectivity...
  Waiting for allocator container to start (60s)...
  Testing: http://52.10.119.234:5000
✓ HTTP responding (status 200)
```

- **Max wait**: 2 minutes after initial 60s container startup
- **Check interval**: 10 seconds
- **Accepted status codes**: 200, 301, 308 (redirect to HTTPS)

### Step 3: HTTPS and SSL (Conditional)

**When SSL = "letsencrypt" and domain exists:**

Verifies HTTPS access and SSL certificate acquisition.

```
[3/3] Verifying HTTPS and SSL certificate...
  Waiting for Let's Encrypt certificate acquisition...
✓ HTTPS responding (status 200)
✓ SSL certificate obtained:
  issuer=C = US, O = Let's Encrypt, CN = R10
  notBefore=Oct  4 20:30:00 2025 GMT
  notAfter=Jan  2 20:29:59 2026 GMT
```

- **Max wait**: 3 minutes
- **Check interval**: 10 seconds

**When SSL = "cloudflare":**
```
[3/3] Skipping SSL verification (CloudFlare handles SSL)
```

**When SSL = "none":**
```
[3/3] Skipping SSL verification (SSL disabled)
```

**When no domain configured:**
```
[3/3] Skipping SSL verification (no domain configured)
```

### Final Summary

```
================================
Verification Summary
================================

✓ Deployment verification complete!

Access your allocator at:
  HTTP:  http://test.lablink.sleap.ai
  HTTPS: https://test.lablink.sleap.ai

Admin dashboard:
  https://test.lablink.sleap.ai/admin
```

**IP-only deployment summary:**
```
Access your allocator at:
  HTTP:  http://52.10.119.234:5000

Admin dashboard:
  http://52.10.119.234:5000/admin
```

## Exit Codes

- **0**: All checks passed successfully
- **1**: Critical check failed (HTTP not responding)

Note: DNS and SSL warnings don't cause script failure, as they may take time to propagate.

## Common Issues

### DNS Propagation Delayed

**Warning:**
```
⚠ DNS propagation delayed after 300s
  This may be normal for newly created DNS records
  Try: nslookup test.lablink.sleap.ai
```

**Solution:**
- DNS propagation can take longer than 5 minutes
- The record exists in Route53 and may work for you already
- Try accessing the site directly via your browser
- Re-run the script after 10-15 minutes

### SSL Certificate Not Ready

**Warning:**
```
⚠ SSL certificate not yet available
  Caddy may still be acquiring the certificate
  Check logs: ssh ubuntu@52.10.119.234 sudo journalctl -u caddy -f
```

**Solution:**
- Caddy is still requesting the certificate from Let's Encrypt
- This typically happens when DNS hasn't fully propagated yet
- SSH into the instance and check Caddy logs:
  ```bash
  ssh -i ~/lablink-key.pem ubuntu@<instance-ip>
  sudo journalctl -u caddy -f
  ```
- Caddy will automatically retry every 2 minutes

### Allocator Not Responding

**Error:**
```
✗ Allocator not responding via HTTP
  Check logs: ssh ubuntu@52.10.119.234 sudo docker logs $(sudo docker ps -q)
```

**Solution:**
- SSH into the instance and check Docker logs:
  ```bash
  ssh -i ~/lablink-key.pem ubuntu@<instance-ip>
  sudo docker logs $(sudo docker ps -q)
  ```
- Common issues:
  - Container still starting (wait another 30-60 seconds)
  - Configuration error (check logs for errors)
  - Database not ready (PostgreSQL may need restart)

## Integration with CI/CD

The verification script is integrated into the deployment workflow at `.github/workflows/lablink-allocator-terraform.yml`:

```yaml
- name: Verify Service Health
  run: |
    cd lablink-infrastructure

    FQDN=$(terraform output -raw allocator_fqdn 2>/dev/null || echo "")
    PUBLIC_IP=$(terraform output -raw ec2_public_ip)

    # Read SSL config
    SSL_PROVIDER=$(grep -A5 "^ssl:" config/config.yaml | grep "provider:" | awk '{print $2}' | tr -d '"' || echo "letsencrypt")

    # Wait for container startup
    sleep 60

    # Test HTTP
    # Test HTTPS (if enabled)
```

## Troubleshooting

### Enable Verbose Output

For debugging, you can run with verbose mode:

```bash
# See all commands
bash -x ./verify-deployment.sh test.lablink.sleap.ai 52.10.119.234
```

### Manual DNS Checks

If the script fails, you can manually check DNS:

```bash
# Check Google DNS
nslookup test.lablink.sleap.ai 8.8.8.8

# Check local DNS
nslookup test.lablink.sleap.ai

# Check with dig
dig test.lablink.sleap.ai @8.8.8.8
dig test.lablink.sleap.ai @1.1.1.1
```

### Manual HTTP/HTTPS Checks

```bash
# Test HTTP
curl -v http://test.lablink.sleap.ai

# Test HTTPS
curl -v https://test.lablink.sleap.ai

# Test via IP (for IP-only deployments)
curl -v http://52.10.119.234:5000
```

### Check SSL Certificate

```bash
# Get certificate details
echo | openssl s_client -servername test.lablink.sleap.ai -connect test.lablink.sleap.ai:443 2>/dev/null | openssl x509 -noout -text

# Check certificate issuer and dates
echo | openssl s_client -servername test.lablink.sleap.ai -connect test.lablink.sleap.ai:443 2>/dev/null | openssl x509 -noout -issuer -dates
```

## Customization

### Adjust Timeouts

Edit the script to modify wait times:

```bash
# DNS propagation timeout (line ~54)
MAX_WAIT=300  # Change to 600 for 10 minutes

# HTTP timeout (line ~109)
MAX_WAIT=120  # Change to 180 for 3 minutes

# SSL certificate timeout (line ~147)
MAX_WAIT=180  # Change to 300 for 5 minutes
```

### Configure SSL Provider

The script reads the SSL provider from `config/config.yaml`:

```yaml
ssl:
  provider: "letsencrypt"  # Options: letsencrypt, cloudflare, none
  email: "admin@example.com"
```

## See Also

- [Infrastructure Deployment Guide](../docs/infrastructure.md)
- [DNS Configuration Guide](../docs/dns.md)
- [Terraform Outputs Reference](../docs/terraform-outputs.md)
