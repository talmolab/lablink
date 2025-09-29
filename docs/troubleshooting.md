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
   cd lablink-allocator
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
   sudo docker exec <container-id> cat /app/lablink-allocator-service/conf/config.yaml
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
   cd /app/lablink-allocator-service/terraform
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

**Solution**:
```bash
# If no other Terraform process is running:
terraform force-unlock <lock-id>

# If using S3 backend, check DynamoDB table for locks
aws dynamodb scan --table-name terraform-lock-table
```

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

**Symptoms**: VM created but doesn't appear in allocator

**Check**:

1. **Client VM logs**:
   ```bash
   ssh -i ~/lablink-key.pem ubuntu@<client-vm-ip>
   sudo docker logs <client-container-id>
   ```

2. **Network connectivity**:
   ```bash
   # From client VM
   curl http://<allocator-ip>:80
   ```

3. **Security group allows outbound**:
   - Client needs to reach allocator on port 80

**Solution**:
```bash
# Update client VM security group
aws ec2 authorize-security-group-egress \
  --group-id <client-sg-id> \
  --protocol tcp \
  --port 80 \
  --cidr <allocator-ip>/32
```

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