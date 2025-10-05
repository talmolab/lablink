# VM Registration Fix Plan

## Problem Summary

Client VMs created via Terraform are not appearing in the allocator database. Your colleague has identified the root cause:

**Root Cause**: Client VMs use HTTP requests to IP addresses for status updates, but the allocator now uses HTTPS with DNS. The requests from `user_data.sh` are failing silently.

## Evidence

1. **Allocator logs**: No POST requests received at `/api/vm-status` endpoint
2. **Client VM behavior**: VMs are created successfully but never register
3. **Error pattern**: 404 errors for VMs `lablink-vm-test-1` and `lablink-vm-test-2`

```
2025-10-04 22:51:19 - lablink_allocator.main - ERROR - VM with log stream lablink-vm-test-1 does not exist.
```

## Current Code Issues

### Issue 1: HTTP instead of HTTPS in user_data.sh

**File**: `packages/allocator/src/lablink_allocator/terraform/user_data.sh`

**Current code** (line 16):
```bash
STATUS_ENDPOINT="http://$ALLOCATOR_IP/api/vm-status"
```

**Problem**: Uses HTTP instead of HTTPS when DNS is enabled.

### Issue 2: IP address instead of DNS hostname

**Current code** (line 15):
```bash
ALLOCATOR_IP="${allocator_ip}"
```

**Problem**: Uses IP address, but SSL certificates are issued for the DNS hostname (`test.lablink.sleap.ai`), not the IP.

### Issue 3: Missing VM insertion in /api/launch

**File**: `packages/allocator/src/lablink_allocator/main.py` (lines 402-419)

**Problem**: After `terraform apply` succeeds, the code never inserts VMs into the database.

**Current flow**:
```
/api/launch → terraform apply → render dashboard ❌ (missing DB insert)
```

**Expected flow**:
```
/api/launch → terraform apply → insert VMs to DB → render dashboard ✓
```

## Proposed Solution

### Fix 1: Pass DNS hostname and protocol to client VMs

**Update `user_data.sh` template variables**:

Add new terraform variables in `packages/allocator/src/lablink_allocator/terraform/main.tf`:

```hcl
variable "allocator_hostname" {
  description = "DNS hostname for allocator (e.g., test.lablink.sleap.ai)"
  type        = string
  default     = ""
}

variable "use_https" {
  description = "Whether to use HTTPS for allocator communication"
  type        = bool
  default     = false
}
```

**Update `user_data.sh`** (line 16):

```bash
# Determine protocol and host based on configuration
%{ if use_https }
ALLOCATOR_HOST="${allocator_hostname}"
PROTOCOL="https"
%{ else }
ALLOCATOR_HOST="${allocator_ip}"
PROTOCOL="http"
%{ endif }

STATUS_ENDPOINT="$PROTOCOL://$ALLOCATOR_HOST/api/vm-status"
```

**Update container environment** (line 135):

```bash
-e ALLOCATOR_HOST="${use_https ? allocator_hostname : allocator_ip}" \
-e ALLOCATOR_PROTOCOL="${use_https ? "https" : "http"}" \
```

### Fix 2: Pass variables from allocator config

**Update `packages/allocator/src/lablink_allocator/main.py`** in `/api/launch` endpoint:

Read DNS configuration and pass to terraform:

```python
# Around line 350-360
dns_enabled = cfg.dns.enabled if hasattr(cfg, 'dns') else False
allocator_hostname = cfg.dns.domain if dns_enabled else ""
use_https = cfg.ssl.provider != "none" if hasattr(cfg, 'ssl') else False

terraform_vars = [
    "-var", f"allocator_ip={allocator_ip}",
    "-var", f"allocator_hostname={allocator_hostname}",
    "-var", f"use_https={use_https}",
    # ... other variables
]
```

### Fix 3: Insert VMs into database after terraform apply

**Update `packages/allocator/src/lablink_allocator/main.py`** after line 419:

