# DNS Configuration

Giving the allocator a hostname instead of a bare IP, using AWS Route53.

This page covers the **DNS setup around** LabLink — hosted zones, NS delegation,
and which record OpenTofu creates. For the `dns:` and `ssl:` config keys
themselves, their validation rules, and copy-paste config examples, see
[Configuration](configuration.md#dns-options-dns). For diagnosing a deployment
that is already broken, see [Troubleshooting](troubleshooting.md).

DNS is optional. With `dns.enabled: false` the allocator is reachable at its
Elastic IP over HTTP, and none of this page applies.

## The fast path: `lablink setup`

If `dns.enabled: true` and `dns.terraform_managed: true` are already in your
config, `lablink setup` does the Route53 work for you:

```bash
lablink setup
```

It finds or creates a hosted zone for the registrable part of `dns.domain`
(`example.com` for `test.example.com`), writes the resulting `dns.zone_id` back
into your config file, and — if it created the zone — prints the four AWS
nameservers to hand to your registrar.

Your config file is `~/.lablink/config.yaml` for CLI deployments, or
`lablink-infrastructure/config/config.yaml` in a
[lablink-template](https://github.com/talmolab/lablink-template) checkout.

!!! warning "Not for delegated subdomains"
    `lablink setup` always targets the registrable domain, so for
    `test.lablink.example.com` it creates a zone for `example.com` — not
    `lablink.example.com`. If the parent domain is managed somewhere else and
    you only control a subdomain, use the delegated setup below and set
    `zone_id` yourself.

## Delegated subdomain (parent domain managed elsewhere)

The usual situation for a lab: `example.com` lives in Cloudflare or with
university IT, and you want `lablink.example.com` under your own control. Hand
that one subdomain to Route53 with an NS delegation.

**Why bother** — OpenTofu can then create and destroy the allocator's A record
on its own, with no third-party DNS credentials in your deployment, and Let's
Encrypt can validate the domain without anyone touching the parent zone.

**1. Create the subdomain zone in Route53:**

```bash
aws route53 create-hosted-zone \
  --name lablink.example.com \
  --caller-reference "lablink-$(date +%s)"

# Note the zone ID and the four nameservers from the response
aws route53 get-hosted-zone --id <zone-id> \
  --query 'DelegationSet.NameServers'
```

**2. Delegate from the parent zone.** At whoever hosts `example.com`, add four
NS records:

| Field | Value |
|-------|-------|
| Type | `NS` |
| Name | `lablink` |
| Content | the four `awsdns` nameservers from step 1 (one record each) |
| TTL | 300 |

**3. Verify, after 5–15 minutes:**

```bash
dig NS lablink.example.com     # must return the four awsdns nameservers
```

If it still returns the parent's nameservers, the delegation has not taken
effect — see [Troubleshooting](troubleshooting.md) for the NS delegation checks.

**4. Point your config at that zone explicitly:**

```yaml
dns:
  enabled: true
  terraform_managed: true
  domain: "test.lablink.example.com"
  zone_id: "Z0123456789ABCDEFGHIJ"    # the subdomain zone from step 1
```

## Always set `zone_id`

When `zone_id` is empty, OpenTofu looks the zone up by name — and it strips
exactly **one** label off `dns.domain` to guess the zone. So
`test.lablink.example.com` is looked up as `lablink.example.com`, and the deploy
fails outright if that intermediate zone does not exist. Setting `zone_id`
skips the lookup and removes the guess.

```bash
# Find it for an existing zone
aws route53 list-hosted-zones \
  --query "HostedZones[?Name=='lablink.example.com.'].Id" --output text
```

## What OpenTofu creates

With `dns.enabled: true` and `dns.terraform_managed: true`, the template creates
one record in `zone_id`, named `dns.domain`:

| `ssl.provider` | Record |
|----------------|--------|
| `none`, `letsencrypt`, `cloudflare` | `A` record, TTL 300, pointing at the allocator's Elastic IP |
| `acm` | `A` alias record pointing at the ALB (no EIP record is created) |

With `terraform_managed: false` no record is created at all — you are expected
to point the hostname at the allocator yourself, in whatever DNS you use. This
is required for `ssl.provider: "cloudflare"`.

## SSL

`ssl.provider: "letsencrypt"` installs Caddy on the allocator, which requests a
certificate on first boot and renews it automatically. It needs the DNS record
already resolving publicly, and ports 80 and 443 open.

!!! warning "Redeploying the same domain hits the Let's Encrypt rate limit"
    Every deploy requests a fresh certificate, and Let's Encrypt allows only
    **5 duplicate certificates per week** per hostname. Past that, the site
    fails in the browser with `ERR_SSL_PROTOCOL_ERROR` and nothing else says
    why. For repeated test deploys use a fresh subdomain each cycle, or
    `ssl.provider: "none"`.

Certificate problems show up in Caddy's log on the allocator:

```bash
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>
sudo journalctl -u caddy -f
```

The full provider comparison — `none`, `letsencrypt`, `cloudflare`, `acm` —
is in [Configuration](configuration.md#ssl-providers).

## Verifying a deployment

The template repo ships a script that checks DNS, HTTP, and SSL together:

```bash
./scripts/verify-deployment.sh prod            # reads config.yaml + tofu outputs
./scripts/verify-deployment.sh <domain> <ip>   # or pass them explicitly
```

## References

- [Configuration](configuration.md) — every `dns:` and `ssl:` key, with examples
- [Troubleshooting](troubleshooting.md) — records in the wrong zone, NS delegation, SSL not ready
- [AWS Route53 documentation](https://docs.aws.amazon.com/route53/)
- [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https)
