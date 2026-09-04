# Tailscale & Cloudflare Setup

Some of the manual provider's [connectivity and exposure modes](byo-clients.md#pick-a-connectivity-mode)
ride on a third-party service: Tailscale (mesh overlay, Funnel) or Cloudflare
(Tunnel). LabLink never touches either account for you — you set it up once,
hand the CLI a credential at deploy time, and the CLI does the rest. This page
is that one-time, account-side setup.

What you need depends on your config:

| Config                                           | Set up here                                                                                 |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| `manual.connectivity: mesh_overlay`              | A [Tailscale tailnet and auth key](#tailscale)                                              |
| `manual.participant_exposure: tailscale_funnel`  | The same tailnet and auth key, plus a [one-time Funnel grant](#4-funnel-only-grant-it-once) |
| `manual.participant_exposure: cloudflare_tunnel` | A [Cloudflare account, domain, and tunnel token](#cloudflare-tunnel)                        |
| `lan_direct`, `reverse_tunnel`, exposure `none`  | Nothing — no third-party account involved                                                   |

The two axes combine: a `reverse_tunnel` deployment needs no Tailscale on its
own, but pairing it with `participant_exposure: tailscale_funnel` brings in the
whole Tailscale section anyway.

## Tailscale

One tailnet and **one reusable auth key** cover the whole deployment. The
allocator joins the tailnet through a sidecar container during `lablink deploy`
(as machine `lablink-allocator-<deployment_name>`), and every mesh-overlay
client box joins with the same key during `lablink client register`.

### 1. Create a tailnet

1. Sign up at [tailscale.com](https://tailscale.com) — the free personal plan
   is enough.
2. In the [admin console](https://login.tailscale.com/admin), open the **DNS**
   tab and note your **tailnet name** (e.g. `tail1234.ts.net`). That string is
   your config's `manual.overlay_tailnet`.
3. Leave **MagicDNS** enabled (it is by default). The allocator reaches
   mesh-overlay clients by their MagicDNS names, so turning it off breaks
   `mesh_overlay` entirely.

You do **not** need to install Tailscale on the allocator host or the client
boxes — it runs inside the containers LabLink starts.

### 2. Generate an auth key

In the admin console: **Settings → Keys → Generate auth key**.

| Setting          | Pick                      | Why                                                                                                                                                                                            |
| ---------------- | ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Reusable**     | **On**                    | The allocator and every client box all join with this one key. A single-use key works for the first join and fails on the second.                                                              |
| **Expiration**   | Default (90 days) is fine | Expiry only blocks _new_ joins — machines already on the tailnet stay on it. Generate a fresh key when you next add a box after expiry.                                                        |
| **Ephemeral**    | **Off** (the default)     | LabLink deliberately persists each node's identity in a docker volume so a re-registered box returns as the _same_ tailnet machine. Ephemeral nodes get deleted while offline, defeating that. |
| **Pre-approved** | On, if shown              | The checkbox only appears when your tailnet has device approval enabled; without it you'd have to manually approve every box in the **Machines** tab before it works.                          |

Copy the `tskey-auth-…` value — Tailscale shows it only once.

### 3. Hand the key to the CLI

On the allocator host, the first deploy:

```bash
lablink deploy --tailscale-authkey tskey-auth-...
```

Omit the flag and `deploy` prompts for it (hidden, so it stays out of your
shell history). It's stored only in the deployment's `.env` (mode `0600`) and
carried forward on redeploys — pass the flag again only to rotate the key.

On each mesh-overlay box:

```bash
lablink client register --allocator-url <url> --register-token <token> \
  --overlay-hostname <name-of-your-choice> --tailscale-authkey tskey-auth-...
```

The register command that `deploy` and the admin UI's `/admin/byo-onboarding`
page print leaves `--tailscale-authkey <key>` as a placeholder — the key is a
secret, so it travels only through you. Send it to whoever registers boxes over
a channel you'd trust with a password.

### 4. Funnel only: grant it once

`participant_exposure: tailscale_funnel` publishes the allocator at
`https://lablink-allocator-<deployment_name>.<tailnet>.ts.net`. Tailnets don't
allow Funnel until you approve it once:

- Just run `lablink deploy`. If the tailnet hasn't granted Funnel yet, the
  deploy finishes the stack but exits with Tailscale's own message naming the
  exact **grant URL** — open it, approve, and run `lablink deploy` again.
- A tailnet that has already granted Funnel needs nothing; the CLI enables and
  verifies Funnel on every deploy.

Funnel also requires `app.admin_password` to be at least 12 characters — a
`.ts.net` hostname appears in Certificate Transparency logs and gets scanned by
bots within minutes of publishing.

### Key expiry, rotation, housekeeping

- **Node keys expire after 180 days** by default, at which point a machine
  silently drops off the tailnet. For a deployment meant to outlive that,
  select each LabLink machine in the **Machines** tab and **Disable key
  expiry**.
- **Rotating the auth key**: generate a new key, use it for future `client
register` runs, and pass `--tailscale-authkey` once to `lablink deploy` to
  update the allocator's stored copy. Machines already joined are unaffected.
- **Stale machines**: an unregistered or reset box leaves its old (offline)
  machine holding its name in the tailnet, and the next join gets a `-1`
  suffix. Delete stale machines in the **Machines** tab — see
  [Troubleshooting](../troubleshooting.md) and the `reset-overlay` notes in
  [Bring-Your-Own Clients](byo-clients.md#removing-a-box).

## Cloudflare Tunnel

`participant_exposure: cloudflare_tunnel` publishes the allocator at a hostname
you choose, through a tunnel in your own Cloudflare account. `cloudflared`
ships inside the allocator image; all you supply is the **tunnel token**.

!!! warning "Requires a domain whose nameservers point at Cloudflare"
    A custom hostname needs Cloudflare's free-plan **full setup** — the
    domain's nameservers must be delegated to Cloudflare. Partial (CNAME)
    setup is Business-tier and subdomain zones are Enterprise-tier, so an
    institutional domain such as `salk.edu` **cannot** be used on the free
    plan. Register a domain you control instead (typically ~$10/yr), or use
    `tailscale_funnel`, which needs no domain at all.

### 1. One-time setup

Done once; the tunnel and its DNS record live in your Cloudflare account, so
the URL is stable across every `lablink deploy` and `lablink destroy`:

1. Sign up at [cloudflare.com](https://cloudflare.com) (free).
2. In the [dashboard](https://dash.cloudflare.com) — not the marketing homepage —
   go to **Domains → Overview**, click **Add domain** (blue button, top right),
   then pick **Connect a domain**. Enter the domain you own; the plan choice
   comes after — pick **Free**. "Free" is Cloudflare's service tier, not the
   domain: the domain itself always costs money (~$10/yr).
3. At your domain's registrar, replace the nameservers with the two Cloudflare
   shows.
4. Wait for activation (usually minutes).

    !!! tip "No domain yet? Buy it from Cloudflare and skip steps 2–4"
        **Buy a domain** on that same Add-domain screen (also
        **Domains → Registrations**) registers one at cost. A
        Cloudflare-registered domain lands in your account already active on
        Cloudflare's nameservers — no connecting, no nameserver swap, no
        activation wait.

5. Open the **Zero Trust** dashboard; pick a team name and the Free plan.
6. **Networks → Tunnels & Mesh → Create a tunnel** → connector `cloudflared` → name
   it.
7. Copy the **token** from the Docker install command it shows (`eyJhIjoiN…`).
8. On the **Public hostname** tab: subdomain (e.g. `lab`), your domain, type
   `HTTP`, URL `http://localhost:5000`. Cloudflare creates the DNS record for
   you.

Cloudflare's Zero Trust onboarding sometimes asks for a payment method even
though the plan is free.

### 2. Configure and deploy

```yaml
provider: manual
deployment_name: smith-lab
ssl:
  provider: none # Cloudflare supplies the public certificate
manual:
  connectivity: mesh_overlay # lan_direct is rejected with any exposure mode
  overlay_tailnet: example.ts.net
  participant_exposure: cloudflare_tunnel
  public_hostname: lab.smithlab.org
```

`public_hostname` is the subdomain + domain from step 8, as a bare FQDN — no
`https://`, port or path.

```bash
lablink deploy --cloudflare-tunnel-token eyJhIjoiN...
```

Same secret handling as the Tailscale key: prompted (hidden) if the flag is
omitted on the first deploy, stored only in the deployment's `.env`, carried
forward on redeploys, passed again only to rotate.

After the stack is up, `deploy` checks `https://<public_hostname>/api/health`
once. A miss is a warning, not a failure — a freshly created DNS record may
still be propagating; retry the URL in your browser in a few minutes.

!!! note "Cloudflare can read your traffic"
    Cloudflare Tunnel terminates TLS at Cloudflare's edge — see the
    [security note](../configuration.md#cloudflare-can-read-your-traffic) for
    what that means and when to prefer `tailscale_funnel`.

## Next steps

- [Bring-Your-Own Clients](byo-clients.md) — the deploy and register flow these credentials plug into.
- [Configuration](../configuration.md#manual-provider-options-manual) — every `manual.*` option and its validation rules.
- [CLI Reference](../reference/cli.md) — full flag lists for `deploy` and `client register`.