```python
# After terraform apply succeeds, insert VMs into database
try:
    # Get VM names from terraform output
    output_cmd = ["terraform", "output", "-json", "vm_instance_names"]
    output_result = subprocess.run(
        output_cmd,
        cwd=TERRAFORM_DIR,
        check=True,
        capture_output=True,
        text=True
    )
    vm_names = json.loads(output_result.stdout)

    # Insert each VM into database with 'initializing' status
    for vm_name in vm_names:
        database.insert_vm(vm_name, status="initializing")
        app.logger.info(f"Inserted VM {vm_name} into database with status 'initializing'")

except subprocess.CalledProcessError as e:
    app.logger.error(f"Failed to get VM names from terraform: {e}")
except Exception as e:
    app.logger.error(f"Failed to insert VMs into database: {e}")
```

### Fix 4: Update /api/vm-status endpoint

**Verify endpoint exists and handles status updates** in `packages/allocator/src/lablink_allocator/main.py`:

```python
@app.route("/api/vm-status", methods=["POST"])
def update_vm_status():
    """Update VM status from client VM user_data.sh"""
    data = request.get_json()
    hostname = data.get("hostname")
    status = data.get("status")

    if not hostname or not status:
        return jsonify({"error": "Missing hostname or status"}), 400

    # Update status in database
    database.update_vm_status(hostname, status)

    return jsonify({"success": True, "hostname": hostname, "status": status}), 200
```

**Add corresponding database function** in `packages/allocator/src/lablink_allocator/database.py`:

```python
def update_vm_status(hostname: str, status: str):
    """Update VM status"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE vms SET status = %s, updated_at = NOW() WHERE hostname = %s",
            (status, hostname)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()
```

## Testing Plan

### Step 1: Test with current deployment

Before making code changes, verify the issue manually:

```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@52.40.142.146

# Manually insert VMs
sudo docker exec $(sudo docker ps -q) psql -U lablink -d lablink_db -c \
  "INSERT INTO vms (hostname, status) VALUES ('lablink-vm-test-1', 'initializing') ON CONFLICT DO NOTHING;"

sudo docker exec $(sudo docker ps -q) psql -U lablink -d lablink_db -c \
  "INSERT INTO vms (hostname, status) VALUES ('lablink-vm-test-2', 'initializing') ON CONFLICT DO NOTHING;"

# Verify in database
sudo docker exec $(sudo docker ps -q) psql -U lablink -d lablink_db -c "SELECT hostname, status FROM vms;"
```

This should make the VMs appear in the dashboard.

### Step 2: Test HTTPS connection from client VM

```bash
# SSH into one of the client VMs
ssh -i ~/lablink-key.pem ubuntu@<client-vm-ip>

# Test HTTPS connection to allocator
curl -X POST "https://test.lablink.sleap.ai/api/vm-status" \
  -H "Content-Type: application/json" \
  -d '{"hostname": "lablink-vm-test-1", "status": "running"}' \
  -v
```

Expected: Should succeed with 200 OK.

### Step 3: Implement fixes and redeploy

1. Make code changes as outlined above
2. Build new Docker image
3. Deploy updated infrastructure
4. Create new test VMs
5. Verify VMs appear in database automatically

## Implementation Order

1. **Fix 3 first** (database insertion) - Easiest and provides immediate value
2. **Fix 4** (vm-status endpoint) - Ensures status updates work
3. **Fix 1 & 2** (HTTPS/DNS) - More complex, requires terraform changes

## Alternative: Quick Workaround

If you need VMs working immediately without code changes:

**Option A**: Disable SSL temporarily and use IP addresses
```yaml
# lablink-infrastructure/config/config.yaml
ssl:
  provider: "none"

dns:
  enabled: false
```

**Option B**: Add HTTP redirect or allow HTTP for /api/vm-status endpoint only

**Option C**: Manually insert VMs after creation (as shown in Testing Step 1)

## Questions for Discussion

1. **DNS hostname**: Confirm `test.lablink.sleap.ai` is the correct hostname
2. **SSL certificate**: Does it cover both the apex and www subdomain?
3. **Backwards compatibility**: Should we support both HTTP (for dev) and HTTPS (for prod)?
4. **Configuration**: Should `use_https` be auto-detected from `ssl.provider` or explicit?

## Expected Outcome

After implementing these fixes:

1. ✅ VMs are inserted into database immediately after terraform apply
2. ✅ Client VMs can communicate with allocator via HTTPS
3. ✅ Status updates from user_data.sh reach the allocator
4. ✅ VMs appear in the admin dashboard
5. ✅ Logs show successful registration
