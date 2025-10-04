# VM Registration Issue - Technical Analysis

**Date**: October 4, 2025
**Reporter**: Elizabeth
**Status**: Active Bug - VMs Cannot Register with Allocator

## Problem Summary

Client VMs created through the allocator web UI (`/admin` -> Create VMs) successfully deploy via Terraform but cannot register with the allocator database, causing them to be unavailable for assignment to users.

## Current Behavior

1. Admin creates VMs via web UI at `https://test.lablink.sleap.ai/admin`
2. Terraform successfully creates VMs (e.g., `lablink-vm-test-1`, `lablink-vm-test-2`)
3. VMs boot up and run cloud-init successfully
4. Client container starts and attempts to register via `/vm_startup` endpoint
5. **FAILURE**: `/vm_startup` returns HTTP 404 "VM not found"
6. VMs remain in limbo - created but not registered in database

## Root Cause

The `/api/launch` endpoint in `packages/allocator/src/lablink_allocator/main.py` runs Terraform to create VMs but **never inserts them into the PostgreSQL database**.

### Code Flow Analysis

**Step 1: Admin Creates VMs** (Working)
- Location: `packages/allocator/src/lablink_allocator/templates/create-instances.html:14`
- Action: Form submits to `/api/launch` with number of VMs

**Step 2: Terraform Execution** (Working)
- Location: `packages/allocator/src/lablink_allocator/main.py:323-425`
- Lines 402-405: Runs `terraform apply` successfully
- Creates VMs with names like `lablink-vm-test-1`, `lablink-vm-test-2`
- **MISSING**: No code to insert VM hostnames into database after terraform succeeds

**Step 3: VM Registration Attempt** (Failing)
- Location: `packages/allocator/src/lablink_allocator/main.py:459-476`
- Client VM POSTs to `/vm_startup` with hostname
- Line 467-470: Checks if VM exists in database via `database.get_vm_by_hostname(hostname)`
- **FAILURE**: Returns 404 because VM was never inserted

### Relevant Code Sections

#### `/api/launch` endpoint (main.py:323-425)
```python
@app.route("/api/launch", methods=["POST"])
@auth.login_required
def launch():
    # ... validation and setup ...

    # Line 402-405: Run Terraform
    result = subprocess.run(
        apply_cmd, cwd=TERRAFORM_DIR, check=True, capture_output=True, text=True
    )

    # Line 407-408: Format output
    clean_output = ANSI_ESCAPE.sub("", result.stdout)

    # ❌ MISSING: Should query terraform outputs and insert VMs here

    # Line 410-417: Upload to S3 and return
    upload_to_s3(...)
    return render_template("dashboard.html", output=clean_output)
```

#### `/vm_startup` endpoint (main.py:459-476)
```python
@app.route("/vm_startup", methods=["POST"])
def vm_startup():
    data = request.get_json()
    hostname = data.get("hostname")

    if not hostname:
        return jsonify({"error": "Hostname is required."}), 400

    # Line 467-470: Check if VM exists
    vm = database.get_vm_by_hostname(hostname)
    if not vm:
        return jsonify({"error": "VM not found."}), 404  # ❌ FAILS HERE

    result = database.listen_for_notifications(
        channel=MESSAGE_CHANNEL, target_hostname=hostname
    )
    return jsonify(result), 200
```

## Historical Context

### Previous Implementation (May 2025 - Commit 5cf0c4a)
The `/vm_startup` endpoint **used to insert VMs** when they registered:

```python
@app.route("/vm_startup", methods=["POST"])
def vm_startup():
    # ...
    # Add to the database
    logger.debug(f"Adding VM {hostname} to database...")
    database.insert_vm(hostname=hostname)
    result = database.listen_for_notifications(...)
    return jsonify(result), 200
```

### Breaking Change (August 15, 2025 - Commit 1c7ca9c)
PR #136 "Add Each VM Log Streamed in the Admin Panel" changed `/vm_startup` to check for VM existence first:

```python
@app.route("/vm_startup", methods=["POST"])
def vm_startup():
    # ...
    # Check if the VM exists in the database
    vm = database.get_vm_by_hostname(hostname)
    if not vm:
        return jsonify({"error": "VM not found."}), 404  # ⚠️ NEW CHECK
```

**This change broke the registration flow** because:
1. VMs are created by Terraform
2. `/api/launch` doesn't insert them into database (this was never implemented)
3. `/vm_startup` now expects them to already exist
4. Registration fails with 404

## Affected Files

### Current Repository State
- `packages/allocator/src/lablink_allocator/main.py` - Missing database insertion in `/api/launch`
- `packages/allocator/src/lablink_allocator/database.py` - Has `insert_vm()` method but never called
- `packages/allocator/src/lablink_allocator/terraform/main.tf` - Creates VMs, no database logic
- `packages/allocator/src/lablink_allocator/terraform/outputs.tf` - Exposes `vm_instance_names` output

