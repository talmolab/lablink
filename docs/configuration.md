# Configuration

LabLink uses structured configuration files to customize behavior. This guide covers all configuration options and how to modify them.

!!! info "Where your `config.yaml` lives"
    Both deployment paths read the same schema, from different places:

    - **CLI** (`lablink deploy`): `~/.lablink/config.yaml`, created and edited by
      `lablink configure`. This is the path the [CLI guide](cli/first-deployment.md) uses.
    - **Template repo** (GitHub Actions): `lablink-infrastructure/config/config.yaml` in a
      [lablink-template](https://github.com/talmolab/lablink-template) checkout.
      `lablink configure --template` writes that one, with `PLACEHOLDER_*` passwords for the
      deploy workflow to substitute from your `ADMIN_PASSWORD` / `DB_PASSWORD` secrets.

## Choosing a Configuration

How you expose the allocator is the one decision that shapes the rest of the file.
Everything else has a working default.

| Scenario | SSL | DNS required | Rate limits | Extra cost |
|----------|-----|--------------|-------------|------------|
| [IP only](#ip-only) | None | No | None | None |
| [Let's Encrypt](#lets-encrypt) | Auto via Caddy | Route53 | 5 certs/domain/week | None |
| [CloudFlare](#cloudflare) | CloudFlare proxy | CloudFlare | None | None |
| [ACM + ALB](#acm-alb) | AWS-managed | Route53 | None | ~$20/month |

Ready-to-use YAML for each is in [Full Configuration Examples](#full-configuration-examples).

## First Steps: Change Default Passwords

!!! danger "Critical Security Step"
    **Before deploying LabLink or creating any VMs, you MUST replace `PLACEHOLDER_ADMIN_PASSWORD` and `PLACEHOLDER_DB_PASSWORD` in your config.** See [Security → Change Default Passwords](security.md#change-default-passwords) for all methods (GitHub Secrets, manual config, environment variables, AWS Secrets Manager).

## Configuration System

Config is a single YAML file, validated against the dataclass schema in
`conf/structured_config.py` via [Hydra](https://hydra.cc/). Unknown keys and wrong
types are rejected at load time rather than surfacing later as a failed deploy.

There are no per-value environment variable or command-line overrides — edit the
file. Two environment variables move the *file itself*: `CONFIG_DIR` (default
`/config`) and `CONFIG_NAME` (default `config.yaml`). If no file is found there,
the allocator falls back to the copy bundled in the package.

## Configuration Files

### Allocator Configuration

**Location**: `~/.lablink/config.yaml` (CLI) or `lablink-infrastructure/config/config.yaml` (template repo)

The file has one required key and ten optional sections:

```yaml
deployment_name: "lablink"   # required — see Deployment Identity below
environment: "prod"
provider: "aws"

db: {...}                    # Postgres password
app: {...}                   # admin credentials, AWS region
machine: {...}               # client VM type, image, AMI, software
dns: {...}                   # hostname for the allocator
eip: {...}                   # Elastic IP strategy
ssl: {...}                   # certificate management
allocator: {...}             # allocator image tag
startup_script: {...}        # optional per-VM setup script
monitoring: {...}            # optional usage telemetry
manual: {...}                # only read when provider: manual
bucket_name: "..."           # S3 bucket for OpenTofu state
```

Every key and its default is documented under
[Configuration Reference](#configuration-reference) below. For a file you can copy
as-is, see [Full Configuration Examples](#full-configuration-examples).

### Client Configuration

**Location**: `packages/client/src/lablink_client_service/conf/config.yaml`

Baked into the client image. Deployments do not normally edit it — the allocator
passes `allocator.host`/`port` and the `machine.software` value to each VM at boot.

```yaml
allocator:
  host: "localhost"
  port: 80

client:
  software: "sleap"

monitoring:      # mirrors the allocator's monitoring block; see below
  enabled: false
```

## Configuration Reference

### Deployment Identity (top-level)

Three top-level keys identify the deployment. They are not nested under a section.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `deployment_name` | string | `""` | **Required.** 3-32 characters, lowercase kebab-case. Prefixes every AWS resource name and scopes the OpenTofu state key (`<deployment_name>/<environment>/…`). |
| `environment` | string | `prod` | One of `dev`, `test`, `ci-test`, `prod`. Suffixes resource names, so the same `deployment_name` can run several environments side by side. |
| `provider` | string | `aws` | `aws` provisions client VMs as EC2 instances via OpenTofu. `manual` provisions nothing — you bring your own client machines and they self-register with `lablink client register`. See [Manual Provider Options](#manual-provider-options-manual). |

Together they produce names like `sleap-lablink-allocator-prod`, so changing either
key points a deploy at a **different** set of resources rather than updating the
existing one.

```yaml
deployment_name: "sleap-lablink"
environment: "prod"
provider: "aws"
```

### Database Options (`db`)

Configuration for the PostgreSQL database. PostgreSQL runs inside the
allocator container with a fixed identity (database `lablink_db`, user
`lablink`, `localhost:5432`) — only the password is configurable.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `password` | string | `lablink` | Database password (override with `PLACEHOLDER_DB_PASSWORD` or GitHub secret) |

!!! warning "Production Security"
    Configure `DB_PASSWORD` secret for GitHub Actions deployments, or manually replace the placeholder. See [Security](security.md#database-password).

### Machine Options (`machine`)

Configuration for client VM specifications. **These are the key options for adapting LabLink to your research software.**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `machine_type` | string | `g4dn.xlarge` | AWS EC2 instance type |
| `image` | string | `ghcr.io/talmolab/lablink-client-base-image:latest` | Docker image for client container |
| `ami_id` | string | `""` | Client VM image. Empty resolves an AWS Deep Learning Base AMI for your region |
| `repository` | string (optional) | `None` | Git repository to clone on VM |
| `software` | string | `sleap` | Software identifier (used by client) |

#### Machine Type Options

Common GPU instance types:

| Instance Type | GPU | vCPUs | Memory | GPU Memory | Use Case |
|---------------|-----|-------|--------|------------|----------|
| `g4dn.xlarge` | NVIDIA T4 | 4 | 16 GB | 16 GB | Light workloads, testing |
| `g4dn.2xlarge` | NVIDIA T4 | 8 | 32 GB | 16 GB | Medium workloads |
| `g5.xlarge` | NVIDIA A10G | 4 | 16 GB | 24 GB | Training, inference |
| `g5.2xlarge` | NVIDIA A10G | 8 | 32 GB | 24 GB | Large models |
| `p3.2xlarge` | NVIDIA V100 | 8 | 61 GB | 16 GB | Deep learning training |

See [AWS Instance Types](https://aws.amazon.com/ec2/instance-types/) for complete list.

#### Docker Image

**Default**: `ghcr.io/talmolab/lablink-client-base-image:latest`

The Docker image determines what software runs on your VMs. Options:

1. **Use default SLEAP image** (for SLEAP workflows)
2. **Build custom image** (for your research software) - see [Adapting LabLink](adapting.md)
3. **Use different tag**:
   - `:latest` - latest stable release
   - `:linux-amd64-test` - development version
   - `:v1.0.0` - specific version

#### AMI ID

**Default**: `""` — resolve an AWS Deep Learning Base AMI (Ubuntu 24.04) for whichever
region the deployment is in. That image carries Docker, the NVIDIA driver and
`nvidia-container-runtime`, all three of which the client boot script requires and none
of which it installs, and AWS publishes it in every region. Leaving this empty is the
way to run in a region LabLink has not published its own image to.

Set it explicitly to use a specific image:

| Region | LabLink's published client AMI |
|--------|-------------------------------|
| `us-west-2` | `ami-0601752c11b394251` |
| `us-east-1` | `ami-0c3412413810adacc` |
| `us-east-2` | `ami-0cd7567480c4840a0` |

LabLink's own image carries less preinstalled software than the Deep Learning AMI, so a
first boot from it should be quicker. The provisioned root volume is 80 GiB either way —
the client terraform pins it — so there is no storage cost difference between the two.
**AMI IDs are region-scoped**: an ID from one region is meaningless in another, and
`lablink doctor` verifies that whatever you set actually exists in `app.region`.

You would also set this explicitly for a custom image with your own software baked in;
it must still provide Docker, the NVIDIA driver and `nvidia-container-runtime`.

**Find AMIs**. This is the same lookup the default performs, so it shows you exactly
which image a given region would get:

```bash
aws ec2 describe-images --region us-west-2 \
  --owners amazon \
  --filters "Name=name,Values=Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04)*" \
  --query 'sort_by(Images, &CreationDate)[-1].[ImageId,Name]' \
  --output text
```

A stock Canonical Ubuntu AMI will **not** work — it has no Docker, NVIDIA driver or
`nvidia-container-runtime`, and the client boot script installs none of them.

#### Repository

**Default**: `None` (no repository cloned)

Git repository to clone onto the client VM. Use this for:

- Custom analysis scripts
- Training data
- Configuration files
- Research code

Set to empty string or omit if no repository needed:
```yaml
repository: ""
```

#### Software Identifier

**Default**: `sleap`

String identifier for the research software. Used by client service for software-specific logic.

### Application Options (`app`)

General application settings.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `admin_user` | string | `MISSING` | Admin username for web UI |
| `admin_password` | string | `MISSING` | Admin password for web UI |
| `region` | string | `us-west-2` | AWS region for deployments |
| `admin_session_timeout_minutes` | integer | `30` | Fixed duration cap for an admin's VNC troubleshooting session on an unassigned VM before it's force-released |

`MISSING` is a sentinel, not a usable credential — the allocator refuses to start if
it is still there at runtime. How it gets filled in depends on the path:

- **CLI**: `lablink configure` never asks for credentials. `lablink deploy` resolves them
  at deploy time from `config.yaml`, then from the previous deployment's rendered config,
  then by prompting you, and writes the result into the deployment's own config.
- **Template repo**: the committed config carries `PLACEHOLDER_ADMIN_PASSWORD` /
  `PLACEHOLDER_DB_PASSWORD`, which the deploy workflow substitutes from your GitHub
  secrets. A `PLACEHOLDER_*` value that reaches a *running* allocator means the
  substitution never happened, and the allocator refuses to start for that too.

!!! danger "Configure Passwords"
    Configure `ADMIN_PASSWORD` secret for GitHub Actions deployments, or manually replace the placeholder. See [Security](security.md#change-default-passwords).

### DNS Options (`dns`)

Controls DNS configuration for allocator hostname.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable DNS-based URLs |
| `terraform_managed` | boolean | `true` | Let OpenTofu manage Route 53 records |
| `domain` | string | `""` | Full domain name (e.g., `lablink.sleap.ai` or `test.lablink.sleap.ai`) |
| `zone_id` | string | `""` | Route 53 zone ID (optional, skips lookup if provided) |

See [DNS Configuration](dns-configuration.md) for detailed setup instructions.

### EIP Options (`eip`)

Controls Elastic IP allocation strategy.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `strategy` | string | `"dynamic"` | `persistent` = reuse tagged EIP, `dynamic` = create new |

### SSL/TLS Options (`ssl`)

Controls HTTPS/SSL certificate management.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `provider` | string | `"letsencrypt"` | SSL provider: `letsencrypt`, `cloudflare`, `acm`, or `none` |
| `email` | string | `""` | Email for Let's Encrypt notifications (required when `provider="letsencrypt"`) |
| `certificate_arn` | string | `""` | AWS ACM certificate ARN (required when `provider="acm"`) |

#### SSL Providers

**`letsencrypt`** - Automatic SSL via Caddy + Let's Encrypt

- HTTPS with trusted certificates
- Automatic HTTP → HTTPS redirects
- Requires `dns.enabled: true` and a valid `ssl.email`
- Rate limited: 5 duplicate certificates per domain per week, 50 certificates per
  registered domain per week, 300 pending authorizations per account

!!! warning "Redeploying the same domain hits the rate limit"
    Every deploy requests a fresh certificate. After 5 deploys of the same
    domain within 7 days, Let's Encrypt refuses issuance and the site fails
    in the browser with `ERR_SSL_PROTOCOL_ERROR` — there is no clearer error
    surfaced anywhere. For repeated test deploys, use a fresh subdomain each
    cycle (e.g. `test2.lablink.example.com`), wait out the 7-day window, or
    use `provider: "none"`.

**`cloudflare`** - CloudFlare proxy handles SSL

- Requires CloudFlare DNS configuration
- Requires `dns.enabled: true` and `dns.terraform_managed: false`

**`acm`** - AWS Certificate Manager

- Uses AWS-managed SSL certificates with an Application Load Balancer
- Requires `dns.enabled: true` and a valid `ssl.certificate_arn`

**`none`** - No SSL, HTTP only

- Serves HTTP only on port 80
- No encryption - all traffic is plaintext
- Browser shows "Not Secure" warning
- Useful for testing and development
- May require clearing browser HSTS cache if you previously accessed via HTTPS (see [Troubleshooting](troubleshooting.md#reaching-the-allocator))
- **Desktop streaming falls back to JPEG/WebP** — the viewer decodes H.264
  with the WebCodecs API, which Chrome only exposes on secure (HTTPS)
  origins. On HTTP the console logs `WebCodecs API not available` and the
  session silently uses JPEG/WebP image mode instead. The desktop still
  works at the full frame rate; only the H.264/NVENC video-streaming mode
  is unavailable. To test H.264 without a certificate, tunnel through
  localhost (a secure context): `ssh -L 8080:localhost:80 <allocator-host>`
  and open `http://localhost:8080` — then retest in an incognito window,
  since the viewer caches its codec-detection result in `localStorage`.

#### SSL Validation Rules

The following rules are enforced during configuration validation:

- SSL `provider` other than `"none"` requires `dns.enabled: true`
- `provider: "letsencrypt"` requires a non-empty `ssl.email`
- `provider: "acm"` requires a non-empty `ssl.certificate_arn`
- `provider: "cloudflare"` requires `dns.terraform_managed: false`

!!! warning "HTTP-only Security"
    `provider: "none"` serves unencrypted HTTP. Never use for production or sensitive data. See [Security](security.md#http-only-deployments-sslprovider-none).

### Allocator Deployment Options (`allocator`)

Configuration for the allocator service Docker image used during infrastructure deployment. This section is consumed by OpenTofu, not by the allocator service itself.

| Option      | Type   | Default                | Description                                 |
|-------------|--------|------------------------|---------------------------------------------|
| `image_tag` | string | `"linux-amd64-latest"` | Docker image tag for the allocator service  |

Example tags:

- `linux-amd64-latest` - latest stable release
- `linux-amd64-latest-test` - development version
- `linux-amd64-v1.2.3` - specific version

### Bucket Name

**Option**: `bucket_name`
**Default**: `tf-state-lablink-allocator-bucket`

S3 bucket for OpenTofu state storage. Must be globally unique.

### Startup Script Options (`startup_script`)

Controls a custom startup script to be run on client VMs after the container starts.

| Option               | Type    | Default    | Description                                                          |
|----------------------|---------|------------|------------------------------------------------------------------------|
| `enabled`            | boolean | `false`    | Enable custom startup script                                         |
| `path`               | string  | `""`       | Path to the startup script file                                      |
| `on_error`           | string  | `continue` | Behavior on script error: `continue` or `fail`                       |
| `max_attempts`       | integer | `3`        | Total attempts to run the script before giving up (`1` = no retry)   |
| `base_delay_seconds` | integer | `30`       | Base delay for exponential backoff between retries (doubles each attempt, plus jitter) |
| `success_check`      | string  | `""`       | Optional shell command run after the script exits `0`, to verify success beyond its own exit code. Empty disables the check. |

**Example:**

```yaml
startup_script:
  enabled: true
  path: "/path/to/install-sleap.sh"
  on_error: "fail"
  max_attempts: 3
  base_delay_seconds: 30
  success_check: "/home/client/.local/bin/sleap --version"
```

When `enabled` is `true`, the content of the script specified by `path` will be executed on the client VM, retried up to `max_attempts` times with exponential backoff if it fails (or if `success_check` is set and fails after the script exits `0`).
- If `on_error` is `continue`, an error on the final attempt is logged, but the VM will continue to run.
- If `on_error` is `fail`, the VM setup will be aborted if the final attempt still returns a non-zero exit code (or fails `success_check`).

**Retries re-run the entire script, not just the failing step** — so the script must be safe to run more than once (e.g. `uv tool install` already is: re-running it when the tool is already installed is a no-op).

**`success_check` runs in a separate shell**, after the script's own process has already exited — it will not see any `PATH`/environment changes the script made only for its own subshell. Reference tools by absolute path, or ensure the script places them somewhere already on the container's `PATH` (e.g. `/usr/local/bin`), not just its own local shell state.

### Monitoring Options (`monitoring`)

Optional **Tier 1 usability telemetry** collected on each client VM and summarised per session in the allocator. **Disabled by default.**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `false` | Master switch. When `false`, no monitoring process runs on the VM. |
| `subject_window_patterns` | list[str] | `[]` (empty) | Lower-cased substrings that mark a focused window as "the tutorial app" (e.g. `["sleap"]`, `["deeplabcut"]`). When empty, falls back to `[client.software]` at runtime — so most deployments don't need to set this. |
| `process_allowlist` | list[str] | `["sleap-train","sleap-track","sleap-label"]` | Process names tracked for time-to-first-invocation. Column names in the DB (`SecondsToFirstSleapLabel/Train/Track`) are static, so a non-SLEAP tutorial will need to interpret those columns by allowlist position. |
| `watch_dir` | string | `/home/client/Desktop` | Directory scanned recursively for `.slp` files and `models/**/training_log.csv` (covers projects inside a cloned tutorial repo). |
| `sample_interval_seconds` | int | `2` | How often each sampler ticks. |
| `push_interval_seconds` | int | `60` | How often the rolling summary is POSTed to the allocator. |

**What is collected.** Window-title buckets (`subject` / `terminal` / `browser` / `other`; raw titles are not stored), GPU utilization and VRAM peaks, allowlisted process names, and numeric parses of `.slp` (labeled frame count) and `training_log.csv` (epochs + final loss).

**What is NOT collected.** Keystrokes, mouse positions, clipboard content, screen pixels, audio, filenames, file contents (other than the numeric parses above), browser URLs, or command-line arguments.

!!! note "Operator note"
    Window titles can leak filenames into the bucketing step. If your participants may consider that sensitive, inform them when enabling.

**Example:**

```yaml
monitoring:
  enabled: true
  subject_window_patterns: []        # empty → derived from client.software
  process_allowlist:
    - sleap-train
    - sleap-track
    - sleap-label
  watch_dir: /home/client/Desktop
  sample_interval_seconds: 2
  push_interval_seconds: 60
```

**Viewing.** With `monitoring.enabled: true`, the admin UI exposes a **Session Metrics** button on the admin landing page; the page shows a cohort summary, funnel, per-VM table, and CSV/JSON download buttons. From the CLI, run `lablink stats` for the same summary in your terminal or `lablink export-metrics --client` to download CSV/JSON.

### Manual Provider Options (`manual`)

Applies only when `provider: manual` (bring-your-own clients, deployed with
`lablink deploy` onto a machine you already have). Ignored by the AWS provider.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `connectivity` | string | `lan_direct` | How a participant's browser reaches a client's KasmVNC desktop: `lan_direct` (client is on the allocator's own LAN), `mesh_overlay` (client is reached over a Tailscale tailnet and proxied through the allocator's nginx), or `reverse_tunnel` (client dials **out** to the allocator and holds one connection open — for networks that won't carry Tailscale and boxes that can't accept inbound connections). |
| `overlay_tailnet` | string | `""` | The tailnet's MagicDNS suffix (e.g. `example.ts.net`). Required for `connectivity: mesh_overlay` and for `participant_exposure: tailscale_funnel`. |
| `participant_exposure` | string | `none` | How **participants** reach the allocator itself: `none` (LAN-only), `tailscale_funnel`, or `cloudflare_tunnel`. Independent of `connectivity`. |
| `public_hostname` | string | `""` | The hostname participants open, e.g. `lab.smithlab.org`. Required when `participant_exposure: cloudflare_tunnel`; ignored otherwise. |

`participant_exposure` is not the same axis as `connectivity`: the first is about
publishing the allocator, the second about reaching clients. What they do constrain
is that any exposure mode other than `none` rules out `connectivity: lan_direct` —
`lan_direct` sends the browser straight to a client's LAN IP over `ws://`, which is
unreachable off-LAN and blocked as mixed content from an HTTPS page. Both
`lablink configure` and `lablink deploy` reject that combination. `mesh_overlay` and
`reverse_tunnel` both work with any exposure mode.

Note that `overlay_tailnet` is required whenever a tailnet is involved on *either*
axis, so a `reverse_tunnel` deployment that publishes itself via
`tailscale_funnel` still needs one; `reverse_tunnel` on its own does not.

#### Manual validation rules

Enforced by both `lablink-validate-config` and the `lablink` CLI:

- `connectivity` must be `lan_direct`, `mesh_overlay` or `reverse_tunnel`
- `participant_exposure` must be `none`, `tailscale_funnel` or `cloudflare_tunnel`
- any `participant_exposure` other than `none` rules out `connectivity: lan_direct`
- `overlay_tailnet` is required for `connectivity: mesh_overlay` or
  `participant_exposure: tailscale_funnel`
- `participant_exposure: cloudflare_tunnel` requires `public_hostname`, and it must be a
  bare FQDN — no scheme, port, path or whitespace. `https://lab.example.org` is rejected
  because it would be interpolated into `https://https://lab.example.org`.
- `participant_exposure: tailscale_funnel` requires an `app.admin_password` that is at
  least 12 characters and not a known example value. A Funnel-published hostname shows up
  in Certificate Transparency logs within minutes and is scanned by bots almost
  immediately, so a weak admin password stops being survivable the moment you publish.

#### Exposure mode: `tailscale_funnel`

Publishes the allocator at `<machine>.<tailnet>.ts.net` using the same Tailscale
sidecar `mesh_overlay` already provisions. No domain required, but the hostname
is not yours to choose — Tailscale Funnel supports no custom domains.

#### Exposure mode: `cloudflare_tunnel`

Publishes the allocator at a hostname you choose, through a Cloudflare Tunnel in
your own Cloudflare account. `cloudflared` ships inside the allocator image and
is started only when this mode is set; LabLink makes no Cloudflare API calls.

!!! warning "Requires a domain whose nameservers point at Cloudflare"
    A custom hostname needs Cloudflare's free-plan **full setup** — the domain's
    nameservers must be delegated to Cloudflare. Cloudflare's partial (CNAME)
    setup is Business-tier and subdomain zones are Enterprise-tier, so an
    institutional domain such as `salk.edu` **cannot** be used on the free plan.
    Register a domain you control instead (typically ~$10/yr), or use
    `tailscale_funnel`, which needs no domain at all.

**One-time setup** (done once per deployment host; the tunnel and its DNS record
live in your Cloudflare account, so the URL is stable across every
`lablink deploy` and `lablink destroy`):

1. Sign up at [cloudflare.com](https://cloudflare.com) (free).
2. **Add a site** → enter your domain → choose the Free plan.
3. At your domain's registrar, replace the nameservers with the two Cloudflare shows.
4. Wait for activation (usually minutes).
5. Open the **Zero Trust** dashboard; pick a team name and the Free plan.
6. **Networks → Tunnels → Create a tunnel** → connector `cloudflared` → name it.
7. Copy the **token** from the Docker install command it shows (`eyJhIjoiN…`).
8. On the **Public hostname** tab: subdomain `lab`, your domain, type `HTTP`, URL
   `http://localhost:5000`. Cloudflare creates the DNS record for you.

Cloudflare's Zero Trust onboarding sometimes asks for a payment method even
though the plan is free.

**Configuration:**

```yaml
provider: manual
deployment_name: smith-lab
ssl:
  provider: none        # Cloudflare supplies the public certificate
manual:
  connectivity: mesh_overlay   # lan_direct is rejected with any exposure mode
  overlay_tailnet: example.ts.net
  participant_exposure: cloudflare_tunnel
  public_hostname: lab.smithlab.org
```

**Deploy:**

```bash
lablink deploy \
  --tailscale-authkey tskey-auth-... \
  --cloudflare-tunnel-token eyJhIjoiN...
```

The token is stored only in the deployment's `.env` (mode `0600`), never in
`config.yaml`, and is carried forward on redeploys — pass
`--cloudflare-tunnel-token` on the first deploy, or again to rotate it. If the
mode is set and no token is available, both `lablink deploy` and the container's
`start.sh` fail loudly rather than starting an allocator that looks healthy but
is unreachable.

After `docker compose up`, `lablink deploy` makes one request to
`https://<public_hostname>/api/health`. A miss is a warning, not a failure — a
freshly created DNS record may still be propagating, in which case retry the URL
in your browser in a few minutes.

##### Cloudflare can read your traffic

Cloudflare Tunnel terminates TLS at Cloudflare's edge, so admin logins, session
cookies and participant desktop streams are all decrypted there. Tailscale
Funnel does not do this — its relays forward encrypted bytes and TLS terminates
on your own machine. If your data cannot transit a third party in cleartext, use
`tailscale_funnel` and accept its `.ts.net` hostname.

## Validating Configuration

After modifying configuration, validate it:

### Schema Validation (Recommended)

Use the built-in validation CLI to check your config against the schema:

```bash
# Validate config file
lablink-validate-config lablink-infrastructure/config/config.yaml

# Output on success:
# [PASS] Config validation passed

# Output on error:
# [FAIL] Config validation failed: Error merging config with schema
#        Unknown key: 'unknown_section'
#        This key is not defined in the Config schema
```

The validator checks:

- File exists and is named `config.yaml`
- All keys match the structured config schema
- Type mismatches (strings vs integers, etc.)
- Unknown configuration sections
- `provider`, `manual.connectivity` and `manual.participant_exposure` are known values
- DNS/SSL dependency rules (e.g., SSL requires DNS enabled)
- Manual-provider rules (see [Manual Provider Options](#manual-provider-options-manual))

It does **not** check `deployment_name` or `environment` — those are validated by the
`lablink` CLI (`lablink configure`, `lablink deploy`), not by this tool.

**Important**: The validator requires the filename to be `config.yaml` to enable Hydra's strict schema matching. Using a different filename will bypass schema validation.

**Usage in CI/CD:**

```bash
# Validate before deployment
lablink-validate-config config/config.yaml && tofu apply || exit 1
```

### Running Against a Config Locally

The allocator reads `$CONFIG_DIR/$CONFIG_NAME`, so point it at your file:

```bash
CONFIG_DIR=$PWD/lablink-infrastructure/config lablink-allocator
```

For the OpenTofu side, `tofu validate` and `tofu plan` in the deployment
directory preview what the config will actually build.

## Full Configuration Examples

Five scenarios, one base file. Everything outside `dns`, `eip` and `ssl` is
identical in all of them, so start from the base and apply one overlay.

### Base

Copy this, then replace the two `PLACEHOLDER_*` passwords and `bucket_name`.
The `dns`/`eip`/`ssl` values come from whichever scenario you pick below.

```yaml
# LabLink base configuration — combine with one scenario overlay below.

deployment_name: "lablink"        # required; prefixes every AWS resource name
environment: "prod"               # dev | test | ci-test | prod
provider: "aws"

db:
  password: "PLACEHOLDER_DB_PASSWORD"

app:
  admin_user: "admin"
  admin_password: "PLACEHOLDER_ADMIN_PASSWORD"
  region: "us-west-2"

machine:
  machine_type: "g4dn.xlarge"
  image: "ghcr.io/talmolab/lablink-client-base-image:latest"
  ami_id: ""                      # resolves a Deep Learning Base AMI for app.region
  repository: "https://github.com/talmolab/sleap-tutorial-data.git"
  software: "sleap"

allocator:
  image_tag: "linux-amd64-latest"

bucket_name: "tf-state-lablink-YOURORG"

startup_script:
  enabled: false
  path: ""
  on_error: "continue"
```

### IP Only

Reach the allocator at `http://<ALLOCATOR_IP>` over plain HTTP. No domain, no
certificate, no issuance limits — the simplest setup, and the right one for
repeated test deploys.

```yaml
dns:
  enabled: false
  terraform_managed: false
  domain: ""
  zone_id: ""

eip:
  strategy: "dynamic"

ssl:
  provider: "none"
  email: ""
  certificate_arn: ""
```

### Let's Encrypt

Caddy obtains and renews a certificate automatically. Access at
`https://test.lablink.example.com`.

**Prerequisites:** a Route53 hosted zone for the domain, with the registrar's
nameservers pointed at it.

Set `terraform_managed: true` to let OpenTofu create and destroy the A record,
or `false` if you maintain it yourself.

```yaml
dns:
  enabled: true
  terraform_managed: true         # false = you manage the A record
  domain: "test.lablink.example.com"
  zone_id: ""

eip:
  strategy: "persistent"

ssl:
  provider: "letsencrypt"
  email: "admin@example.com"
  certificate_arn: ""
```

!!! warning "5 certificates per domain per 7 days"
    Every deploy requests a fresh certificate, and the failure surfaces only as
    `ERR_SSL_PROTOCOL_ERROR` in the browser. Use a fresh subdomain per test
    cycle, or [IP Only](#ip-only).

### CloudFlare

CloudFlare's proxy terminates TLS, so there are no issuance limits. Access at
`https://lablink.example.com`.

**Prerequisites:** the domain is managed in CloudFlare with the proxy enabled
(orange cloud). `terraform_managed` must be `false` — CloudFlare owns the record.

```yaml
dns:
  enabled: true
  terraform_managed: false
  domain: "lablink.example.com"
  zone_id: ""

eip:
  strategy: "persistent"

ssl:
  provider: "cloudflare"
  email: ""
  certificate_arn: ""
```

### ACM + ALB

AWS-managed certificates behind an Application Load Balancer. No issuance
limits, but the ALB adds roughly **$20/month**. Access at
`https://lablink.example.com`.

**Prerequisites:** a Route53 hosted zone, plus an ACM certificate already
requested and validated for the domain — you need its ARN.

```yaml
dns:
  enabled: true
  terraform_managed: true
  domain: "lablink.example.com"
  zone_id: ""

eip:
  strategy: "persistent"

ssl:
  provider: "acm"
  email: ""
  certificate_arn: "arn:aws:acm:us-west-2:123456789012:certificate/abcd1234-EXAMPLE"
```


## Next Steps

- **[Adapting LabLink](adapting.md)**: Customize for your research software
- **[Deployment](deployment.md)**: Deploy with your configuration
- **[Security & Access](security.md)**: Secure your configuration values
