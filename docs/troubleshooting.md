# Troubleshooting

This guide covers common issues and their solutions when deploying and operating LabLink.

## General Troubleshooting Workflow

When encountering issues, follow this systematic approach:

1. **Initialize Terraform state locally** (if not already done)
2. **Plan terraform resources** using AWS CLI
3. **Apply changes**
4. **Retrieve PEM key** for SSH access
5. **Check admin website** or SSH into EC2 instance
6. **Review logs** for errors
7. **Destroy resources** when done troubleshooting

## Common Issues

### Docker and Installation

#### Docker Permission Error

**Error**:
```
Got permission denied while trying to connect to the Docker daemon socket
```

**Solution**:
```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Apply group changes
newgrp docker

# Verify
docker ps
```

#### Docker Daemon Not Running

**Error**:
```
Cannot connect to the Docker daemon at unix:///var/run/docker.sock
```

**Solution**:
```bash
# Start Docker (Linux)
sudo systemctl start docker
sudo systemctl enable docker

# macOS/Windows
# Start Docker Desktop application
```

### SSH Access Issues

#### Permission Denied (publickey)

**Error**:
```
Permission denied (publickey).
```

**Solutions**:

1. **Check key permissions**:
   ```bash
   chmod 600 ~/lablink-key.pem
   ls -l ~/lablink-key.pem
   # Should show: -rw-------
   ```

2. **Verify correct key**:
   ```bash
   # Extract key from Terraform
   cd lablink-infrastructure
   terraform output -raw private_key_pem > ~/lablink-key.pem
   chmod 600 ~/lablink-key.pem
   ```

3. **Check correct user**:
   ```bash
   # Try ubuntu user
   ssh -i ~/lablink-key.pem ubuntu@<ip>

   # Or ec2-user
   ssh -i ~/lablink-key.pem ec2-user@<ip>
   ```

4. **Verify security group allows SSH**:
   ```bash
   aws ec2 describe-security-groups --group-ids <sg-id> \
     --query 'SecurityGroups[0].IpPermissions[?FromPort==`22`]'
   ```

#### SSH Connection Timeout

**Error**:
```
ssh: connect to host X.X.X.X port 22: Connection timed out
```

**Solutions**:

1. **Verify security group allows port 22**:
   ```bash
   aws ec2 authorize-security-group-ingress \
     --group-id <sg-id> \
     --protocol tcp \
     --port 22 \
     --cidr 0.0.0.0/0
   ```

2. **Check instance is running**:
   ```bash
   aws ec2 describe-instances --instance-ids <instance-id> \
     --query 'Reservations[0].Instances[0].State.Name'
   ```

3. **Verify correct public IP**:
   ```bash
   terraform output ec2_public_ip
   ```

4. **Check network ACLs**:
   - Verify VPC network ACLs allow inbound/outbound on port 22

### Flask Server Problems

#### Cannot Access Web Interface

**Error**: Browser shows "Connection refused" or "Cannot connect"

**Solutions**:

1. **Check if container is running**:
   ```bash
   ssh -i ~/lablink-key.pem ubuntu@<ip>
   sudo docker ps
   ```

2. **View container logs**:
   ```bash
   sudo docker logs <container-id>

   # Follow logs in real-time
   sudo docker logs -f <container-id>
   ```

3. **Test locally from instance**:
   ```bash
   # From within the EC2 instance
   curl localhost:80
   ```

4. **Test connectivity from outside**:
   ```bash
   # From your local machine
   nc -vz <ec2-public-ip> 80

   # Or
   curl http://<ec2-public-ip>:80
   ```

5. **Check security group allows port 80**:
   ```bash
   aws ec2 authorize-security-group-ingress \
     --group-id <sg-id> \
     --protocol tcp \
     --port 80 \
     --cidr 0.0.0.0/0
   ```

#### Browser Cannot Access HTTP (Staging Mode)

**Symptoms**:
- Browser cannot connect to `http://your-domain.com` when using staging mode
- "This site can't be reached"
- "Connection refused"
- "ERR_CONNECTION_REFUSED"

**Cause**: Your browser previously accessed the site via HTTPS and cached the HSTS (HTTP Strict Transport Security) policy. This forces all future requests to automatically upgrade to HTTPS. Since staging mode only serves HTTP (port 443 is closed), the browser cannot connect.

