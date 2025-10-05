# SSH Access

This guide covers SSH access to LabLink allocator and client EC2 instances.

## Overview

SSH (Secure Shell) provides secure remote access to EC2 instances for:

- Debugging and troubleshooting
- Log inspection
- Configuration changes
- Database access
- Manual operations

## SSH Key Management

### Key Generation

Terraform automatically generates SSH key pairs during deployment:

```hcl
resource "tls_private_key" "lablink_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "lablink_key_pair" {
  key_name   = "lablink-${var.resource_suffix}-key"
  public_key = tls_private_key.lablink_key.public_key_openssh
}
```

**Key characteristics**:
- **Algorithm**: RSA
- **Key size**: 4096 bits (strong security)
- **Format**: OpenSSH
- **Naming**: `lablink-<environment>-key` (e.g., `lablink-dev-key`, `lablink-prod-key`)

### Retrieving SSH Keys

#### From Terraform Output

After deployment:

```bash
cd lablink-infrastructure

# Display private key
terraform output -raw private_key_pem

# Save to file
terraform output -raw private_key_pem > ~/lablink-dev-key.pem

# Set proper permissions
chmod 600 ~/lablink-dev-key.pem
```

#### From GitHub Actions Artifacts

For deployments via GitHub Actions:

1. Navigate to **Actions** tab in GitHub
2. Click on the deployment workflow run
3. Scroll to **Artifacts** section
4. Download `lablink-key-<env>` artifact
5. Extract `lablink-key.pem`
6. Set permissions: `chmod 600 ~/lablink-key.pem`

!!! warning "Artifact Expiration"
    GitHub Actions artifacts expire after 1 day. Retrieve keys promptly or re-run deployment.

### Key Permissions

**Required permissions**: `600` (read/write for owner only)

```bash
# Set correct permissions
chmod 600 ~/lablink-key.pem

# Verify
ls -l ~/lablink-key.pem
# Should show: -rw------- (600)
```

**Why**:
SSH refuses to use keys with overly permissive permissions:
```
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@         WARNING: UNPROTECTED PRIVATE KEY FILE!          @
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
Permissions 0644 for 'lablink-key.pem' are too open.
```

## Connecting to Allocator

### Get Allocator IP Address

#### From Terraform Output

```bash
cd lablink-infrastructure
terraform output ec2_public_ip
```

#### From AWS Console

1. Navigate to **EC2 → Instances**
2. Find instance tagged `lablink-allocator-<env>`
3. Copy **Public IPv4 address**

#### From AWS CLI

```bash
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=lablink-allocator-dev" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text
```

### SSH Command

```bash
ssh -i ~/lablink-dev-key.pem ubuntu@<allocator-public-ip>
```

**Example**:
```bash
ssh -i ~/lablink-dev-key.pem ubuntu@54.123.45.67
```

**Default user**: `ubuntu` (for Ubuntu AMI)

### First Connection

On first SSH connection, you'll see:

```
The authenticity of host '54.123.45.67 (54.123.45.67)' can't be established.
ED25519 key fingerprint is SHA256:xxxxx.
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

Type `yes` and press Enter. This adds the host to `~/.ssh/known_hosts`.

### Successful Connection

You should see:

```
Welcome to Ubuntu 20.04.6 LTS (GNU/Linux 5.15.0-1023-aws x86_64)
...
ubuntu@ip-xxx-xx-xx-xx:~$
```

## Common SSH Tasks

### Inspect Docker Containers

```bash
# List running containers
sudo docker ps

# View allocator container logs
sudo docker logs <container-id>

# Follow logs in real-time
sudo docker logs -f <container-id>
```

### Access Allocator Container

```bash
# Get container ID
CONTAINER_ID=$(sudo docker ps --filter "ancestor=ghcr.io/talmolab/lablink-allocator-image" --format "{{.ID}}")

# Execute bash in container
sudo docker exec -it $CONTAINER_ID bash
```

Inside container:

```bash
# View configuration
cat /app/config/config.yaml

# Check Flask app
ps aux | grep flask