### Database Schema
```sql
CREATE TABLE IF NOT EXISTS vms (
    HostName VARCHAR(1024) PRIMARY KEY,
    Pin VARCHAR(1024),
    CrdCommand VARCHAR(1024),
    UserEmail VARCHAR(1024),
    InUse BOOLEAN NOT NULL DEFAULT FALSE,
    Healthy VARCHAR(1024),
    Status VARCHAR(1024),
    Logs TEXT
);
```

## Proposed Solution

Add database insertion logic to `/api/launch` endpoint after Terraform succeeds:

### Location
`packages/allocator/src/lablink_allocator/main.py`, after line 408

### Code to Add
```python
# Query terraform outputs and insert VMs into database
logger.debug("Querying terraform outputs for VM hostnames...")
try:
    output_result = subprocess.run(
        ["terraform", "output", "-json", "vm_instance_names"],
        cwd=TERRAFORM_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    import json
    vm_hostnames = json.loads(output_result.stdout)
    logger.debug(f"VM hostnames from terraform: {vm_hostnames}")

    # Insert new VMs into database
    for hostname in vm_hostnames:
        if not database.vm_exists(hostname):
            logger.debug(f"Inserting VM into database: {hostname}")
            database.insert_vm(hostname)
        else:
            logger.debug(f"VM already exists in database: {hostname}")

    logger.debug("Successfully inserted VMs into database")
except subprocess.CalledProcessError as e:
    logger.error(f"Error querying terraform outputs: {e}")
    # Don't fail the whole operation if we can't get outputs
except Exception as e:
    logger.error(f"Error inserting VMs into database: {e}")
    # Don't fail the whole operation if we can't insert
```

### Additional Changes Needed
Move `import json` to top of file with other imports (currently at line 3 area).

## Testing the Fix

1. Deploy updated allocator image with fix
2. Go to `https://test.lablink.sleap.ai/admin`
3. Create 2 VMs via web UI
4. Verify VMs appear in database:
   ```sql
   SELECT hostname FROM vms;
   ```
5. Verify client containers register successfully (check logs)
6. Verify VMs can be assigned to users via main page

## Temporary Workaround

For the 2 existing VMs (`lablink-vm-test-1`, `lablink-vm-test-2`), manually insert into database:

```bash
# SSH into allocator EC2 instance
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>

# Access PostgreSQL in Docker container
sudo docker exec -it <container-id> psql -U lablink -d lablink_db

# Insert VMs
INSERT INTO vms (hostname, inuse) VALUES ('lablink-vm-test-1', FALSE);
INSERT INTO vms (hostname, inuse) VALUES ('lablink-vm-test-2', FALSE);

# Verify
SELECT hostname, inuse FROM vms;
```

Then client VMs should be able to register on next attempt.

## Related Commits

- **5cf0c4a** (May 21, 2025): "Fix Startup API in the Allocator" - Original working version where `/vm_startup` inserted VMs
- **1c7ca9c** (August 15, 2025): "Add Each VM Log Streamed in the Admin Panel" - Broke registration by adding existence check
- **1d47121** (Recent): "feat: restructure packages and create infrastructure template" - Package restructure, preserved broken behavior

## Questions for Andrew

1. Was there a reason to change `/vm_startup` to check for existence instead of inserting VMs?
2. Was there supposed to be corresponding code in `/api/launch` to insert VMs that got missed?
3. How has this been working in production if VMs were never inserted after August 2025?
4. Should we:
   - Option A: Add insertion to `/api/launch` (preferred - explicit control)
   - Option B: Revert `/vm_startup` to auto-insert (simpler, original behavior)
   - Option C: Something else?

## Current Deployment Status

- **Allocator**: Running at `https://test.lablink.sleap.ai` (IP: 52.40.142.146)
- **Database**: PostgreSQL in Docker container on allocator instance
- **Client VMs**: 2 created (`lablink-vm-test-1`, `lablink-vm-test-2`) but not registered
- **Docker Image**: `ghcr.io/talmolab/lablink-allocator:linux-amd64-refactor-separate-infrastructure-repo-test`
- **Package Version**: `lablink-allocator==0.0.3a0`

## Next Steps

1. Andrew reviews this analysis and commit 1c7ca9c
2. Decide on fix approach (Option A vs B)
3. Implement fix in `packages/allocator/src/lablink_allocator/main.py`
4. Update tests in `packages/allocator/tests/test_api_calls.py`
5. Build new Docker image
6. Deploy and test
7. Apply temporary workaround for existing 2 VMs if needed immediately
