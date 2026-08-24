# External Runtime (Run:AI Walkthrough)

A third way to run the allocator: not as an EC2 instance, not as a
docker-compose stack you `docker run` yourself, but as a **workload on a
container platform you don't control the Docker daemon for** — a Run:AI
workspace, a raw Kubernetes pod, or similar. `lablink deploy --render-only`
renders the same allocator bundle the manual provider always renders, then
hands it to you to launch on that platform instead of starting containers
itself.

This page walks through the whole path end to end on Run:AI, the platform it
was validated against. The mechanics — render, submit a workload, read the
register token from its logs — carry over to any platform that runs
arbitrary container images.

## When to use this page

Use this instead of [Bring-Your-Own Clients](byo-clients.md) when the
allocator itself has to run **inside** a managed container platform rather
than on a machine you can `docker run` on directly. The giveaway is that
`lablink deploy` has no Docker daemon to talk to — the platform *is* the
container runtime. Typically that's because the only compute you have access
to is scheduler-hosted (a Run:AI cluster, a shared Kubernetes namespace), and
starting a container from inside a container (docker-in-docker) either isn't
possible or isn't something the platform allows.

The rendered bundle is still a plain `provider: manual` deployment under the
hood — same allocator image, same `config.yaml`, same register-token
handshake. `--render-only` just stops short of running it, because there is
no local daemon to run it *with*.

