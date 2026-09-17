# Security

LabLink protects the admin UI, client registration, and browser desktop
sessions with different credentials. The deployment config and state can
contain secrets; treat them as sensitive files. Choose an HTTPS exposure mode
before inviting participants over the internet.

## Change Default Passwords

The allocator reads `app.admin_user`, `app.admin_password`, and `db.password`
from its deployed `config.yaml`. It does not read `ADMIN_PASSWORD` or
`DB_PASSWORD` environment variables or fetch them from AWS Secrets Manager.
The handling depends on how you deploy:

- **CLI on AWS:** `lablink deploy` prompts for admin credentials on every run.
  It saves them in the deployment working copy under `~/.lablink/deploy/`,
  never in `~/.lablink/config.yaml`. It does **not** prompt for the database
  password: set a strong `db.password` in `~/.lablink/config.yaml` yourself
  before deploying.
- **CLI with `provider: manual`:** `deploy` uses values from the config or a
  previous rendered deployment first, then prompts if needed. It saves the
  result under `~/.lablink/compose/<deployment_name>/config.yaml`.
- **Template repository:** keep `PLACEHOLDER_ADMIN_PASSWORD` and
  `PLACEHOLDER_DB_PASSWORD` in the committed config. `scripts/setup.sh`
  creates GitHub repository secrets `ADMIN_PASSWORD` and `DB_PASSWORD`; the
  deployment workflow substitutes them in its working copy.

Do not commit a config file containing real passwords. Use a strong unique
admin password for any publicly reachable allocator. The validator rejects
common weak passwords and passwords shorter than 12 characters for a
Tailscale Funnel deployment.

### Database Password

Set `db.password` through the deployment path above. PostgreSQL 17 runs
inside the allocator container, and the standard deployments do not publish
port 5432 to the host or the internet. The database password still protects
local and in-container access; replace the CLI default or template placeholder
before it reaches a running deployment.

## Machine-to-Machine Authentication

- The allocator uses admin HTTP Basic authentication for admin pages and
  management APIs. Participant requests use their signed browser session,
  not the admin password.
- A BYO client registers with a deployment-wide register token. The
  allocator stores an argon2 hash of that token in PostgreSQL. The plaintext
  token appears in the allocator log so the CLI can pick it up; protect log
  access and avoid pasting the token into public channels.
- Each registered client receives its own secret. The allocator stores its
  argon2 hash and verifies it on client telemetry endpoints, including
  heartbeat, GPU health, session metrics, and overlay-hostname updates.
- The allocator also mints a separate `AGENT_TOKEN` for its control calls to
  client agents. The client agent checks the bearer value with ordinary
  string equality, so this path does not claim constant-time comparison.
  The token is generated per allocator process. A manual-provider client
  container can outlive an allocator restart and retain an older token until
  it is re-registered or restarted with updated credentials.

## Browser Desktop Sessions

On assignment, the allocator rotates the client's KasmVNC password and
creates a session ID and browser token. It signs the `lablink_session` cookie
with HMAC-SHA256; the cookie is `HttpOnly` and `SameSite=Strict`, with the
`Secure` flag when the request arrived over HTTPS. The browser receives a
`303` redirect to `/desktop`.

For allocator-proxied desktops, nginx calls Flask's `auth_request` endpoint
before upgrading `/proxy/<token>` to a WebSocket. The signed cookie must
resolve to the VM named by the URL token and the VM must be running. nginx
then sends the rotated KasmVNC credential to the client; the browser does not
receive it. Reverse-tunnel attachment at `/tun-*` has its own bearer-token
`auth_request` check.

An admin can reserve a VM for peek or connect without giving it to a student.
The allocator releases reservations older than 30 minutes in a background
sweep, so closing a browser tab does not hold the seat indefinitely.

## Network Security

The template's allocator security group allows TCP 80, 443, 5000, and 22
from `0.0.0.0/0`. The application may bind port 5000 to loopback under an
HTTPS configuration, but the security-group rule itself is broad. The
client VM security group allows SSH (22) from the internet and KasmVNC
(6080) and its agent (7070) only from the allocator security group. Neither
security group exposes PostgreSQL 5432.

Review those rules for your deployment before making it public. OpenTofu
resources are in the [template repository](https://github.com/talmolab/lablink-template)
and the allocator's bundled client OpenTofu files. For a manual-provider
deployment, use [the connectivity and exposure modes](cli/byo-clients.md#pick-a-connectivity-mode)
to control which network paths are reachable.

## HTTP-Only Deployments (`ssl.provider: "none"`)

HTTP sends the admin Basic-auth header, session cookie, bearer tokens, and
desktop traffic without transport encryption. Use HTTPS for public
deployments. The AWS host uses Caddy for `letsencrypt`, `cloudflare`, and
`none`; ACM terminates TLS at an ALB. A Cloudflare Tunnel terminates TLS at
Cloudflare's edge, so Cloudflare can read traffic there. Tailscale Funnel
offers a different public exposure path; see
[Tailscale & Cloudflare Setup](cli/tunnels.md).

An HTTP viewer also cannot use browser WebCodecs H.264 streaming on an
insecure origin, so it falls back to JPEG/WebP. `lablink doctor` warns about
this when `ssl.provider: none` is selected.

## GitHub Actions and State

The template's `scripts/setup.sh` creates a GitHub OIDC provider and the
`github-actions-lablink` IAM role, then stores the role ARN and region as
repository secrets. The trust policy is scoped to the configured repository
and the `sts.amazonaws.com` audience. See
[AWS Setup](aws-setup.md#step-4-github-actions-oidc-configuration) for the
current managed-policy list.

OpenTofu state can contain sensitive values, including generated SSH keys.
The template uses an S3 backend and a DynamoDB lock table. `setup.sh` enables
S3 versioning on a new state bucket; it does not explicitly set a bucket
encryption policy or public-access block. Apply your organization's storage
controls and restrict access to the state bucket and workflow artifacts.

## SSH Access

### SSH Key Management

The deployment OpenTofu state contains a key for the **allocator**. On the
template path, the deploy workflow uploads it as a one-day artifact; a local
OpenTofu run can use `tofu output -raw private_key_pem` from the initialized
`lablink-infrastructure/` directory. Restrict file
permissions before using that key.

Client VMs use a different keypair generated by the allocator's own OpenTofu
workspace. Its output is `lablink_private_key_pem` inside the allocator
container. The deployment key does not open client VMs. See
[Troubleshooting](troubleshooting.md) for access steps and use the allocator
logs or `lablink logs` to diagnose a client before reaching for SSH.
