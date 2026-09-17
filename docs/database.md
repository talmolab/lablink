# Database Management

This guide covers the PostgreSQL database used by LabLink, including schema, management tasks, and troubleshooting.

!!! note "Who this page is for"
    This is an internal reference for LabLink contributors and for
    troubleshooting a running deployment. If you are deploying LabLink for
    your research software, the only database setting you touch is
    `db.password` — see [Configuration](configuration.md#database-options-db).

## Database Overview

LabLink uses **PostgreSQL** for:

- Tracking VM states (`initializing`, `running`, `error`, `rebooting`; the status endpoint also accepts `unknown`, but nothing writes it)
- Storing seat assignments, and claiming them atomically so concurrent requesters can't collide
- Holding per-session browser state (session IDs, rotated VNC credentials)
- Registration records and hashed secrets for BYO clients
- Async operation and scheduled-destruction bookkeeping
- Session metrics, when `monitoring.enabled` is set

**Version**: PostgreSQL 17
**Location**: Runs in allocator Docker container
**Access**: Port 5432 (internal)

## Database Schema

The schema is created once, at container start, by `generate-init-sql` writing
`init.sql` for Postgres' bootstrap step. There are four tables.

!!! note "One-time-use database"
    A LabLink database is created fresh for each deployment and thrown away with it,
    so there is no migration machinery. New schema goes in `generate_init_sql.py`,
    not into a runtime upgrade path.

### `vms` Table

The main table. One row per client machine, whether it was provisioned by OpenTofu
or registered itself as a BYO box. The table name is fixed: `vms`.

It carries five groups of columns:

**Identity and assignment**

| Column | Type | Description |
|---|---|---|
| `HostName` | VARCHAR(1024) PK | Hostname / instance ID |
| `UserEmail` | VARCHAR(1024) | Assigned participant, `NULL` when free |
| `InUse` | BOOLEAN NOT NULL | Whether the configured software is actively running |
| `Healthy` | VARCHAR(1024) | `Healthy`, `Unhealthy`, `N/A`, or `NULL` |
| `Status` | VARCHAR(1024) | `initializing`, `running`, `error`, `rebooting`; `unknown` is accepted by the API but never written |
| `CreatedAt` | TIMESTAMP | Row creation time |
| `last_release_time` | TIMESTAMP | Indexed for assignment ordering, but currently never written |

**Provider and connectivity** — how the allocator reaches this machine

| Column | Type | Description |
|---|---|---|
| `provider` | TEXT NOT NULL | `aws` or `manual`. Defaults to `aws` |
| `machine_identity` | TEXT | Stable machine ID, unique where non-NULL. Lets a BYO box re-register without consuming a second seat |
| `endpoint_url` | TEXT | Reported endpoint, if any |
| `provider_metadata` | JSONB NOT NULL | Connectivity-specific payload: `lan_ip`, `overlay_hostname`, or the reverse-tunnel alias octet and path prefix |
| `client_secret_hash` | TEXT | Argon2 hash of this client's own secret |
| `gpu_present` | BOOLEAN | Whether a GPU was detected |
| `gpu_model` | TEXT | Reported GPU model |

**Browser session** — per-assignment state, rewritten on each new session

| Column | Type | Description |
|---|---|---|
| `SessionId` | UUID | Per-session ID, unique where non-NULL. Bound to the `lablink_session` cookie |
| `BrowserToken` | TEXT | Per-session token, unique where non-NULL |
| `VncPassword` | TEXT | Current KasmVNC password, rotated at assignment |
| `browser_ws_url` | TEXT | The URL the viewer page opens |
| `browser_credential` | TEXT | Sent as HTTP Basic by the viewer, when required |
| `Upstream` | TEXT | Proxy upstream for this client |
| `SessionStartedAt` | TIMESTAMPTZ | Session start |
| `AdminReservedAt` | TIMESTAMPTZ | Set while an admin holds the VM for troubleshooting |

**Liveness and recovery**

| Column | Type | Description |
|---|---|---|
| `last_seen_at` | TIMESTAMP | Last heartbeat |
| `boot_id` | VARCHAR(64) | Changes across reboots, so a silent restart is detectable |
| `disk_free_pct` | SMALLINT | Reported free disk percentage |
| `reboot_count` | INTEGER | Reboot attempts so far |
| `last_reboot_time` | TIMESTAMP | Last reboot attempt |

The last two are added by `ensure_reboot_columns()` at reboot-service startup, not
by `init.sql` — the one exception to the note above.

**Startup timings and logs**

`CloudInitLogs`, `DockerLogs`, and the `TofuApply*`, `CloudInit*`, `Container*`
and `TotalStartupDurationSeconds` timing columns, which break VM startup into its
OpenTofu / cloud-init / container-start phases for bottleneck analysis.

**Session metrics** — populated only when `monitoring.enabled` is true

The `SessionMetrics*`, `SecondsIn*`, `SecondsToFirst*`, `Gpu*`, `Vram*` and
`Training*` columns, plus `MaxLabeledFrames` — per-session time-in-software, GPU
activity and training-progress counters.

#### Indexes

```sql
CREATE UNIQUE INDEX vms_browser_token_idx     ON vms(BrowserToken)      WHERE BrowserToken IS NOT NULL;
CREATE UNIQUE INDEX vms_session_id_idx        ON vms(SessionId)         WHERE SessionId IS NOT NULL;
CREATE UNIQUE INDEX vms_machine_identity_idx  ON vms(machine_identity)  WHERE machine_identity IS NOT NULL;
CREATE INDEX        vms_provider_idx          ON vms(provider);
CREATE INDEX        vms_assignable_idx        ON vms(status, useremail, last_release_time)
    WHERE useremail IS NULL AND status = 'running' AND adminreservedat IS NULL;
```

`vms_assignable_idx` is the one that matters for assignment: it covers exactly the
rows a seat request can claim, so `assign_vm`'s `FOR UPDATE SKIP LOCKED` scan stays
cheap as the pool grows.

**`InUse` vs assignment.** `InUse` means *the configured software is running*, not
*a participant is assigned*. A participant can hold a seat with `InUse = FALSE`
if they haven't launched anything yet. It's maintained by the client's
`update_inuse_status` service.

### `operations` Table

Tracks asynchronous provisioning work so the CLI and admin UI can poll progress
instead of blocking on a long OpenTofu run.

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL PK | |
| `op_type` | VARCHAR(16) NOT NULL | `launch` or `destroy` |
| `status` | VARCHAR(16) NOT NULL | `queued`, `running`, `succeeded`, `failed`, or `interrupted` |
| `params` | TEXT | Serialized request parameters |
| `created_by` | VARCHAR(255) | Requesting admin |
| `created_at` | TIMESTAMP NOT NULL | Defaults to `NOW()` |
| `started_at` / `finished_at` | TIMESTAMP | Execution window |
| `output` / `error` | TEXT | Captured result |
| `resources_total` / `resources_completed` | INTEGER | Progress counters |

Exposed via [`/api/operations`](api-endpoints.md#provisioning-and-operations).
`idx_operations_created_at` supports recent-job listings. The partial unique
index `operations_single_flight` permits only one `queued` or `running` row, so
a second launch or destroy request cannot start concurrently.

### `scheduled_destructions` Table

Backs scheduled tear-down, so a workshop deployment can be capped ahead of time.

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL PK | |
| `schedule_name` | VARCHAR(255) NOT NULL UNIQUE | |
| `destruction_time` | TIMESTAMP NOT NULL | When to tear down |
| `recurrence_rule` | VARCHAR(255) | Optional recurrence |
| `created_by` | VARCHAR(255) | |
| `status` | VARCHAR(50) NOT NULL | Defaults to `scheduled` |
| `execution_count` | INTEGER | Defaults to 0 |
| `last_execution_time` | TIMESTAMP | |
| `last_execution_result` | TEXT | |
| `notification_enabled` | BOOLEAN | Defaults to `TRUE` |
| `notification_hours_before` | INTEGER | Defaults to 1 |
| `created_at` / `updated_at` | TIMESTAMP | Default `NOW()` |

Exposed via [`/api/schedule-destruction`](api-endpoints.md#scheduled-destruction-api).

### `settings` Table

A two-column key/value store (`key TEXT PRIMARY KEY`, `value TEXT NOT NULL`) for
deployment-wide state that has to survive a restart. Its main use is holding
`register_token_hash`, the argon2 hash of the deployment's register token, so
client registration can be verified without keeping the token in memory alone.

### Triggers

One, `scheduled_destructions_updated_at`, which maintains `updated_at` on that
table.

Seat assignment uses `FOR UPDATE SKIP LOCKED` in `/api/request_vm`; the
allocator then calls the assigned client's agent to rotate its VNC password.

## Accessing the Database

### Via SSH and psql

```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>

# Get container ID
CONTAINER_ID=$(sudo docker ps --filter "ancestor=ghcr.io/talmolab/lablink-allocator-image" --format "{{.ID}}")

# Access PostgreSQL
sudo docker exec -it $CONTAINER_ID psql -U lablink -d lablink_db
```

### Connection Parameters

The database identity is fixed — `lablink_db`, user `lablink`, on
`localhost:5432` inside the allocator container. Only the password comes
from [configuration](configuration.md#database-options-db):

```yaml
db:
  password: "<strong-private-password>"
```

## Common Database Operations

### View All VMs

```sql
SELECT * FROM vms;
```

### View Available VMs

A seat is claimable when it is `running`, unassigned, and not reserved by an admin —
the same predicate `vms_assignable_idx` covers.

```sql
SELECT hostname, status, gpu_model, createdat
FROM vms
WHERE status = 'running' AND useremail IS NULL AND adminreservedat IS NULL
ORDER BY createdat;
```

### View Assigned VMs

```sql
SELECT hostname, useremail, status, inuse, sessionstartedat
FROM vms
WHERE useremail IS NOT NULL
ORDER BY sessionstartedat DESC;
```

`inuse` tells you whether the configured software is actually running, which is not
the same as a seat being assigned.

### Count VMs by Status

```sql
SELECT status, COUNT(*) AS count
FROM vms
GROUP BY status;
```

Expected output:

```
 status       | count
--------------+-------
 running      |     8
 initializing |     1
 error        |     1
```

### Find a VM by Email

```sql
SELECT hostname, status, healthy, sessionstartedat
FROM vms
WHERE useremail = 'user@example.com';
```

### Release a Seat

Clearing the assignment and the per-session state returns a VM to the pool.
The allocator's `release_seat` does not update `last_release_time`:

```sql
UPDATE vms
SET useremail = NULL, sessionid = NULL, browsertoken = NULL,
    vncpassword = NULL, upstream = NULL, browser_ws_url = NULL,
    browser_credential = NULL, sessionstartedat = NULL,
    adminreservedat = NULL
WHERE hostname = 'i-0abc123def456';
```

### Clear a Stuck Unhealthy Flag

A single transient rotation failure can leave a client marked `Unhealthy`. The admin
UI exposes this as **clear-unhealthy**; the equivalent query is:

```sql
UPDATE vms SET healthy = NULL WHERE hostname = 'i-0abc123def456';
```

### View BYO Client Registrations

```sql
SELECT hostname, machine_identity, provider, gpu_model,
       provider_metadata, last_seen_at
FROM vms
WHERE provider = 'manual'
ORDER BY last_seen_at DESC NULLS LAST;
```

### Find Silent Clients

Clients that stopped heartbeating — the signal the recovery loop acts on:

```sql
SELECT hostname, status, last_seen_at, reboot_count
FROM vms
WHERE status = 'running'
  AND (last_seen_at IS NULL OR last_seen_at < NOW() - INTERVAL '3 minutes');
```

### Delete VM Record

```sql
DELETE FROM vms WHERE hostname = 'i-0abc123def456';
```

!!! warning
    Only delete after the VM instance is terminated in AWS.

## Troubleshooting

### PostgreSQL Won't Start

**Check logs**:

```bash
sudo docker logs lablink-allocator
```

If the log reports a full disk, check free space on the allocator host with
`df -h`. Keep the container and its data in place while investigating startup
errors; removing its volume deletes assignments and operation history.

### Cannot Connect to Database

**Check connection from allocator**:

```bash
sudo docker exec <container-id> pg_isready -U lablink
```

**Test connection**:

```bash
sudo docker exec <container-id> psql -U lablink -d lablink_db -c "SELECT 1;"
```

The production image currently copies its `pg_hba.conf` override to a
PostgreSQL 15 path, while the running cluster is PostgreSQL 17. Inspect the
active configuration inside the container rather than assuming the copied
file is in use.

### Restart PostgreSQL

If PostgreSQL needs a manual restart inside the allocator container:

```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>

# Access container
sudo docker exec -it <container-id> bash

# Inside container
pg_ctlcluster 17 main restart

# Verify
pg_isready -U lablink
```

## Security

The database is reachable only from inside the allocator container
(`localhost:5432`). Set a strong password through the deployment path as
described in [Security](security.md#database-password).

## Next Steps

- **[Troubleshooting](troubleshooting.md)**: Investigate deployment failures
- **[Security](security.md)**: Secure database access
- **[Architecture](architecture.md)**: Understand database role
