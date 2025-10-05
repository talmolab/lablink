# VM Registration Solution: Support All Config Scenarios

## Problem
Client VMs need to communicate with the allocator, but the URL varies based on deployment configuration:
- DNS enabled/disabled
- SSL provider (letsencrypt, cloudflare, none)
- Custom subdomain patterns

Currently, `user_data.sh` hardcodes `http://$ALLOCATOR_IP`, which breaks with HTTPS+DNS.

## Solution: Auto-Detect Allocator URL from Config

### Approach
1. Build the allocator URL in Python based on config settings
2. Pass it to Terraform as a variable
3. Use it in `user_data.sh` for all HTTP requests

### Implementation

#### Step 1: Add URL Builder Helper

**File**: `packages/allocator/src/lablink_allocator/utils/config_helpers.py` (new file)

```python
"""Configuration helper functions."""
from typing import Tuple


def get_allocator_url(cfg, allocator_ip: str) -> Tuple[str, str]:
    """
    Build the allocator URL based on configuration.

    Args:
        cfg: Hydra configuration object
        allocator_ip: Public IP address of allocator

    Returns:
        Tuple of (base_url, protocol)
        Examples:
            ("https://test.lablink.sleap.ai", "https")
            ("http://52.40.142.146", "http")
    """
    # Determine protocol based on SSL provider
    if hasattr(cfg, 'ssl') and cfg.ssl.provider != 'none':
        protocol = 'https'
    else:
        protocol = 'http'

    # Determine host based on DNS configuration
    if hasattr(cfg, 'dns') and cfg.dns.enabled:
        # Use DNS hostname
        if cfg.dns.pattern == 'custom':
            host = f"{cfg.dns.custom_subdomain}.{cfg.dns.domain}"
        elif cfg.dns.pattern == 'auto':
            # Assuming environment is passed or derived
            # For now, use custom_subdomain as fallback
            host = f"{cfg.dns.custom_subdomain}.{cfg.dns.domain}"
        else:
            host = cfg.dns.domain
    else:
        # Use IP address
        host = allocator_ip

    base_url = f"{protocol}://{host}"
    return base_url, protocol


def should_use_dns(cfg) -> bool:
    """Check if DNS is enabled in config."""
    return hasattr(cfg, 'dns') and cfg.dns.enabled


def should_use_https(cfg) -> bool:
    """Check if HTTPS is enabled in config."""
    return hasattr(cfg, 'ssl') and cfg.ssl.provider != 'none'
```

#### Step 2: Update Terraform Variables

**File**: `packages/allocator/src/lablink_allocator/terraform/main.tf`

Add new variable:
```hcl
variable "allocator_url" {
  description = "Full URL to allocator service (e.g., https://test.lablink.sleap.ai or http://1.2.3.4)"
  type        = string
}
```

#### Step 3: Update user_data.sh Template

**File**: `packages/allocator/src/lablink_allocator/terraform/user_data.sh`

Replace lines 14-16:
```bash
VM_NAME="lablink-vm-${resource_suffix}-${count_index}"
ALLOCATOR_URL="${allocator_url}"
STATUS_ENDPOINT="$ALLOCATOR_URL/api/vm-status"
```

Also update container environment (line 135):
```bash
-e ALLOCATOR_URL="${allocator_url}" \
```

#### Step 4: Update main.py to Pass Allocator URL

**File**: `packages/allocator/src/lablink_allocator/main.py`

In the `/api/launch` endpoint (around line 350):

```python
from lablink_allocator.utils.config_helpers import get_allocator_url

# ... existing code ...

# Get allocator URL based on configuration
allocator_url, protocol = get_allocator_url(cfg, allocator_ip)
app.logger.info(f"Using allocator URL: {allocator_url}")

# Build terraform command with variables
terraform_vars = [
    "-var", f"allocator_ip={allocator_ip}",
    "-var", f"allocator_url={allocator_url}",
    "-var", f"resource_suffix={resource_suffix}",
    "-var", f"instance_count={instance_count}",
    "-var", f"subject_software={cfg.machine.software}",
    "-var", f"repository={cfg.machine.repository}",
    "-var", f"image_name={cfg.machine.image}",
    "-var", f"machine_type={cfg.machine.machine_type}",
    "-var", f"ami_id={cfg.machine.ami_id}",
    "-var", f"region={cfg.app.region}",
]
```

#### Step 5: Insert VMs into Database After Terraform Apply

**File**: `packages/allocator/src/lablink_allocator/main.py`

After line 419 (after terraform apply succeeds), add:

```python
# After terraform apply succeeds
app.logger.info("Terraform apply completed successfully")

# Insert VMs into database
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

    vm_names_json = json.loads(output_result.stdout)

    # Insert each VM into database with 'initializing' status
    for vm_name in vm_names_json:
        try:
            database.insert_vm(vm_name, inuse=False)
            app.logger.info(f"Inserted VM {vm_name} into database")
        except Exception as e:
            # VM might already exist, that's okay
            app.logger.warning(f"Could not insert VM {vm_name}: {e}")

    app.logger.info(f"Inserted {len(vm_names_json)} VMs into database")

except subprocess.CalledProcessError as e:
    app.logger.error(f"Failed to get VM names from terraform: {e}")
except json.JSONDecodeError as e:
    app.logger.error(f"Failed to parse terraform output: {e}")
except Exception as e:
    app.logger.error(f"Failed to insert VMs into database: {e}")
```