!!! info "Requirements"
    - `manual.connectivity: reverse_tunnel` — clients dial **out** to the
      allocator; the allocator never dials in.
    - `manual.participant_exposure: cloudflare_tunnel` — the allocator
      publishes itself by dialing **out** to Cloudflare's edge.
    - A domain on Cloudflare's nameservers (see
      [Configuration](../configuration.md#exposure-mode-cloudflare_tunnel)
      for the one-time domain setup if you don't have one yet).
    - The platform must allow the container to run as **root** — the
      allocator image bundles Postgres and nginx, both of which need it.

    Every leg of this path dials out. The workload needs no inbound ports
    open and no privileges beyond running as root.

## Step 1: Configure

```bash
lablink configure
```

Choose the **manual** provider, then **reverse_tunnel** connectivity, then
**cloudflare_tunnel** participant exposure, and enter your public hostname
(e.g. `lab.smithlab.org`) when asked. The wizard writes
`~/.lablink/config.yaml` and pins `ssl.provider: none` for you automatically
— the allocator image ships no TLS terminator; Cloudflare terminates TLS at
its edge instead.

A minimal hand-written equivalent:

```yaml
provider: manual
deployment_name: smith-lab
ssl:
  provider: none
manual:
  connectivity: reverse_tunnel
  participant_exposure: cloudflare_tunnel
  public_hostname: lab.smithlab.org
```

If you edit `config.yaml` by hand rather than through the wizard, double
check `ssl.provider: "none"` — `SSLConfig`'s own default is `letsencrypt`,
and `lablink deploy` refuses anything else for the manual provider.

## Step 2: Create the Cloudflare tunnel (one-time, dashboard)

This is the same Cloudflare Tunnel every `cloudflare_tunnel` deployment uses
(see [Configuration](../configuration.md#exposure-mode-cloudflare_tunnel) for
the full one-time domain setup — signing up, delegating nameservers, opening
Zero Trust). What differs here is only *where* `cloudflared` ends up
running: normally it's a process inside a container on your own machine;
here it's a process inside the allocator container running as a platform
workload. Either way, `cloudflared` is baked into the allocator image and
only starts when the config asks for it — there's no separate connector to
install.

In the Cloudflare **Zero Trust** dashboard:

1. **Networks → Tunnels → Create a tunnel** → choose the remotely-managed
   (Cloudflared) connector type, and name it.
2. On the **Public Hostname** tab, add a hostname on your domain (e.g.
   `lab.smithlab.org`) with service **`http://localhost:5000`** — that's the
   allocator container's own nginx listener, whichever machine or platform
   it ends up running on.
3. Copy the **tunnel token** from the connector's install command
   (`eyJhIjoiN…`). You'll pass it to the workload as an environment
   variable, not run any `cloudflared` install command yourself.

## Step 3: Render the deployment bundle

```bash
lablink deploy --render-only --cloudflare-tunnel-token <token>
```

No Docker is used or required on this machine — `--render-only` writes the
same files a compose deploy would (`config.yaml`, `custom-startup.sh`, a
canonical-URL file) into `~/.lablink/compose/<deployment_name>/`, marks the
deployment as externally managed, and prints a launch sheet instead of
starting containers:

```text
Bundle rendered — launch it on your platform:
  Image:    ghcr.io/talmolab/lablink-allocator-image:linux-amd64-latest  (default command)
  Env vars:
    PARTICIPANT_EXPOSURE=cloudflare_tunnel
    CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoiN...
  Mounts (read-only files, all rendered in this dir):
    ~/.lablink/compose/smith-lab/config.yaml        -> /config/config.yaml
    ~/.lablink/compose/smith-lab/custom-startup.sh  -> /config/custom-startup.sh
    ~/.lablink/compose/smith-lab/allocator-url      -> /config/allocator-url
  Persistent volume (optional): /var/lib/postgresql (DB survives pod restarts)
  Inbound ports: none required — every leg dials out.
  The image expects to run as root (postgres + nginx).

  After boot, the BYO register token prints in the workload's log
  (also at /var/log/lablink/allocator.log inside the container).
```

Everything after this step is about getting that image, those two env vars,
and those three files onto your platform.

!!! note "Tailscale-based modes are rejected here"
    `--render-only` refuses a config that needs the Tailscale sidecar
    (`connectivity: mesh_overlay` and/or `participant_exposure:
    tailscale_funnel`) — that sidecar needs a kernel TUN device and
    `NET_ADMIN`, which managed platforms don't grant workloads. Use
    `reverse_tunnel` + `cloudflare_tunnel`, as above.

## Step 4: Launch the allocator workspace (Run:AI)

The image's default command (`start.sh`) needs no override, there's no GPU
request for the allocator itself, and the Postgres volume is optional — the
allocator's database is created fresh per deployment either way.

### ConfigMap route

Stage the three rendered files as a ConfigMap and mount it at `/config`:

```bash
kubectl create configmap lablink-config -n runai-<project> \
  --from-file ~/.lablink/compose/<deployment>/config.yaml \
  --from-file ~/.lablink/compose/<deployment>/custom-startup.sh \
  --from-file ~/.lablink/compose/<deployment>/allocator-url

runai workspace submit lablink-allocator -p <project> \
  -i ghcr.io/talmolab/lablink-allocator-image:<image_tag> \
  -e PARTICIPANT_EXPOSURE=cloudflare_tunnel \
  -e 'CLOUDFLARE_TUNNEL_TOKEN=<token>' \
  --configmap-map-volume name=lablink-config,path=/config \
  --existing-pvc claimname=<pvc>,path=/var/lib/postgresql   # optional
```

### No-kubectl fallback (validated)

If you don't have `kubectl` access to the cluster — only the `runai` CLI or
UI — skip the ConfigMap entirely and inject the config through the
environment instead, decoding it back to a file in a command override:

```bash
runai workspace submit lablink-allocator -p <project> \
  -i ghcr.io/talmolab/lablink-allocator-image:<image_tag> \
  -e LABLINK_CONFIG_B64=$(base64 -i ~/.lablink/compose/<deployment>/config.yaml) \
  -e ALLOCATOR_URL=https://<public_hostname> \
  -e PARTICIPANT_EXPOSURE=cloudflare_tunnel \
  -e 'CLOUDFLARE_TUNNEL_TOKEN=<token>' \
  --command -- bash -c 'mkdir -p /config && echo "$LABLINK_CONFIG_B64" | base64 -d > /config/config.yaml && touch /config/custom-startup.sh && printf %s "$ALLOCATOR_URL" > /config/allocator-url && exec /app/start.sh'
```

This reconstructs the same `/config` layout the ConfigMap route mounts —
`custom-startup.sh` is just touched empty (no custom startup script in this
example) and `allocator-url` gets the public hostname directly — then hands
off to the image's normal entrypoint.

## Step 5: Verify and get the register token

Watch the workload boot:

```bash
runai workspace logs lablink-allocator -p <project> -f
```

Look for Postgres and Flask coming up — this is where a line of the form
`REGISTER_TOKEN=...` prints, the bootstrap token BYO clients register
with — followed by nginx passing its config check and the `cloudflared`
connector's own startup lines.

Once it's up, confirm the public path end to end:

```bash
curl https://<public_hostname>/api/health
```

A `200` response means DNS, the Cloudflare edge, the tunnel, nginx, and
Flask are all working together. The admin UI is at
`https://<public_hostname>/admin`.

!!! tip "Lost the token?"
    Re-run the `logs -f` command above and grep for `REGISTER_TOKEN` — the
    allocator only prints it once, at startup, but it stays in the
    workload's log for as long as the workload does.

## Step 6: Client workspaces on the same platform (optional)

Clients don't have to run anywhere special — they're ordinary
reverse-tunnel BYO clients that happen to also be platform workloads. Since
you generally can't `docker run` from your own laptop onto someone else's
cluster, register each client **ahead of time**, from your own machine, with
`--no-run-locally`:

```bash
lablink client register --allocator-url https://<public_hostname> \
  --register-token <token> --tunnel --no-run-locally \
  --hostname runai-client-1 --machine-identity runai-client-1 \
  --env-file ./client-1.env
```

`--tunnel` registers a reverse-tunnel client (no extra arguments — the
allocator mints every value the tunnel needs); `--no-run-locally` means
nothing gets `docker run` here, and instead the secrets are written to
`./client-1.env` and printed for you to paste into a workload submission.
`--hostname`/`--machine-identity` are required in this mode since there's no
local box to auto-detect them from.

Submit the client workload with the client image and every non-comment line
of that env file as a `-e` variable:

```bash
runai workspace submit lablink-runai-client-1 -p <project> \
  -i ghcr.io/talmolab/lablink-client-base-image:<tag> \
  --gpu-devices-request 1 \
  -e CLIENT_ID=... -e CLIENT_SECRET=... # …every line from client-1.env
```

Add `--gpu-present --gpu-model "<model>"` to the `register` call itself when
the workload will actually have a GPU attached — that's what shows up in the
allocator's inventory, independent of whatever `--gpu-devices-request` you
pass to Run:AI. Confirm registration with:

```bash
lablink status
```

or by hitting `GET /api/v1/clients` on the allocator directly (admin basic
auth).

## Day-2 operations

Run the CLI from your own machine — nothing needs to run on the platform
itself besides the workloads:

| Task | Command | Notes |
|---|---|---|
| Check health | `lablink status` | Reads the public URL straight from the local rendered bundle; there's no local container to show `docker ps` status for, so it prints a note pointing you at the platform's own workload view for that. |
| Read logs | `lablink logs` | No local `lablink-allocator` container to `docker logs` — this fetches a redacted tail of the allocator's own log over HTTPS from `/api/allocator-logs` (admin basic-auth) instead. |
| Tear down | `lablink destroy` | Only removes the local rendered bundle. It does **not** touch the platform — delete the allocator workload yourself (e.g. `runai workspace delete lablink-allocator -p <project>`), **and delete every client workload you submitted there too**. Any Postgres data lives in whatever volume you attached there, not on this machine. |

`lablink client launch` stays unavailable under the manual provider exactly
as it is for docker-compose deployments — register each client with
`lablink client register` instead.

`lablink stats` and `lablink export-metrics` work the same as for any
manual-provider deployment: they resolve the allocator's address from the
same recorded public URL `status`/`logs` use, so no extra configuration is
needed.

## Limitations

- **No `mesh_overlay` or `tailscale_funnel`.** Both need a Tailscale sidecar
  with a kernel TUN device and `NET_ADMIN` — access managed container
  platforms don't grant workloads. Use `reverse_tunnel` +
  `cloudflare_tunnel`, as this page does.
- **Cloudflare needs a domain you control on Cloudflare's nameservers.**
  Cloudflare's free plan requires full nameserver delegation, so an
  institutional domain (e.g. a university's) generally can't be used this
  way — see
  [Configuration](../configuration.md#exposure-mode-cloudflare_tunnel) for
  the reasoning and alternatives.
- **The image runs as root.** Postgres and nginx inside the allocator
  container both need it. Clusters that force workloads onto non-root UIDs
  can't run this image yet.

## Next steps

- [Configuration](../configuration.md#manual-provider-options-manual) — every `manual.*` setting, plus the full Cloudflare Tunnel one-time setup.
- [Bring-Your-Own Clients](byo-clients.md) — the docker-compose path this shares its `config.yaml`/register flow with.
- [CLI Reference](../reference/cli.md#deployment-commands) — full flag list for `deploy`, `status`, `logs`, `destroy`.
- [Troubleshooting](../troubleshooting.md) — general LabLink issues.