**Solution - Clear HSTS Cache:**

**Chrome / Edge:**

1. Open a new tab and navigate to:
   ```
   chrome://net-internals/#hsts
   ```
   (For Edge use: `edge://net-internals/#hsts`)

2. Scroll down to "Delete domain security policies"

3. Enter your full domain name:
   ```
   test.lablink.sleap.ai
   ```

4. Click "Delete"

5. Access the site again, explicitly typing `http://`:
   ```
   http://test.lablink.sleap.ai
   ```

**Firefox:**

1. Close all Firefox windows

2. Navigate to your Firefox profile directory:
   - Windows: `%APPDATA%\Mozilla\Firefox\Profiles\`
   - macOS: `~/Library/Application Support/Firefox/Profiles/`
   - Linux: `~/.mozilla/firefox/`

3. Find your profile folder (e.g., `abc123.default-release`)

4. Delete the file: `SiteSecurityServiceState.txt`

5. Restart Firefox and access with `http://`:
   ```
   http://test.lablink.sleap.ai
   ```

**Safari:**

1. Close Safari completely

2. Open Terminal and run:
   ```bash
   rm ~/Library/Cookies/HSTS.plist
   ```

3. Restart Safari and access with `http://`:
   ```
   http://test.lablink.sleap.ai
   ```

**Quick Workarounds:**

If you don't want to clear HSTS cache:

1. **Use Incognito/Private Browsing**
   - HSTS cache doesn't apply in incognito mode
   - Access `http://test.lablink.sleap.ai`

2. **Access via IP Address**
   ```
   http://54.214.215.124
   ```
   (Find IP in Terraform outputs: `terraform output allocator_public_ip`)

3. **Use curl for testing**
   ```bash
   curl http://test.lablink.sleap.ai
   ```

**Verify Staging Mode is Working:**

```bash
# HTTP should return 200 OK
curl -I http://test.lablink.sleap.ai

# HTTPS should fail (connection refused)
curl -I https://test.lablink.sleap.ai
```

**Expected behavior**: When using staging mode (`ssl.staging: true`), your browser will show "Not Secure" in the address bar. This is normal and expected - staging mode uses unencrypted HTTP for testing.

