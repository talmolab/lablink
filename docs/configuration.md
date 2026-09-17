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
| IP only | None | No | None | None |
| Let's Encrypt | Auto via Caddy | Route53 | 5 certs/domain/week | None |
| CloudFlare | CloudFlare proxy | CloudFlare | None | None |
| ACM + ALB | AWS-managed | Route53 | None | ALB charges; [check current pricing](https://aws.amazon.com/elasticloadbalancing/pricing/) |

A copy-paste base file is in [Full Configuration Examples](#full-configuration-examples). The
template repo ships one overlay per scenario as
[`lablink-infrastructure/config/*.example.yaml`](https://github.com/talmolab/lablink-template/tree/main/lablink-infrastructure/config)
(`ip-only`, `letsencrypt`, `cloudflare`, `acm`).

## First Steps: Change Default Passwords

!!! danger "Critical Security Step"
    Set strong admin and database passwords before exposing a deployment. For
    the template-repo path, keep `PLACEHOLDER_ADMIN_PASSWORD` and
    `PLACEHOLDER_DB_PASSWORD` in the committed config: the deploy workflow
    replaces them from GitHub secrets. See
    [Security → Change Default Passwords](security.md#change-default-passwords).

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
| `password` | string | `lablink` | Database password. The template workflow substitutes `PLACEHOLDER_DB_PASSWORD` from its GitHub secret. |

!!! warning "Production Security"
    On the CLI path, replace the default `lablink` value in
    `~/.lablink/config.yaml` with a strong password before deploying; the CLI
    does not prompt for it. On the template path, keep the placeholder in
    committed config and set the `DB_PASSWORD` GitHub secret. See
    [Security](security.md#database-password).

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

Any EC2 instance type is accepted. The GPU and CPU-only types the CLI wizard
offers are listed in [Cost Estimation](cost-estimation.md#gpu-instance-types),
along with a link to current regional prices.

#### Docker Image

**Default**: `ghcr.io/talmolab/lablink-client-base-image:latest`

The Docker image determines what software runs on your VMs. Options:

1. **Use default SLEAP image** (for SLEAP workflows)
2. **Build custom image** (for your research software) - see [Adapting LabLink](adapting.md)
3. **Use different tag**:
    - `:latest` - latest stable release
    - `:linux-amd64-test` - development version
    - `:0.4.0` - specific version (no `v` prefix)

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

- **CLI**: `lablink configure` never asks for credentials. On AWS, `lablink deploy`
  prompts for them on every run and writes them only into the deployment's working
  copy under `~/.lablink/deploy/`, never into `~/.lablink/config.yaml`. On the manual
  provider, `deploy` — and `destroy` on either provider — resolves them from
  `config.yaml`, then from the previous deployment's saved config, then by prompting.
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
- `linux-amd64-0.4.0` - specific version (no `v` prefix)

### Bucket Name

**Option**: `bucket_name`
**Schema default**: `tf-state-lablink-allocator-bucket`

S3 bucket for OpenTofu state storage. Must be globally unique. `lablink setup`
creates `lablink-tf-state-<account-id>` and writes it to the CLI config; the
template setup script uses the bucket name you choose and writes it to the
template config.

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
Creating the tailnet, finding this value, and generating the auth key the deploy
will ask for are covered in
[Tailscale & Cloudflare Setup](cli/tunnels.md#tailscale).

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

For setup steps and working examples of both exposure modes, see
[Tailscale & Cloudflare Setup](cli/tunnels.md).

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

This example uses IP-only HTTP for testing. Set your deployment name and
`bucket_name` before deploying; `lablink setup` writes the CLI bucket name for
you. For the template path, keep the `PLACEHOLDER_*` passwords in the committed
file so the deploy workflow replaces them from GitHub secrets. For the CLI
path, replace `PLACEHOLDER_DB_PASSWORD` in `~/.lablink/config.yaml` with a
strong password; `lablink deploy` prompts for the admin password. For a
manual OpenTofu deploy, replace both placeholders with strong passwords in
your private working copy.

```yaml
deployment_name: "lablink"
environment: "prod"
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
  ami_id: "" # resolves a Deep Learning Base AMI for app.region
  repository: "https://github.com/talmolab/sleap-tutorial-data.git"
  software: "sleap"

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

allocator:
  image_tag: "linux-amd64-latest"

bucket_name: "tf-state-lablink-YOURORG"
```

For domain-based deployment, use the matching
[template configuration example](https://github.com/talmolab/lablink-template/tree/main/lablink-infrastructure/config)
(`letsencrypt.example.yaml`, `cloudflare.example.yaml`, or
`acm.example.yaml`) and the [SSL options](#ssltls-options-ssl) above. The
[IP-only template example](https://github.com/talmolab/lablink-template/blob/main/lablink-infrastructure/config/ip-only.example.yaml)
is the corresponding source file for the example here.

## Next Steps

- **[Adapting LabLink](adapting.md)**: Customize for your research software
- **[Deployment](deployment.md)**: Deploy with your configuration
- **[Security & Access](security.md)**: Secure your configuration values
