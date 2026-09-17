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
arbitrary container images. It is still a plain `provider: manual`
deployment: same image, same `config.yaml`, same register flow as
[Bring-Your-Own Clients](byo-clients.md).

!!! info "Requirements"
    - `manual.connectivity: reverse_tunnel` — clients dial **out** to the
      allocator; the allocator never dials in.
    - `manual.participant_exposure: cloudflare_tunnel` — the allocator
      publishes itself by dialing **out** to Cloudflare's edge.
    - A domain on Cloudflare's nameservers — see
      [Cloudflare Tunnel](tunnels.md#cloudflare-tunnel) for the one-time
      setup and why an institutional domain won't do.
    - The platform must allow the container to run as **root** — the
      allocator image bundles Postgres and nginx, both of which need it.
      Clusters that force non-root UIDs can't run it yet.

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

Follow [Cloudflare Tunnel](tunnels.md#cloudflare-tunnel) and keep the tunnel
token. Nothing there changes for an external runtime: `cloudflared` runs
inside the allocator container wherever that container lands, so the public
hostname's service stays `http://localhost:5000`. The only difference is that
the token reaches the workload as an environment variable instead of a
`lablink deploy` flag.

## Step 3: Render the deployment bundle

```bash
lablink deploy --render-only --cloudflare-tunnel-token <token>
```

No Docker is used or required on this machine — `--render-only` writes the
same bundle a compose deploy would into `~/.lablink/compose/<deployment_name>/`,
marks the deployment as externally managed, and prints a launch sheet instead
of starting containers:

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
CFG_B64=$(gzip -9 < ~/.lablink/compose/<deployment>/config.yaml | base64 | tr -d '\n')

runai workspace submit lablink-allocator -p <project> \
  -i ghcr.io/talmolab/lablink-allocator-image:<image_tag> \
  -e LABLINK_CONFIG_B64="$CFG_B64" \
  -e ALLOCATOR_URL=https://<public_hostname> \
  -e PARTICIPANT_EXPOSURE=cloudflare_tunnel \
  -e 'CLOUDFLARE_TUNNEL_TOKEN=<token>' \
  --command -- bash -c 'mkdir -p /config && echo "$LABLINK_CONFIG_B64" | base64 -d | gunzip > /config/config.yaml && touch /config/custom-startup.sh && printf %s "$ALLOCATOR_URL" > /config/allocator-url && exec /app/start.sh'
```

This reconstructs the same `/config` layout the ConfigMap route mounts —
`custom-startup.sh` is just touched empty (no custom startup script in this
example) and `allocator-url` gets the public hostname directly — then hands
off to the image's normal entrypoint.

Run:AI caps every submitted value (each `-e` and the command) at 10,000
characters, which a plain-base64 `config.yaml` can exceed — hence the `gzip`.
If it still doesn't fit, use the ConfigMap route or a PVC.

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
| Check health | `lablink status` | Checks `/api/health` at the public URL recorded in the local bundle and lists registered clients. There's no local container to `docker ps`, so it points you at the platform's workload view for that. |
| Read logs | `lablink logs` | Same TUI as everywhere else. Client logs come from the allocator; the allocator's own entry is a redacted tail fetched over HTTPS from `/api/allocator-logs` (admin basic-auth), since there's no local container to `docker logs`. |
| Tear down | `lablink destroy` | Only removes the local rendered bundle. It does **not** touch the platform — delete the allocator workload yourself (e.g. `runai workspace delete lablink-allocator -p <project>`), **and delete every client workload you submitted there too**. Any Postgres data lives in whatever volume you attached there, not on this machine. |

`lablink client launch` and `lablink client destroy` no-op under the manual
provider, here as for docker-compose deployments — register and unregister
each client with `lablink client register` / `lablink client unregister`.

`lablink stats` and `lablink export-metrics` work the same as for any
manual-provider deployment: they resolve the allocator's address from the
same recorded public URL `status`/`logs` use, so no extra configuration is
needed.

## Next steps

- [Tailscale & Cloudflare Setup](tunnels.md#cloudflare-tunnel) — the Cloudflare Tunnel one-time setup.
- [Configuration](../configuration.md#manual-provider-options-manual) — every `manual.*` setting.
- [Bring-Your-Own Clients](byo-clients.md) — the docker-compose path this shares its `config.yaml`/register flow with.
- [CLI Reference](../reference/cli.md#deployment-commands) — full flag list for `deploy`, `status`, `logs`, `destroy`.
- [Troubleshooting](../troubleshooting.md) — general LabLink issues.