To get a secure HTTPS connection, set `ssl.staging: false` in your configuration. See [Configuration - SSL Options](configuration.md#ssltls-options-ssl).

#### Flask App Not Starting

**Symptoms**: Container runs but Flask doesn't start

**Check**:

```bash
# View full logs
sudo docker logs <container-id>

# Look for errors like:
# - Port already in use
# - Module import errors
# - Configuration errors
```

**Solutions**:

1. **Restart container**:
   ```bash
   sudo docker restart <container-id>
   ```

2. **Check for port conflicts**:
   ```bash
   sudo netstat -tulpn | grep 5000
   ```

3. **Verify configuration**:
   ```bash
   sudo docker exec <container-id> cat /app/config/config.yaml
   ```

### PostgreSQL Issues

#### PostgreSQL Not Accessible

**Known Issue**: PostgreSQL server may need manual restart after first deployment.

**Solution**:
```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@<ec2-public-ip>

# Get container name
sudo docker ps

# Enter container
sudo docker exec -it <container-name> bash

# Inside container, restart PostgreSQL
/etc/init.d/postgresql restart

# Verify it's running
pg_isready -U lablink
```

**Verify manually**:
```bash
# Test connection
sudo docker exec <container-id> psql -U lablink -d lablink_db -c "SELECT 1;"
```

#### Database Connection Refused

**Error**: `psycopg2.OperationalError: could not connect to server`

**Solutions**:

1. **Check PostgreSQL is running**:
   ```bash
   sudo docker exec <container-id> pg_isready -U lablink
   ```

2. **Check PostgreSQL logs**:
   ```bash
   sudo docker exec <container-id> tail -f /var/log/postgresql/postgresql-*-main.log
   ```

3. **Verify configuration**:
   ```bash
   # Check pg_hba.conf
   sudo docker exec <container-id> cat /etc/postgresql/*/main/pg_hba.conf

   # Should contain:
   # host    all             all             0.0.0.0/0            md5
   ```

4. **Restart PostgreSQL** (see above)

### VM Spawning Issues

#### VMs Not Being Created

**Symptoms**: Click "Create VMs" but nothing happens

**Check**:

1. **Allocator container logs**:
   ```bash
   sudo docker logs -f <allocator-container-id>
   ```

2. **AWS credentials configured**:
   ```bash
   # Inside container
   sudo docker exec <container-id> aws sts get-caller-identity
   ```

3. **Terraform installed in container**:
   ```bash
   sudo docker exec <container-id> terraform version
   ```

**Solutions**:

1. **Set AWS credentials** (if not using IAM role):
   - Navigate to `/admin/set-aws-credentials` in web interface
   - Enter AWS access key and secret key
   - Submit

2. **Check Terraform errors**:
   ```bash
   # Inside container
   sudo docker exec <container-id> cat /tmp/terraform-*.log
   ```

3. **Verify IAM permissions**:
   - EC2 permissions (RunInstances, DescribeInstances)
   - VPC permissions (CreateSecurityGroup, etc.)

#### Terraform Apply Failed Inside Container

**Error**: Terraform operations fail when triggered from allocator

**Solutions**:

1. **Check AWS credentials**:
   ```bash
   sudo docker exec <container-id> env | grep AWS
   ```

2. **Test Terraform manually**:
   ```bash
   sudo docker exec -it <container-id> bash
   cd /app/.venv/lib/python*/site-packages/lablink_allocator/terraform
   terraform init
   terraform plan
   ```

3. **Verify Docker socket access** (if using Docker-in-Docker):
   ```bash
   sudo docker exec <container-id> docker ps
   ```

### Terraform Issues

#### Terraform Init Fails

**Error**: `Error configuring the backend "s3": ... bucket does not exist`

**Solution**:
```bash
# Create S3 bucket first
aws s3 mb s3://tf-state-lablink-allocator-bucket --region us-west-2

# Enable versioning
aws s3api put-bucket-versioning \
  --bucket tf-state-lablink-allocator-bucket \
  --versioning-configuration Status=Enabled

# Re-init
terraform init
```

#### Terraform State Locked

**Error**: `Error acquiring the state lock`

**Cause**: A previous Terraform operation didn't complete cleanly, leaving the state locked in DynamoDB.

**Diagnosis**:

1. **Identify the lock**:
   ```bash
   # Check for locks in DynamoDB
   aws dynamodb scan --table-name lock-table --region us-west-2
   ```

2. **Check if a process is actually running**:
   ```bash
   # Look for terraform processes
   ps aux | grep terraform

   # In allocator container
   sudo docker exec <container-id> ps aux | grep terraform
   ```

**Solutions**:

**Option 1: Unlock via AWS CLI** (Recommended - works from anywhere)

**Step 1:** First, scan the lock table to find the exact LockID:
```bash
# List all locks
aws dynamodb scan --profile <your-profile> --table-name lock-table --region us-west-2
```

**Step 2:** Look for entries with an `Info` field (these are actual locks, not just digests). Copy the exact `LockID` value.

**Step 3:** Delete the lock:

**Linux/macOS:**
```bash
aws dynamodb delete-item \
    --profile <your-profile> \
    --table-name lock-table \
    --key '{"LockID":{"S":"<exact-lock-id-from-scan>"}}' \
    --region us-west-2
```

**Windows PowerShell:**
```powershell
# Create key.json file with:
# {
#   "LockID": {
#     "S": "<exact-lock-id-from-scan>"
#   }
# }

aws dynamodb delete-item --profile <your-profile> --table-name lock-table --key file://key.json --region us-west-2
```

**Common lock paths:**
- Infrastructure: `tf-state-lablink-allocator-bucket/test/terraform.tfstate`
- Client VMs: `tf-state-lablink-allocator-bucket/test/client/terraform.tfstate`

Note: Lock IDs do NOT always have `-md5` suffix - use the exact value from the scan!

**Option 2: Unlock from allocator** (Requires DynamoDB IAM permissions)
```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>

# Enter container
sudo docker exec -it <container-id> bash

# Navigate to terraform directory
cd /app/lablink_allocator/terraform

# Force unlock (using lock ID from error message)
terraform force-unlock <lock-id>
```

**Common Error**: `AccessDeniedException: User is not authorized to perform: dynamodb:GetItem`

**Cause**: The allocator IAM role lacks DynamoDB permissions.

**Solution**: Ensure the allocator IAM role includes these permissions:
```json
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:DeleteItem"
  ],
  "Resource": "arn:aws:dynamodb:us-west-2:<account-id>:table/lock-table"
}
```

After updating IAM permissions, redeploy infrastructure for changes to take effect.

**Prevention**:
- Don't manually terminate EC2 instances while Terraform is running
- Always let Terraform operations complete fully
- Use destroy workflows instead of manual AWS console deletions
- Monitor allocator logs during VM creation/destruction

#### Resource Already Exists

**Error**: `Error creating ... already exists`

**Solutions**:

1. **Import existing resource**:
   ```bash
   terraform import aws_security_group.lablink sg-xxxxx
   terraform import aws_instance.lablink_allocator i-xxxxx
   ```

2. **Delete resource manually** (if safe):
   ```bash
   aws ec2 terminate-instances --instance-ids i-xxxxx
   aws ec2 delete-security-group --group-id sg-xxxxx
   ```

3. **Use different resource names**:
   - Change `resource_suffix` variable: `-dev`, `-test`, `-prod`

#### Cannot Destroy Resources

**Error**: Resources won't destroy cleanly

**Solution**:

1. **Destroy in order**:
   ```bash
   # Terminate instances first
   aws ec2 terminate-instances --instance-ids i-xxxxx

   # Wait for termination
   aws ec2 wait instance-terminated --instance-ids i-xxxxx

   # Delete security group
   aws ec2 delete-security-group --group-id sg-xxxxx
   ```

2. **Check dependencies**:
   - Network interfaces attached
   - Elastic IPs associated
   - Security group rules referencing each other

3. **Force destroy**:
   ```bash
   terraform destroy -auto-approve
   ```

### GitHub Actions Workflow Issues

#### Workflow Won't Trigger

**Check**:

1. **Workflow file syntax**:
   ```bash
   # Use YAML validator
   yamllint .github/workflows/*.yml
   ```

2. **Branch protection rules**:
   - Check repository settings
   - Ensure workflows are enabled

3. **Trigger conditions**:
   - Verify branch name matches trigger
   - Check file path filters

#### AWS Authentication Fails in Workflow

**Error**: `Error: Could not assume role with OIDC`

**Solutions**:

1. **Verify OIDC provider exists**:
   ```bash
   aws iam list-open-id-connect-providers
   ```

2. **Check IAM role trust policy**:
   ```bash
   aws iam get-role --role-name github-lablink-deploy \
     --query 'Role.AssumeRolePolicyDocument'
   ```

3. **Verify repository in trust policy**:
   - Trust policy must include: `repo:talmolab/lablink:*`

4. **Check role ARN in workflow**:
   - Ensure ARN matches your account ID

#### Terraform Apply Fails in Workflow

**Check workflow logs** for specific error:

1. **Permission errors**: Update IAM role permissions
2. **Resource limits**: Check AWS service quotas
3. **State lock**: Clear lock if safe

### Client VM Issues

#### Client VM Not Registering

**Symptoms**: VM created but doesn't appear in allocator database

**Root Cause**: VMs are not being inserted into the database after Terraform creates them.

**Step-by-Step Diagnosis**:

1. **Verify VMs were created by Terraform**:
   ```bash
   # Check terraform outputs from allocator
   ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>
   sudo docker exec <container-id> terraform -chdir=/app/.venv/lib/python*/site-packages/lablink_allocator/terraform output vm_instance_names
   ```

2. **Check if VMs exist in database**:
   ```bash
   # SSH into allocator
   ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>

   # Query database
   sudo docker exec <container-id> psql -U lablink -d lablink_db -c "SELECT hostname, inuse, status FROM vms;"
   ```

3. **Check client VM container logs**:
   ```bash
   ssh -i ~/lablink-key.pem ubuntu@<client-vm-ip>
   sudo docker logs <client-container-id>

   # Look for errors like:
   # "POST request failed with status code: 404"
   # "VM not found"
   ```

4. **Check allocator logs for /vm_startup requests**:
   ```bash
   ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>
   sudo docker logs <allocator-container-id> | grep vm_startup

   # Look for:
   # POST /vm_startup - 404 errors
   ```

5. **Test network connectivity**:
   ```bash
   # From client VM
   curl http://<allocator-ip>/vm_startup \
     -H "Content-Type: application/json" \
     -d '{"hostname": "lablink-vm-test-1"}'

   # Expected if VM not in DB: {"error":"VM not found."}
   # Expected if VM in DB: Success response
   ```

**Solutions**:

**Option A: Manual Database Insertion (Temporary Fix)**
```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>

# Get container ID
CONTAINER_ID=$(sudo docker ps -q)

# Insert VMs manually
sudo docker exec $CONTAINER_ID psql -U lablink -d lablink_db -c \
  "INSERT INTO vms (hostname, inuse) VALUES ('lablink-vm-test-1', FALSE);"

sudo docker exec $CONTAINER_ID psql -U lablink -d lablink_db -c \
  "INSERT INTO vms (hostname, inuse) VALUES ('lablink-vm-test-2', FALSE);"

# Verify
sudo docker exec $CONTAINER_ID psql -U lablink -d lablink_db -c \
  "SELECT hostname, inuse FROM vms;"
```

**Option B: Code Fix (Permanent Solution)**

The `/api/launch` endpoint needs to be updated to insert VMs after Terraform succeeds. See [VM_REGISTRATION_ISSUE.md](../VM_REGISTRATION_ISSUE.md) for details.

**After Fix - Verify Registration**:
```bash
# Watch client VM logs
ssh -i ~/lablink-key.pem ubuntu@<client-vm-ip>
sudo docker logs -f <client-container-id>

# Should see:
# "POST request was successful."
# "Received success response from server."
```

**Preventive Measures**:
- Always verify VMs appear in database after creation
- Check allocator logs during VM creation
- Monitor client VM registration within 5 minutes of creation

#### GPU Not Available

**Error**: `RuntimeError: CUDA not available`

**Check**:

1. **GPU instance type**:
   ```bash
   # Verify instance has GPU
   aws ec2 describe-instances --instance-ids <id> \
     --query 'Reservations[0].Instances[0].InstanceType'
   ```

2. **NVIDIA drivers installed**:
   ```bash
   ssh -i ~/lablink-key.pem ubuntu@<client-vm-ip>
   nvidia-smi
   ```

3. **Docker GPU support**:
   ```bash
   docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi
   ```

**Solution**:

1. **Use GPU-enabled AMI** or install drivers:
   ```bash
   # Ubuntu Deep Learning AMI
   ami_id = "ami-0c2b0d3fb02824d92"  # us-west-2
   ```

2. **Verify Docker GPU runtime**:
   ```bash
   cat /etc/docker/daemon.json
   # Should have: "default-runtime": "nvidia"
   ```

### DNS and Domain Issues

For detailed DNS configuration, see [DNS Configuration Guide](dns-configuration.md).

#### DNS Record Not Resolving

**Symptoms**: Domain doesn't resolve to allocator IP

**Step-by-Step Diagnosis**:

1. **Verify DNS is enabled in config**:
   ```bash
   cat lablink-infrastructure/config/config.yaml | grep -A 10 "^dns:"
   ```

2. **Check Route53 record exists**:
   ```bash
   aws route53 list-resource-record-sets \
     --hosted-zone-id Z010760118DSWF5IYKMOM \
     --query "ResourceRecordSets[?Name=='test.lablink.sleap.ai.']"
   ```

3. **Query authoritative nameservers directly**:
   ```bash
   # Should return the allocator IP
   nslookup test.lablink.sleap.ai ns-158.awsdns-19.com
   ```

4. **Check public DNS propagation**:
   ```bash
   # Google DNS
   nslookup test.lablink.sleap.ai 8.8.8.8

   # Cloudflare DNS
   nslookup test.lablink.sleap.ai 1.1.1.1

   # Local DNS
   nslookup test.lablink.sleap.ai
   ```

5. **Verify IP matches**:
   ```bash
   # Get terraform output
   cd lablink-infrastructure
   terraform output allocator_public_ip

   # Compare with DNS resolution
   dig test.lablink.sleap.ai +short
   ```

**Solutions**:

**If record doesn't exist**:
```bash
# Re-run terraform to create DNS record
cd lablink-infrastructure
terraform apply
```

**If DNS not propagating**:
- Wait 5-15 minutes for global propagation
- Check NS delegation is correct (see below)
- Try flushing local DNS cache:
  ```bash
  # macOS
  sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder

  # Linux
  sudo systemd-resolve --flush-caches

  # Windows
  ipconfig /flushdns
  ```

#### DNS Record in Wrong Zone

**Symptoms**: DNS record created in `sleap.ai` zone instead of `lablink.sleap.ai` zone

**Root Cause**: Terraform data source matched parent zone

**Diagnosis**:
```bash
# Check both zones
aws route53 list-resource-record-sets --hosted-zone-id <sleap.ai-zone-id> \
  --query "ResourceRecordSets[?contains(Name, 'lablink')]"

aws route53 list-resource-record-sets --hosted-zone-id Z010760118DSWF5IYKMOM \
  --query "ResourceRecordSets[?contains(Name, 'test')]"
```

**Solution**:

1. **Add zone_id to config.yaml**:
   ```yaml
   dns:
     enabled: true
     domain: "lablink.sleap.ai"
     zone_id: "Z010760118DSWF5IYKMOM"  # Force correct zone
     pattern: "custom"
     custom_subdomain: "test"
   ```

2. **Delete record from wrong zone** (if exists):
   ```bash
   # Use AWS console or CLI to delete A record from sleap.ai zone
   ```

3. **Re-run terraform**:
   ```bash
   cd lablink-infrastructure
   terraform apply
   ```

#### NS Delegation Not Working

**Symptoms**:
- nslookup returns Cloudflare nameservers instead of AWS
- DNS queries fail even though record exists in Route53

**Diagnosis**:
```bash
# Check NS delegation
dig NS lablink.sleap.ai

# Should show AWS nameservers:
# ns-158.awsdns-19.com
# ns-697.awsdns-23.net
# ns-1839.awsdns-37.co.uk
# ns-1029.awsdns-00.org
```

**Solution**:

1. **Get Route53 nameservers**:
   ```bash
   aws route53 get-hosted-zone --id Z010760118DSWF5IYKMOM \
     --query 'DelegationSet.NameServers'
   ```

2. **Add NS records in Cloudflare**:
   - Log into Cloudflare
   - Navigate to DNS for `sleap.ai`
   - Add 4 NS records:
     - Type: NS
     - Name: `lablink`
     - Content: Each of the 4 AWS nameservers
     - TTL: 300 (or Auto)

3. **Verify delegation**:
   ```bash
   # Wait 5-15 minutes, then check
   dig NS lablink.sleap.ai
   ```

4. **Test resolution**:
   ```bash
   # Should now resolve via AWS
   nslookup test.lablink.sleap.ai 8.8.8.8
   ```

#### HTTPS/SSL Certificate Not Working

**Symptoms**:
- HTTP works but HTTPS fails
- Browser shows "Connection refused" or "SSL error"

**Step-by-Step Diagnosis**:

1. **Check DNS is resolving**:
   ```bash
   nslookup test.lablink.sleap.ai 8.8.8.8
   # Must resolve before Let's Encrypt can issue certificate
   ```

2. **Check Caddy is running**:
   ```bash
   ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>
   sudo systemctl status caddy
   ```

3. **Check Caddy logs**:
   ```bash
   sudo journalctl -u caddy -f

   # Look for:
   # - "certificate obtained successfully" (success)
   # - "challenge failed" (DNS not ready)
   # - "timeout" (network issue)
   ```

4. **Test HTTPS manually**:
   ```bash
   curl -v https://test.lablink.sleap.ai

   # Look for SSL handshake or certificate errors
   ```

5. **Check ports are open**:
   ```bash
   # Port 80 (HTTP-01 challenge)
   nc -vz test.lablink.sleap.ai 80

   # Port 443 (HTTPS)
   nc -vz test.lablink.sleap.ai 443
   ```

**Solutions**:

**If DNS not propagated**:
- Wait 5-10 more minutes
- Verify DNS resolves to correct IP
- Caddy will automatically retry every 2 minutes

**If ports blocked**:
```bash
# Check security group
aws ec2 describe-security-groups \
  --filters "Name=tag:Name,Values=lablink-allocator-*" \
  --query 'SecurityGroups[0].IpPermissions'

# Add rules if missing
aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp \
  --port 80 \
  --cidr 0.0.0.0/0

aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp \
  --port 443 \
  --cidr 0.0.0.0/0
```

**If Caddy configuration error**:
```bash
# Check Caddyfile
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>
cat /etc/caddy/Caddyfile

# Should contain:
# test.lablink.sleap.ai {
#     reverse_proxy localhost:5000
# }

# Restart Caddy
sudo systemctl restart caddy
```

**Manual certificate check**:
```bash
# View certificate details
echo | openssl s_client -servername test.lablink.sleap.ai \
  -connect test.lablink.sleap.ai:443 2>/dev/null | \
  openssl x509 -noout -text

# Check issuer and expiration
echo | openssl s_client -servername test.lablink.sleap.ai \
  -connect test.lablink.sleap.ai:443 2>/dev/null | \
  openssl x509 -noout -issuer -dates
```

#### Multiple Hosted Zones Causing Conflicts

**Symptoms**: Unpredictable DNS behavior, records in multiple zones

**Diagnosis**:
```bash
# List all zones
aws route53 list-hosted-zones --query 'HostedZones[*].[Name,Id]' --output table

# Check for duplicates or parent/child conflicts
```

**Solution**:

1. **Identify which zone to keep**:
   - Keep `lablink.sleap.ai` in Route53 (managed by LabLink)
   - Delete `sleap.ai` from Route53 (managed in Cloudflare)

2. **Delete conflicting zone**:
   ```bash
   # ONLY if sleap.ai is managed in Cloudflare
   aws route53 delete-hosted-zone --id <sleap-ai-zone-id>
   ```

3. **Verify NS delegation in Cloudflare** (see above)

#### Deployment Verification Failing

**Symptoms**: `verify-deployment.sh` reports failures

**Run verification**:
```bash
cd lablink-infrastructure
./verify-deployment.sh test.lablink.sleap.ai 52.40.142.146
```

**Common failures**:

1. **DNS timeout** - Wait longer and retry
2. **HTTP not responding** - Check allocator container logs
3. **SSL not ready** - Check Caddy logs, may need more time

**Interpret results**:
- ✓ Green checkmarks = Success
- ⚠ Yellow warnings = May need more time
- ✗ Red errors = Actual problem requiring action

## Diagnostic Commands

### Check Overall System Health

```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>

# System resources
df -h              # Disk usage
free -h            # Memory usage
top                # CPU usage

# Docker
sudo docker ps -a  # All containers
sudo docker stats  # Resource usage

# Network
sudo netstat -tulpn    # Listening ports
ip addr show           # Network interfaces

# Logs
sudo journalctl -u docker -n 100  # Docker service logs
dmesg | tail                      # Kernel messages
```

### Check Flask App Status

```bash
# From allocator instance
curl localhost:80

# Expected: HTML response with LabLink interface
```

### Check Database Status

```bash
# PostgreSQL running?
sudo docker exec <container-id> pg_isready -U lablink

# Can connect?
sudo docker exec <container-id> psql -U lablink -d lablink_db -c "SELECT version();"

# View VMs
sudo docker exec <container-id> psql -U lablink -d lablink_db -c "SELECT * FROM vms;"
```

### Check AWS Connectivity

```bash
# From allocator container
sudo docker exec <container-id> aws sts get-caller-identity

# List EC2 instances
sudo docker exec <container-id> aws ec2 describe-instances --region us-west-2
```

## Getting Help

If issues persist:

1. **Check logs thoroughly**: Most issues have error messages in logs
2. **Search existing issues**: [GitHub Issues](https://github.com/talmolab/lablink/issues)
3. **Open new issue**: Provide:
   - Error messages
   - Logs
   - Steps to reproduce
   - Environment (OS, versions)
   - What you've tried

## Related Documentation

- **[Installation](installation.md)**: Setup instructions
- **[Deployment](deployment.md)**: Deployment guides
- **[SSH Access](ssh-access.md)**: Connection help
- **[Database](database.md)**: Database issues
- **[Security](security.md)**: Security problems

## Quick Troubleshooting Checklist

- [ ] Docker is running
- [ ] Container is running (`docker ps`)
- [ ] Security groups allow required ports (22, 80, 5432)
- [ ] SSH key has correct permissions (600)
- [ ] AWS credentials are configured
- [ ] PostgreSQL has been restarted (if needed)
- [ ] Terraform state is not locked
- [ ] S3 bucket exists for Terraform state
- [ ] IAM role/user has necessary permissions
- [ ] Network connectivity between components
- [ ] Logs have been checked for errors