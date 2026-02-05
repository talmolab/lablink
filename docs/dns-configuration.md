# DNS Configuration Guide

## Overview

LabLink uses AWS Route53 for DNS management with a delegated subdomain structure. This document describes the DNS architecture and configuration for internal reference.

## DNS Architecture

### Domain Structure

- **Parent Domain**: `sleap.ai` (managed in Cloudflare)
- **Delegated Subdomain**: `lablink.sleap.ai` (managed in AWS Route53)
- **Example Deployment**: `test.lablink.sleap.ai` → allocator instance

### Why Delegated Subdomain?

The main `sleap.ai` domain is managed in Cloudflare for the primary website. To avoid conflicts and allow AWS-based automation, we use NS delegation to hand off the `lablink.sleap.ai` subdomain to AWS Route53.

**Benefits**:
- Terraform can manage DNS records automatically
- No Cloudflare API credentials needed
- Separation of concerns (website vs LabLink infrastructure)
- Let's Encrypt can validate domain ownership via DNS

## Route53 Setup

### Hosted Zone Configuration

**Zone Name**: `lablink.sleap.ai`
**Zone ID**: `Z010760118DSWF5IYKMOM`
**Type**: Public hosted zone

**Nameservers** (AWS-assigned):
```
ns-158.awsdns-19.com
ns-697.awsdns-23.net
ns-1839.awsdns-37.co.uk
ns-1029.awsdns-00.org
```

### Cloudflare NS Delegation

In Cloudflare DNS for `sleap.ai`, the following NS records delegate the subdomain to AWS:

**Record Type**: NS
**Name**: `lablink`
**Content** (4 records):
```
ns-158.awsdns-19.com
ns-697.awsdns-23.net
ns-1839.awsdns-37.co.uk
ns-1029.awsdns-00.org
```

**TTL**: Auto (or 300 seconds)

### Verification

```bash
# Query AWS nameservers directly
dig @ns-158.awsdns-19.com lablink.sleap.ai

# Check NS delegation
dig NS lablink.sleap.ai

# Should show AWS nameservers, not Cloudflare
```

## LabLink DNS Configuration

### Configuration File

**Location**: `lablink-infrastructure/config/config.yaml`

```yaml
dns:
  enabled: true
  terraform_managed: true            # true = Terraform manages Route53 records
  domain: "test.lablink.sleap.ai"    # Full domain name for the allocator
  zone_id: "Z010760118DSWF5IYKMOM"   # Optional: Route53 zone ID (skips lookup)
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable DNS-based URLs |
| `terraform_managed` | boolean | `true` | Let Terraform manage Route53 records. Set to `false` for external DNS (CloudFlare, etc.) |
| `domain` | string | `""` | Full domain name (e.g., `lablink.sleap.ai` or `test.lablink.sleap.ai`) |
| `zone_id` | string | `""` | Route53 zone ID (optional, skips lookup if provided) |

### Domain Naming

Specify the full domain name directly in the `domain` field. This supports:

- **Root domain**: `domain: "lablink.sleap.ai"`
- **Environment subdomains**: `domain: "test.lablink.sleap.ai"`
- **Custom subdomains**: `domain: "myapp.lablink.sleap.ai"`

### Zone ID Configuration

**Why hardcode zone_id?**

The Terraform data source `aws_route53_zone` can incorrectly match parent zones when searching by domain name. To ensure the correct zone is always used, we hardcode the zone ID in the config:

```yaml
dns:
  zone_id: "Z010760118DSWF5IYKMOM"  # Forces use of lablink.sleap.ai zone
```

**How to find your zone ID**:
```bash
aws route53 list-hosted-zones --query "HostedZones[?Name=='lablink.sleap.ai.'].Id" --output text
```

## Terraform DNS Management

### Main Configuration

**Location**: `lablink-infrastructure/main.tf`

```hcl
# DNS configuration from config.yaml
locals {
  dns_enabled          = try(local.config_file.dns.enabled, false)
  dns_terraform_managed = try(local.config_file.dns.terraform_managed, true)
  dns_domain           = try(local.config_file.dns.domain, "")
  dns_zone_id          = try(local.config_file.dns.zone_id, "")
}

# Zone selection: use provided zone_id or lookup by domain
locals {
  zone_id = local.dns_enabled && local.dns_terraform_managed ? (
    local.dns_zone_id != "" ? local.dns_zone_id : data.aws_route53_zone.existing[0].zone_id
  ) : ""
}
```

### DNS Record Creation

```hcl
resource "aws_route53_record" "allocator" {
  count   = local.dns_enabled ? 1 : 0
  zone_id = local.zone_id
  name    = local.fqdn
  type    = "A"
  ttl     = 300
  records = [local.allocator_public_ip]
}
```

## SSL/TLS Configuration

### Let's Encrypt Integration

LabLink uses Caddy for automatic SSL certificate acquisition from Let's Encrypt.

**Prerequisites**:
- Valid DNS record pointing to allocator IP
- DNS propagated to public resolvers (Google DNS 8.8.8.8, Cloudflare DNS 1.1.1.1)
- Port 80 and 443 accessible

**Configuration**:
```yaml
ssl:
  provider: "letsencrypt"
  email: "admin@example.com"
