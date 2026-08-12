# API Endpoints

This document outlines the API endpoints provided by the LabLink Allocator service.

## Authentication

LabLink uses four gates. All bearer credentials go in `Authorization: Bearer <token>`.

| Gate | Credential | Guards |
|---|---|---|
| **HTTP Basic** | `app.admin_user` / `app.admin_password` from `config.yaml` | `/admin/*` pages and the operator JSON APIs |
| **Client secret** | A per-client secret minted when that client registers, stored as an argon2 hash | client → allocator telemetry (`/api/heartbeat`, `/api/vm-status`, …) |
| **Register token** | One deployment-wide bootstrap token, also stored hashed | `POST /api/v1/clients/register` only |
| **Signed cookie** | `lablink_session`, minted by `/api/request_vm` | `GET /desktop` |

A handful of endpoints are deliberately unauthenticated: `/` and
`/api/request_vm` (participant-facing), `/api/health` and
`/api/unassigned_vms_count` (health/monitoring), and `/internal/*` (reachable only
from the allocator's own nginx, never exposed publicly).

Secrets are per-client, so a leaked one compromises a single machine. The register
token is the only deployment-wide credential, and it can do nothing but register.

## Student Endpoint

### Landing Page

**Endpoint:** `GET /`

**Authentication:** None.

Renders `index.html`, the email form a participant submits to claim a seat.

### Request a VM

Claims a seat for a participant and redirects them to their desktop.

**Endpoint:** `POST /api/request_vm`

**Authentication:** None — this is the only unauthenticated state-changing endpoint in the allocator.

**Request Body:** `application/x-www-form-urlencoded`

- `email` (string, required): The participant's email address.

**What it does:**

1. **Idempotent rejoin.** If this email already owns a running seat, it keeps that seat rather than consuming a second one.
2. **Atomic claim.** Otherwise `assign_vm` claims a free seat with `SELECT … FOR UPDATE SKIP LOCKED`, so concurrent requesters cannot collide on one VM. An empty pool raises and returns `503` with `no_seats.html`.
3. **Per-session prep.** Mints a `session_id` and `browser_token`, then rotates the KasmVNC password on the assigned client through that client's local agent. This runs inside the assignment transaction, so a rotation failure rolls the assignment back.
4. **Cookie + redirect.** Signs a `lablink_session` cookie bound to the `session_id` and redirects to [`/desktop`](#the-participant-desktop).

**Success Response:**

- **Code:** `302 Found` → `/desktop`, with the `lablink_session` cookie set.

**Error Response:**

- **Code:** `503 Service Unavailable` — `no_seats.html` when the pool is empty, or `rotation_failed.html` when the assigned client could not be reached. On a rotation failure the seat is released and the VM flagged `Unhealthy` so the participant isn't wedged on a dead machine.
- **Code:** `200 OK` — `index.html` re-rendered with an error if `email` is missing.

The participant supplies nothing but an email address — the old `crd_command` and
PIN contract is gone, along with the mechanism behind it
([Database](database.md#triggers)).

### The participant desktop

**Endpoint:** `GET /desktop`

**Authentication:** The signed `lablink_session` cookie.

Renders the noVNC viewer page. Reads the cookie minted by `/api/request_vm`, looks
up the assigned VM by `session_id`, and configures the viewer from the persisted
`browser_ws_url` and `browser_credential`. If the cookie is missing, invalid, or the
bound VM is no longer running, it redirects to `/` so the participant can submit
their email again.

### Internal proxy authorization

**Endpoints:** `GET|POST /internal/proxy_auth`, `GET|POST /internal/tunnel_auth`

**Authentication:** None — these are `auth_request` subrequest targets for the
allocator's own nginx and are never routed publicly.

nginx calls these before proxying desktop bytes, to check that the requesting
session is entitled to the client it is asking for. `tunnel_auth` is the
equivalent gate for reverse-tunnel clients.

## Health

### Readiness Check

**Endpoint:** `GET /api/health`

**Authentication:** None — this is what load balancers, `lablink deploy` and
`lablink status` poll.

Returns a structured readiness report rather than a bare 200. The `checks` map
always covers `database`, `scheduler` and `reboot_service`, and gains a `tailscale`
entry when the configured connectivity needs one, or a `tunnel` entry for
reverse-tunnel deployments.

**Success Response:**

- **Code:** `200 OK` when every gating check is `ok`
- **Content:**
  ```json
  {
    "status": "ready",
    "checks": {
      "database": "ok",
      "scheduler": "ok",
      "reboot_service": "ok"
    }
  }
  ```

**Error Response:**

- **Code:** `503 Service Unavailable` when a gating check fails.

!!! note "A dead client tunnel does not make the allocator unready"
    Unattached client tunnels are reported but deliberately don't gate readiness — a
    registering client is unattached until its tunnel comes up. The allocator's own
    dependencies (tunnel server, database) do gate.

### Connection Usage

**Endpoint:** `GET /api/health/connections`

**Authentication:** Admin (HTTP Basic) — the same gate as `/admin/*`.

Reports PostgreSQL connection usage against the server's configured maximum,
for checking headroom before scaling a deployment up.

`active_connections` counts client backends only — the things `max_connections`
bounds — excluding the background-worker rows `pg_stat_activity` also carries.
It includes the connection serving this request. `max_connections` is read from
PostgreSQL, so it tracks whatever is actually configured.

`idle_in_transaction` distinguishes a leaked pooled connection from ordinary
load; a non-zero value that doesn't fall back to zero is worth investigating.
It counts `idle in transaction (aborted)` too — an aborted-but-open transaction
pins locks just like a live one.

The same numbers appear on the [`/admin` panel](#admin-pages), which escalates
to a banner above 90%.

**Success Response:**

- **Code:** `200 OK`
- **Content:**
  ```json
  {
    "status": "ok",
    "active_connections": 61,
    "idle_in_transaction": 0,
    "max_connections": 300,
    "utilization_percent": 20.3,
    "level": "ok"
  }
  ```

`level` is `ok`, `warning` above 80% utilization, or `critical` above 90%. High
utilization still answers `200` — busy is not broken.

**Error Response:**

- **Code:** `503 Service Unavailable` with `{"status": "unavailable"}` when the
  numbers can't be read — the database isn't initialized yet, or the query
  failed (including a pool with no free connections).

## Client VM API Endpoints

These endpoints are used by client VMs to report to the allocator. They require that
client's own secret as a bearer token — see [Authentication](#authentication).

Clients only ever *report upward* through these; they are never told about an
assignment. The allocator pushes that the other way, by calling the client's local
agent (see [`/api/request_vm`](#request-a-vm) and
[Database](database.md#triggers)).

### Get Unassigned VM Count

Retrieves the number of available (unassigned) VMs.

**Endpoint:** `GET /api/unassigned_vms_count`

**Description:** Returns the current count of VMs that are running and not yet assigned to a user.

**Authentication:** None (health/monitoring)

**Request Body:** None

**Success Response:**

- **Code:** `200 OK`
- **Content:**
  ```json
  {
    "count": 5
  }
  ```

**Client Usage:** This endpoint is not used by the client service. It is intended for external monitoring or UI components on the allocator to display the number of available VMs.

### Update VM In-Use Status

Updates the "in-use" status of a VM.

**Endpoint:** `POST /api/update_inuse_status`

**Description:** Called by the client VM to indicate whether a user is actively using it.

**Authentication:** Client secret

**Request Body:** `application/json`

```json
{
  "hostname": "lablink-vm-prod-1",
  "status": true
}
```

**Success Response:**

- **Code:** `200 OK`
- **Content:**
  ```json
  {
    "message": "In-use status updated successfully."
  }
  ```

**Error Response:**

- **Code:** `400 Bad Request` if `hostname` or `status` is missing.
- **Code:** `500 Internal Server Error` on failure.

**Client Usage:**

- **When:** Called by the `update_inuse_status` service, which is started by `start.sh` and runs continuously.
- **How:** The service monitors for the presence of the research software process (e.g., `sleap`). When the process starts, it sends a POST request with `status: true`. When the process stops, it sends `status: false`. This allows the allocator to know if a user is actively using the VM.

### Update GPU Health

Updates the GPU health status of a VM.

**Endpoint:** `POST /api/gpu_health`

**Description:** Called by the client VM to report its GPU health status.

**Authentication:** Client secret

**Request Body:** `application/json`

```json
{
  "hostname": "lablink-vm-prod-1",
  "gpu_status": "healthy"
}
```

**Success Response:**

- **Code:** `200 OK`
- **Content:**
  ```json
  {
    "message": "GPU health status updated successfully."
  }
  ```

**Error Response:**

- **Code:** `400 Bad Request` if `hostname` or `gpu_status` is missing.
- **Code:** `500 Internal Server Error` on failure.
  **Client Usage:**
- **When:** Called by the `check_gpu` service, which is started by `start.sh` and runs continuously.
- **How:** The service periodically runs `nvidia-smi`. Based on the output, it determines the GPU status (`Healthy`, `Unhealthy`, or `N/A`) and sends a POST request to the allocator whenever the status changes.

### Update VM Status

Updates the overall status of a VM (e.g., `initializing`, `running`, `error`, `rebooting`).

**Endpoint:** `POST /api/vm-status`

**Description:** Called by the client VM during its startup sequence to report its current status.

**Authentication:** Client secret

**Request Body:** `application/json`

```json
{
  "hostname": "lablink-vm-prod-1",
  "status": "running"
}
```

**Success Response:**

- **Code:** `200 OK`
- **Content:**
  ```json
  {
    "message": "VM status updated successfully."
  }
  ```

**Error Response:**

- **Code:** `400 Bad Request` if `hostname` or `status` is missing.
- **Code:** `500 Internal Server Error` on failure.
  **Client Usage:** This endpoint is not called from the `packages/client` code. Instead, it is called by the `user_data.sh` script during the client VM's initial boot sequence (cloud-init). This script reports `initializing`, `running`, and `error` statuses to the allocator, allowing it to track the VM's progress before the client service container has started. An error trap in `user_data.sh` automatically sends an `error` status if any command fails, which can then trigger the auto-reboot service.

### Receive VM Metrics

Receives and stores startup metrics from a VM.

**Endpoint:** `POST /api/vm-metrics/<hostname>`

**Description:** Called by the client VM's `user_data.sh` script to post timing metrics for `cloud-init` and container startup.

**Authentication:** Client secret

**URL Parameters:**

- `hostname` (string, required): The hostname of the VM reporting metrics.

  **Request Body:** `application/json`

  ```json
  {
    "cloud_init_start": 1678886400,
    "cloud_init_end": 1678886460,
    "cloud_init_duration_seconds": 60
  }
  ```

**Success Response:**

- **Code:** `200 OK`
- **Content:**
  ```json
  {
    "message": "VM metrics posted successfully."
  }
  ```

**Error Response:**

- **Code:** `404 Not Found` if the VM does not exist.
- **Code:** `500 Internal Server Error` on failure.

**Client Usage:**

- **When:** At the end of the client container's startup sequence.
- **How:** The `start.sh` script, which is the container's entrypoint, records its start and end times. It then sends a `curl` POST request with these timing metrics to the allocator. This helps in monitoring the duration of container startup.

### Receive VM Logs

Receives and stores logs pushed from a VM.

**Endpoint:** `POST /api/vm-logs/<hostname>`

**Description:** Receives batched log lines pushed from a VM by the `log_shipper.sh` script, which tails the VM's `cloud-init` output and the client container's Docker logs.

**Authentication:** Client secret

**Request Body:** `application/json`

```json
{
  "log_group": "/aws/ec2/lablink",
  "log_stream": "lablink-vm-prod-1",
  "messages": ["log line 1", "log line 2"]
}
```

**Success Response:**

- **Code:** `200 OK`
- **Content:**
  ```json
  {
    "message": "VM logs posted successfully."
  }
  ```

**Error Response:**

- **Code:** `400 Bad Request` if required fields are missing.
- **Code:** `404 Not Found` if the VM does not exist.
- **Code:** `500 Internal Server Error` on failure.

**Client Usage:** This endpoint is not called directly from any code in `packages/client`. The `log_shipper.sh` script, installed on each VM by the OpenTofu user-data script, tails the VM's `cloud-init` output log and the client container's Docker logs, batches new lines, and POSTs them to this endpoint using the API token as a Bearer credential.

## Admin API Endpoints

These endpoints require HTTP Basic Authentication and are intended for administrators to manage the VM pool.

### Launch VMs

**Endpoint:** `POST /api/launch`

**Description:** Takes a number of VMs to create, generates a OpenTofu variables file, and runs `tofu apply` to provision the new instances.

**Authentication:** HTTP Basic Auth

**Request Body:** `application/x-www-form-urlencoded`

- `num_vms` (integer, required): The number of new VMs to launch.

**Success Response:**

- **Code:** `200 OK`
- **Content:** An HTML page (`dashboard.html`) displaying the OpenTofu output and a real-time status monitor for the VMs.

**Error Response:**

- **Code:** `200 OK`
- **Content:** An HTML page (`dashboard.html`) displaying the OpenTofu error output.

### Destroy All VMs

**Endpoint:** `POST /destroy`

**Description:** Runs `tofu destroy` to terminate all EC2 instances and associated resources created by LabLink. It also clears all records from the `vms` table in the database. **This is a destructive action.** Driven by `lablink client destroy`, and by `lablink destroy` as its first teardown step.

**Authentication:** HTTP Basic Auth

**Request Body:** None

**Success Response:**

- **Code:** `200 OK`
- **Content:** An HTML page (`delete-dashboard.html`) displaying the OpenTofu output.

**Error Response:**

- **Code:** `200 OK`
- **Content:** An HTML page (`delete-dashboard.html`) displaying the OpenTofu error output.

### Get Status of All VMs

**Endpoint:** `GET /api/vm-status`

**Description:** Returns a JSON object mapping each VM hostname to its current status. Used by the admin dashboard.

**Authentication:** HTTP Basic Auth

**Request Body:** None

**Success Response:**

- **Code:** `200 OK`
- **Content:**
  ```json
  {
    "lablink-vm-prod-1": "running",
    "lablink-vm-prod-2": "initializing"
  }
  ```

**Error Response:**

- **Code:** `404 Not Found` if no VMs are found in the database.
- **Code:** `500 Internal Server Error` on failure.

### Get Logs for a Specific VM

**Endpoint:** `GET /api/vm-logs/<hostname>`

**Description:** Returns the stored logs for a specific VM. Used by the admin log viewer page.

**Authentication:** HTTP Basic Auth

**URL Parameters:**

- `hostname` (string, required): The hostname of the VM.
  **Request Body:** None

**Success Response:**

- **Code:** `200 OK`
- **Content:**
  ```json
  {
    "hostname": "lablink-vm-prod-1",
    "logs": "Starting cloud-init...\n..."
  }
  ```

**Error Response:**

- **Code:** `404 Not Found` if the VM is not found.
- **Code:** `503 Service Unavailable` if the logs are not yet available because the VM's log shipper has not started reporting yet.
- **Code:** `500 Internal Server Error` on failure.

### Get the Allocator's Own Logs

**Endpoint:** `GET /api/allocator-logs`

**Description:** Returns a redacted tail (last 2000 lines) of the allocator's own container output, read from the file `start.sh` writes at `/var/log/lablink/allocator.log`. Backs the `/admin/allocator-logs` page. Values of `PASSWORD`/`TOKEN`/`SECRET`/`KEY` assignments are masked before the response leaves the process.

**Authentication:** Admin HTTP Basic

**URL Parameters:** None

**Request Body:** None

**Success Response:**

- **Code:** `200 OK`
- **Content:**
  ```json
  {
    "cloud_init_logs": null,
    "docker_logs": "2026-08-03 12:00:00 - Starting nginx on :5000...",
    "error": null
  }
  ```

`cloud_init_logs` is always `null`: the allocator host's cloud-init output lives outside the container and is out of scope. When no log file exists, `docker_logs` is `null` and `error` explains why — the response is still `200`.

**Error Response:**

- **Code:** `401 Unauthorized` without admin credentials.

### Heartbeat

**Endpoint:** `POST /api/heartbeat`

**Description:** Periodic liveness ping. Lets the allocator detect silent failures — a dead container, a broken network, a hung host, an OOM, or an out-of-band VM termination — that no other endpoint would reveal. The body also carries cheap health signals for early warning.

**Authentication:** Client secret (resolved from the `vm_id` field)

**Request Body:** `application/json`

```json
{
  "vm_id": "lablink-vm-prod-1",
  "boot_id": "…",
  "disk_free_pct": 62
}
```

**Client Usage:** Sent by the client's `heartbeat` service every `HEARTBEAT_INTERVAL_SECONDS`. A client that stops heartbeating for longer than the staleness window becomes eligible for automatic recovery — see [Troubleshooting](troubleshooting.md#client-vms-aws-provider).

---

## Client Registration API

Used by bring-your-own (BYO) client machines to enrol themselves under the
`manual` provider. AWS-provisioned clients do not use these endpoints — OpenTofu
supplies their credentials directly.

Registration is what the CLI's `lablink client register` drives — see
[Bring-Your-Own Clients](cli/byo-clients.md#step-4-register-each-box) for the
operator-facing walkthrough, and
[Configuration](configuration.md#manual-provider-options-manual) for the `manual.*`
settings it depends on.

### Register a Client

**Endpoint:** `POST /api/v1/clients/register`

**Authentication:** Register token (the one deployment-wide bearer credential)

**Request Body:** `application/json`

| Field | Required | Description |
|---|---|---|
| `hostname` | yes | The client's self-declared hostname, which becomes its `client_id`. Must start with a letter or digit and contain only letters, digits, dots, dashes and underscores (max 253 chars). |
| `machine_identity` | yes | Stable machine identifier, unique across the deployment. Re-registering the same identity replaces the old row rather than adding a seat. |
| `provider` | no | Defaults to `aws`. BYO clients send `manual`. |
| `provider_metadata` | no | Shape must match the deployment's configured `manual.connectivity` — `lan_ip` for `lan_direct`, `overlay_hostname` for `mesh_overlay`, `reverse_tunnel: true` for `reverse_tunnel`. A mismatch is rejected here rather than failing opaquely at assignment time. |
| `endpoint_url`, `gpu_present`, `gpu_model` | no | Reported by the client; all auto-detected by the CLI. |

**Success Response:**

- **Code:** `200 OK`
- **Content:** the client's credentials and the configuration it needs to start:

```json
{
  "client_id": "gpu-box-3",
  "client_secret": "…",
  "agent_token": "…",
  "allocator_url": "https://lab.example.org",
  "connectivity": "lan_direct",
  "client_image": "ghcr.io/talmolab/lablink-client-base-image:latest",
  "repository": "https://github.com/talmolab/sleap-tutorial-data.git",
  "subject_software": "sleap",
  "register_token": "…",
  "startup_script_b64": "",
  "startup_on_error": "continue",
  "startup_max_attempts": 3,
  "startup_base_delay_seconds": 30,
  "startup_success_check_b64": "",
  "monitoring": { "enabled": false }
}
```

`client_secret` is returned **once** and stored only as an argon2 hash. Reverse-tunnel
registrations additionally receive `tunnel_url`, `tunnel_path_prefix` and
`tunnel_bind_addr`, all minted by the allocator.

**Error Response:**

- **Code:** `400 Bad Request` — missing/invalid `hostname` or `machine_identity`, or a `provider_metadata` shape that doesn't match the configured connectivity.
- **Code:** `401 Unauthorized` — bad or missing register token.

### Get Client Status

**Endpoint:** `GET /api/v1/clients/<client_id>/status`

**Authentication:** That client's own secret.

Lets a registered client confirm the allocator still knows about it.

### Unregister a Client

**Endpoint:** `DELETE /api/v1/clients/<client_id>`

**Authentication:** That client's own secret.

Removes the client's row. Driven by `lablink client unregister`, which calls this
best-effort — a client whose allocator is already gone still tears itself down
locally.

### List Clients

**Endpoint:** `GET /api/v1/clients`

**Authentication:** HTTP Basic Auth

Operator view of every registered client.

### Report Overlay Hostname

**Endpoint:** `POST /api/overlay-hostname`

**Authentication:** Client secret

A mesh-overlay client reports the tailnet hostname it actually joined under. This
matters because MagicDNS appends a numeric suffix when a name is already held by an
offline node, so the name the client *asked* for and the name it *got* can differ.

---

## Operations API

Long-running provisioning work runs asynchronously; these endpoints expose it.

### List Operations

**Endpoint:** `GET /api/operations`

**Authentication:** HTTP Basic Auth

Returns recent operations with their `op_type`, `status`, timestamps, and
`resources_completed` / `resources_total` progress counters.

### Get an Operation

**Endpoint:** `GET /api/operations/<operation_id>`

**Authentication:** HTTP Basic Auth

Returns one operation, including its captured `output` and `error`. This is what
the CLI polls while `client launch` runs.

---

## Scheduled Destruction API

Lets an operator schedule tear-down ahead of time — useful for capping the cost of
a workshop deployment.

| Endpoint | Method | Description |
|---|---|---|
| `/api/schedule-destruction` | `POST` | Create a schedule. |
| `/api/schedule-destruction` | `GET` | List schedules. |
| `/api/schedule-destruction/<schedule_id>` | `GET` | Fetch one schedule. |
| `/api/schedule-destruction/<schedule_id>` | `DELETE` | Cancel a schedule. |

**Authentication:** HTTP Basic Auth on all four.

Schedules are persisted in the `scheduled_destructions` table — see
[Database](database.md#scheduled_destructions-table).

---

## Session Metrics API

Populated only when `monitoring.enabled` is true.

### Report Session Metrics

**Endpoint:** `POST /api/session-metrics/<hostname>`

**Authentication:** Client secret

The client's monitoring sampler posts its accumulated per-session counters
(time-in-software, GPU activity, training progress).

### Get the Cohort Summary

**Endpoint:** `GET /api/session-metrics/summary`

**Authentication:** HTTP Basic Auth

Returns the aggregate view model — participation funnel plus cohort totals. Both
the admin **Session Metrics** page and `lablink stats` render this same payload, so
the two can never disagree.

### Export Metrics

**Endpoint:** `GET /api/export-metrics`

**Authentication:** HTTP Basic Auth

Per-VM metrics as CSV or JSON. Backs `lablink export-metrics --client`.

---

## Admin Pages

The allocator also serves operator HTML pages under `/admin`, all behind HTTP Basic
Auth. They are walked through in the [Workshop Guide](workshop-guide.md), and
`/admin/byo-onboarding` in [Bring-Your-Own Clients](cli/byo-clients.md#step-4-register-each-box).
Only the JSON APIs above are documented here.