# Access PostgreSQL
psql -U lablink -d lablink_db
```

### Restart PostgreSQL

Known issue: PostgreSQL may need restart after first boot:

```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>

# Get container ID
sudo docker ps

# Access container
sudo docker exec -it <container-id> bash

# Inside container: restart PostgreSQL
/etc/init.d/postgresql restart

# Verify it's running
pg_isready -U lablink
```

### Check System Resources

```bash
# Disk usage
df -h

# Memory usage
free -h

# CPU usage
top

# Running processes
ps aux

# Network connections
sudo netstat -tulpn
```

### View Logs

```bash
# System logs
sudo journalctl -u docker

# Docker container logs
sudo docker logs <container-id>

# PostgreSQL logs (inside container)
sudo docker exec -it <container-id> tail -f /var/log/postgresql/postgresql-*.log

# Application logs (if logging to file)
sudo docker exec -it <container-id> tail -f /var/log/lablink/app.log
```

### Transfer Files

#### From Local to EC2

```bash
# Copy single file
scp -i ~/lablink-key.pem local-file.txt ubuntu@<allocator-ip>:~/

# Copy directory
scp -i ~/lablink-key.pem -r local-dir/ ubuntu@<allocator-ip>:~/
```

#### From EC2 to Local

```bash
# Copy single file
scp -i ~/lablink-key.pem ubuntu@<allocator-ip>:~/remote-file.txt ./

# Copy directory
scp -i ~/lablink-key.pem -r ubuntu@<allocator-ip>:~/remote-dir ./
```

## Connecting to Client VMs

### Get Client VM IP

```bash
# Via allocator database
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>
sudo docker exec -it <container-id> psql -U lablink -d lablink_db -c "SELECT hostname, status FROM vms;"

# Via AWS CLI
aws ec2 describe-instances \
  --filters "Name=tag:CreatedBy,Values=LabLink" \
  --query 'Reservations[*].Instances[*].[InstanceId,PublicIpAddress,State.Name]' \
  --output table
```

### SSH to Client VM

Use the same key as allocator:

```bash
ssh -i ~/lablink-key.pem ubuntu@<client-vm-ip>
```

**Note**: If Terraform created clients, key might be different. Check Terraform outputs or client VM security settings.

### Common Client VM Tasks

```bash
# Check Docker containers
sudo docker ps

# View client service logs
sudo docker logs <client-container-id>

# Check GPU availability
nvidia-smi

# Verify research repository cloned
ls -la /home/ubuntu/research-repo/

# Check client service status
sudo systemctl status lablink-client  # If using systemd
```

## SSH Configuration File

For easier SSH access, create `~/.ssh/config`:

```bash
# Allocator Dev
Host lablink-dev
    HostName 54.123.45.67
    User ubuntu
    IdentityFile ~/.ssh/lablink-dev-key.pem
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null

# Allocator Test
Host lablink-test
    HostName 54.234.56.78
    User ubuntu
    IdentityFile ~/.ssh/lablink-test-key.pem

# Allocator Prod
Host lablink-prod
    HostName 54.98.76.54
    User ubuntu
    IdentityFile ~/.ssh/lablink-prod-key.pem
```

**Usage**:
```bash
# Instead of:
ssh -i ~/lablink-dev-key.pem ubuntu@54.123.45.67