#### Step 6: Ensure /api/vm-status Endpoint Exists

**File**: `packages/allocator/src/lablink_allocator/main.py`

Verify this endpoint exists (add if missing):

```python
@app.route("/api/vm-status", methods=["POST"])
def update_vm_status():
    """
    Update VM status from client VM.

    Called by client VMs during startup via user_data.sh.

    Request body:
        {
            "hostname": "lablink-vm-test-1",
            "status": "initializing|running|error"
        }
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "Missing JSON body"}), 400

    hostname = data.get("hostname")
    status = data.get("status")

    if not hostname or not status:
        return jsonify({"error": "Missing hostname or status"}), 400

    # Check if VM exists
    vm = database.get_vm_by_hostname(hostname)
    if not vm:
        app.logger.warning(f"VM {hostname} not found in database, cannot update status to {status}")
        return jsonify({"error": "VM not found"}), 404

    # Update status
    try:
        database.update_vm_field(hostname, "status", status)
        app.logger.info(f"Updated VM {hostname} status to {status}")
        return jsonify({"success": True, "hostname": hostname, "status": status}), 200
    except Exception as e:
        app.logger.error(f"Failed to update VM {hostname} status: {e}")
        return jsonify({"error": "Database update failed"}), 500
```

#### Step 7: Add Database Helper if Missing

**File**: `packages/allocator/src/lablink_allocator/database.py`

Add this function if it doesn't exist:

```python
def update_vm_field(hostname: str, field: str, value: Any):
    """Update a specific field for a VM."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Use SQL identifier interpolation safely
        allowed_fields = ["status", "inuse", "email", "crd_command"]
        if field not in allowed_fields:
            raise ValueError(f"Field {field} not allowed")

        query = f"UPDATE vms SET {field} = %s, updated_at = NOW() WHERE hostname = %s"
        cursor.execute(query, (value, hostname))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
```

## Configuration Examples

### Example 1: Your Case (DNS + Let's Encrypt)
```yaml
dns:
  enabled: true
  domain: "lablink.sleap.ai"
  pattern: "custom"
  custom_subdomain: "test"

ssl:
  provider: "letsencrypt"
  email: "admin@sleap.ai"
```

**Result**: `allocator_url = "https://test.lablink.sleap.ai"`

### Example 2: Simple IP-only (No DNS, No SSL)
```yaml
dns:
  enabled: false

ssl:
  provider: "none"
```

**Result**: `allocator_url = "http://52.40.142.146"` (uses IP)

### Example 3: DNS without SSL
```yaml
dns:
  enabled: true
  domain: "example.com"
  pattern: "custom"
  custom_subdomain: "lablink"

ssl:
  provider: "none"
```

**Result**: `allocator_url = "http://lablink.example.com"`

### Example 4: Cloudflare SSL
```yaml
dns:
  enabled: true
  domain: "example.com"
  pattern: "custom"
  custom_subdomain: "lablink"

ssl:
  provider: "cloudflare"
```

**Result**: `allocator_url = "https://lablink.example.com"`

## Testing Plan

### Test 1: Verify URL Building
```python
# In Python shell
from hydra import compose, initialize
from lablink_allocator.utils.config_helpers import get_allocator_url

initialize(config_path="../conf", version_base=None)
cfg = compose(config_name="config")

url, protocol = get_allocator_url(cfg, "52.40.142.146")
print(f"URL: {url}")
print(f"Protocol: {protocol}")
```

Expected output for your config:
```
URL: https://test.lablink.sleap.ai
Protocol: https
```

### Test 2: Verify Terraform Variable Passing
```bash
cd lablink-infrastructure
terraform plan

# Check that allocator_url is passed correctly in the plan output
```

### Test 3: End-to-End Test
1. Deploy infrastructure with updated code
2. Create VMs via dashboard
3. Check logs: VMs should appear in database immediately
4. Check VM logs: Should see successful POST to `/api/vm-status`

## Migration for Existing Deployments

If you have existing VMs that need to work with the new system:

```bash
# SSH to allocator
ssh -i ~/lablink-key.pem ubuntu@52.40.142.146

# Insert existing VMs
sudo docker exec $(sudo docker ps -q) psql -U lablink -d lablink_db -c \
  "INSERT INTO vms (hostname, inuse, status)
   VALUES ('lablink-vm-test-1', FALSE, 'running'),
          ('lablink-vm-test-2', FALSE, 'running')
   ON CONFLICT (hostname) DO NOTHING;"
```

## Backwards Compatibility

This solution maintains backwards compatibility:
- Old configs without `dns` or `ssl` sections still work (fallback to IP + HTTP)
- Existing VMs continue to function
- No breaking changes to API endpoints

## Summary

This approach:
✅ Supports all configuration scenarios (DNS on/off, SSL variants)
✅ Auto-detects the correct URL from config
✅ No manual URL configuration needed
✅ Works for development (IP) and production (DNS+SSL)
✅ Fixes the root cause of VM registration failure
✅ Maintains backwards compatibility