```

**Caddy Configuration** (`lablink-infrastructure/user_data.sh`):
```bash
cat > /etc/caddy/Caddyfile <<EOF
${fqdn} {
    reverse_proxy localhost:5000
}
EOF
```

Caddy automatically:
1. Requests certificate from Let's Encrypt
2. Validates domain ownership via HTTP-01 challenge
3. Renews certificates before expiration
4. Redirects HTTP to HTTPS

### SSL Troubleshooting

Check Caddy logs:
```bash
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>
sudo journalctl -u caddy -f
```

Common issues:
- DNS not propagated → Wait 5-10 minutes
- Port 80/443 blocked → Check security group rules
- Invalid domain → Verify DNS record exists

## DNS Troubleshooting

### Issue: Record Created in Wrong Zone

**Symptom**: DNS record appears in `sleap.ai` zone instead of `lablink.sleap.ai` zone

**Cause**: Terraform data source matched parent zone

**Solution**: Add `zone_id` to config.yaml:
```yaml
dns:
  zone_id: "Z010760118DSWF5IYKMOM"
```

### Issue: DNS Not Resolving

**Check DNS propagation**:
```bash
# Check Google DNS
nslookup test.lablink.sleap.ai 8.8.8.8

# Check Cloudflare DNS
nslookup test.lablink.sleap.ai 1.1.1.1

# Check authoritative nameservers
nslookup test.lablink.sleap.ai ns-158.awsdns-19.com
```

**Verify Route53 record**:
```bash
aws route53 list-resource-record-sets \
  --hosted-zone-id Z010760118DSWF5IYKMOM \
  --query "ResourceRecordSets[?Name=='test.lablink.sleap.ai.']"
```

**Check NS delegation**:
```bash
dig NS lablink.sleap.ai
# Should return AWS nameservers, not Cloudflare
```

### Issue: NS Delegation Not Working

**Symptom**: DNS queries return NXDOMAIN even though record exists in Route53

**Cause**: NS records not properly configured in Cloudflare

**Solution**:
1. Log into Cloudflare
2. Go to DNS settings for `sleap.ai`
3. Add/verify NS records for `lablink` pointing to all 4 AWS nameservers
4. Wait 5-15 minutes for propagation

### Issue: Multiple Hosted Zones Conflict

**Symptom**: Both `sleap.ai` and `lablink.sleap.ai` zones exist in Route53

**Solution**: Delete the parent zone from Route53 if it's managed elsewhere (Cloudflare)
```bash
# List zones
aws route53 list-hosted-zones

# Delete parent zone (if managed in Cloudflare)
aws route53 delete-hosted-zone --id <zone-id>
```

## DNS Verification Script

Use the deployment verification script to check DNS:

```bash
cd lablink-infrastructure
./verify-deployment.sh test.lablink.sleap.ai 52.40.142.146
```

This checks:
1. DNS resolution via Google/Cloudflare DNS
2. HTTP connectivity
3. HTTPS/SSL certificate (if enabled)

## Configuration Templates

### Development Environment
```yaml
dns:
  enabled: true
  terraform_managed: true
  domain: "dev.lablink.sleap.ai"
  zone_id: "Z010760118DSWF5IYKMOM"

ssl:
  provider: "letsencrypt"
  email: "dev@example.com"
```

### Test Environment
```yaml
dns:
  enabled: true
  terraform_managed: true
  domain: "test.lablink.sleap.ai"
  zone_id: "Z010760118DSWF5IYKMOM"

ssl:
  provider: "letsencrypt"
  email: "test@example.com"
```

### Production Environment
```yaml
dns:
  enabled: true
  terraform_managed: true
  domain: "lablink.sleap.ai"  # Root domain for production
  zone_id: "Z010760118DSWF5IYKMOM"

ssl:
  provider: "letsencrypt"
  email: "admin@example.com"
```

### External DNS (CloudFlare)
```yaml
dns:
  enabled: true
  terraform_managed: false  # DNS managed externally
  domain: "lablink.example.com"

ssl:
  provider: "cloudflare"  # CloudFlare handles SSL
```

### IP-Only Deployment (No DNS)
```yaml
dns:
  enabled: false

ssl:
  provider: "none"
```

## Best Practices

1. **Always hardcode zone_id** - Prevents zone lookup issues
2. **Use custom pattern** - Explicit control over subdomain names
3. **Verify NS delegation** - Check before first deployment
4. **Wait for DNS propagation** - Allow 5-15 minutes after changes
5. **Test with verification script** - Automate DNS/SSL checks
6. **Document all changes** - Record zone IDs and nameservers

## Security Considerations

### DNS Security
- Route53 hosted zones are public by default
- Use IAM policies to restrict who can modify DNS records
- Enable CloudTrail logging for DNS changes
- Consider DNSSEC for additional security (advanced)

### SSL/TLS Security
- Let's Encrypt certificates are valid for 90 days
- Caddy handles automatic renewal
- Monitor certificate expiration in Caddy logs
- Use strong cipher suites (Caddy defaults are secure)

## Monitoring and Maintenance

### Regular Checks
- Verify DNS records exist in correct zone
- Check SSL certificate expiration
- Monitor Caddy logs for renewal issues
- Review Route53 query metrics

### Backup Information
Keep this information documented:
- Zone ID: `Z010760118DSWF5IYKMOM`
- Nameservers: (listed above)
- Parent domain registrar: Cloudflare
- SSL provider: Let's Encrypt via Caddy

## References

- [AWS Route53 Documentation](https://docs.aws.amazon.com/route53/)
- [Cloudflare DNS Documentation](https://developers.cloudflare.com/dns/)
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [Caddy Documentation](https://caddyserver.com/docs/)
- [LabLink Configuration Guide](configuration.md)
- [LabLink Deployment Guide](deployment.md)