# Simply:
ssh lablink-dev
```

## Troubleshooting SSH Issues

### Permission Denied (publickey)

**Error**:
```
Permission denied (publickey).
```

**Causes & Solutions**:

1. **Wrong key**:
   ```bash
   # Verify key matches instance
   ssh-keygen -lf ~/lablink-key.pem
   ```

2. **Wrong permissions**:
   ```bash
   chmod 600 ~/lablink-key.pem
   ```

3. **Wrong user**:
   ```bash
   # Try 'ubuntu' or 'ec2-user'
   ssh -i ~/lablink-key.pem ubuntu@<ip>
   ssh -i ~/lablink-key.pem ec2-user@<ip>
   ```

4. **Key not in authorized_keys**:
   - Redeploy instance with correct key

### Connection Timeout

**Error**:
```
ssh: connect to host 54.123.45.67 port 22: Connection timed out
```

**Causes & Solutions**:

1. **Security group doesn't allow SSH**:
   ```bash
   aws ec2 describe-security-groups \
     --group-ids sg-xxxxx \
     --query 'SecurityGroups[0].IpPermissions'
   ```

   Add SSH rule:
   ```bash
   aws ec2 authorize-security-group-ingress \
     --group-id sg-xxxxx \
     --protocol tcp \
     --port 22 \
     --cidr $(curl -s ifconfig.me)/32
   ```

2. **Instance not running**:
   ```bash
   aws ec2 describe-instances --instance-ids i-xxxxx \
     --query 'Reservations[0].Instances[0].State.Name'
   ```

3. **Wrong IP address**:
   - Verify IP from AWS console or Terraform output

### Host Key Verification Failed

**Error**:
```
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
```

**Cause**: Instance was recreated with same IP but different host key.

**Solution**:
```bash
# Remove old host key
ssh-keygen -R <ip-address>

# Or remove entire known_hosts file (if safe)
rm ~/.ssh/known_hosts
```

### Too Many Authentication Failures

**Error**:
```
Received disconnect from 54.123.45.67: Too many authentication failures
```

**Cause**: SSH tried multiple keys before correct one.

**Solution**:
```bash
# Specify only this key
ssh -o IdentitiesOnly=yes -i ~/lablink-key.pem ubuntu@<ip>
```

## Alternative Access Methods

### AWS Systems Manager Session Manager

No SSH keys needed:

```bash
# Install Session Manager plugin
# macOS
brew install --cask session-manager-plugin

# Start session
aws ssm start-session --target i-xxxxx
```

**Benefits**:
- No SSH keys to manage
- Works even if security group blocks port 22
- Audit logs in CloudTrail
- IAM-based access control

**Requirements**:
- SSM agent installed on instance (default for recent AMIs)
- IAM role attached to instance with SSM permissions

### EC2 Instance Connect

Browser-based SSH (AWS Console):

1. Navigate to **EC2 → Instances**
2. Select instance
3. Click **Connect**
4. Choose **EC2 Instance Connect**
5. Click **Connect**

**Limitations**:
- Only works for 60 seconds
- Requires security group to allow port 22 from AWS IP ranges

### Serial Console

For debugging boot issues:

1. Navigate to **EC2 → Instances**
2. Select instance
3. **Actions → Monitor and troubleshoot → EC2 Serial Console**

**Note**: Must be enabled in account settings.

## Security Best Practices

1. **Restrict SSH access**: Limit security group to your IP
   ```bash
   YOUR_IP=$(curl -s ifconfig.me)
   aws ec2 authorize-security-group-ingress \
     --group-id sg-xxxxx \
     --protocol tcp \
     --port 22 \
     --cidr $YOUR_IP/32
   ```

2. **Use SSH agent**: Avoid typing key path
   ```bash
   ssh-add ~/lablink-key.pem
   ssh ubuntu@<ip>  # No -i flag needed
   ```

3. **Disable password authentication**: Enforce key-based auth
   ```bash
   # In /etc/ssh/sshd_config
   PasswordAuthentication no
   ```

4. **Use bastion host**: For production, access via jump box
   ```bash
   ssh -J bastion-user@bastion-ip ubuntu@private-ip
   ```

5. **Rotate keys regularly**: Every 90 days
   ```bash
   terraform destroy && terraform apply  # Generates new keys
   ```

6. **Use Session Manager**: Avoid SSH when possible

## Next Steps

- **[Troubleshooting](troubleshooting.md)**: Fix SSH and connectivity issues
- **[Security](security.md)**: Secure your SSH access
- **[Database Management](database.md)**: Access database via SSH

## Quick Reference

```bash
# Connect to allocator
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>

# Set key permissions
chmod 600 ~/lablink-key.pem

# Copy file to instance
scp -i ~/lablink-key.pem file.txt ubuntu@<ip>:~/

# Access container
sudo docker exec -it <container-id> bash

# View logs
sudo docker logs -f <container-id>

# Restart PostgreSQL
sudo docker exec -it <container-id> /etc/init.d/postgresql restart
```