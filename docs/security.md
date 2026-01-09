# Security

This guide covers security considerations, best practices, and how to secure your LabLink deployment.

## Security Overview

LabLink implements multiple security layers:

- **Authentication**: Admin interface password protection
- **Authorization**: OIDC for GitHub Actions, IAM roles for AWS
- **Encryption**: HTTPS (optional), encrypted Terraform state
- **Network**: Security groups restrict access
- **Secrets**: Environment variables, AWS Secrets Manager

## Threat Model

### Assets to Protect

1. **Allocator Server**: Controls infrastructure
2. **Client VMs**: Run research workloads
3. **Database**: Contains VM assignments and user data
4. **AWS Credentials**: Access to cloud resources
5. **SSH Keys**: Access to EC2 instances
6. **Admin Credentials**: Access to allocator interface

### Potential Threats

| Threat | Impact | Mitigation |
|--------|--------|------------|
| Unauthorized admin access | Full system control | Strong passwords, HTTPS, IP restrictions |
| AWS credential exposure | Unauthorized infrastructure changes | OIDC (no stored credentials), IAM policies |
| SSH key leakage | Direct server access | Ephemeral keys, proper permissions (600) |
| Database access | Data exposure, manipulation | Firewall rules, strong passwords |
| Man-in-the-middle | Credential theft, data interception | HTTPS, VPC isolation |
| Resource exhaustion | Denial of service, high costs | Billing alerts, resource limits |

## Authentication & Authorization

### Change Default Passwords

**Critical**: Change default passwords before deployment!

#### Allocator Admin Password

**Default**: Configuration files use `PLACEHOLDER_ADMIN_PASSWORD` which must be replaced with a secure password.

**Method 1: GitHub Secrets (Recommended for CI/CD)**

For GitHub Actions deployments, add the `ADMIN_PASSWORD` secret to your repository:

1. Go to repository **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Name: `ADMIN_PASSWORD`
4. Value: Your secure password
5. Click **Add secret**

The deployment workflow automatically injects this secret into configuration files before Terraform apply, preventing passwords from appearing in logs.

**Method 2: Manual configuration**

Edit `lablink-infrastructure/config/config.yaml`:
```yaml
app:
  admin_user: "admin"
  admin_password: "YOUR_SECURE_PASSWORD_HERE"
```

**Method 3: Environment variable**

```bash
export ADMIN_PASSWORD="your_secure_password"

# Docker
docker run -d \
  -e ADMIN_PASSWORD="your_secure_password" \
  -p 5000:5000 \
  ghcr.io/talmolab/lablink-allocator-image:latest
```

**Password requirements**:
- Minimum 12 characters
- Mix of uppercase, lowercase, numbers, symbols
- Not a dictionary word
- Use a password manager

#### Database Password

**Default**: Configuration files use `PLACEHOLDER_DB_PASSWORD` which must be replaced with a secure password.

**Method 1: GitHub Secrets (Recommended for CI/CD)**

For GitHub Actions deployments, add the `DB_PASSWORD` secret to your repository:

1. Go to repository **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Name: `DB_PASSWORD`
4. Value: Your secure database password
5. Click **Add secret**

The deployment workflow automatically injects this secret into configuration files before Terraform apply, preventing passwords from appearing in logs.

**Method 2: Manual configuration**

Edit `lablink-infrastructure/config/config.yaml`:
```yaml
db:
  user: "lablink"
  password: "YOUR_SECURE_DB_PASSWORD_HERE"
```

**Method 3: Environment variable**

```bash
export DB_PASSWORD="your_secure_db_password"
```

**Method 4: AWS Secrets Manager (Advanced)**

```bash
# Store in Secrets Manager
aws secretsmanager create-secret \
  --name lablink/db-password \
  --secret-string "your-secure-db-password"

# Retrieve in application
import boto3
client = boto3.client('secretsmanager', region_name='us-west-2')
response = client.get_secret_value(SecretId='lablink/db-password')
db_password = response['SecretString']
```

### OIDC for GitHub Actions

OpenID Connect (OIDC) allows GitHub Actions to authenticate to AWS **without storing credentials**.

#### How It Works

```
1. GitHub Action requests token from GitHub OIDC provider
2. GitHub issues short-lived token with repository info
3. Action presents token to AWS STS
4. AWS validates token against IAM role trust policy
5. AWS issues temporary AWS credentials
6. Action uses credentials for Terraform operations
7. Credentials expire automatically
```

#### Benefits

- **No stored credentials**: Nothing to leak or rotate
- **Short-lived**: Credentials expire quickly
- **Scoped**: Permissions limited to specific role
- **Auditable**: CloudTrail logs all API calls

#### Trust Policy

The IAM role trust policy restricts which repositories can assume the role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:talmolab/lablink:*"
        }
      }
    }
  ]
}
```

**Key**: `token.actions.githubusercontent.com:sub` restricts to specific repository.

#### Setup

See [AWS Setup → OIDC Configuration](aws-setup.md#step-4-github-actions-oidc-configuration).

### IAM Role Permissions

Follow **principle of least privilege**.

**Minimal permissions** for LabLink deployment:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances",
        "ec2:TerminateInstances",
        "ec2:DescribeInstances",
        "ec2:CreateSecurityGroup",
        "ec2:DeleteSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:RevokeSecurityGroupIngress",
        "ec2:CreateKeyPair",
        "ec2:DeleteKeyPair",
        "ec2:DescribeKeyPairs",
        "ec2:AllocateAddress",
        "ec2:AssociateAddress",
        "ec2:DescribeAddresses"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::tf-state-lablink-*",
        "arn:aws:s3:::tf-state-lablink-*/*"
      ]
    }
  ]
}
```

**Restrict by tags** (advanced):

```json
{
  "Effect": "Allow",
  "Action": "ec2:*",
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "ec2:ResourceTag/Project": "lablink"
    }
  }
}
```

## Network Security

### Security Groups

LabLink creates security groups for allocator and client VMs.

#### Allocator Security Group

**Inbound Rules**:

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 80 | TCP | 0.0.0.0/0 | HTTP web interface |
| 22 | TCP | 0.0.0.0/0 | SSH access |
| 5432 | TCP | VPC CIDR | PostgreSQL (internal) |

**Recommendations**:

1. **Restrict SSH**: Change source from `0.0.0.0/0` to your IP:
   ```bash
   YOUR_IP=$(curl -s ifconfig.me)
   aws ec2 authorize-security-group-ingress \
     --group-id sg-xxxxx \
     --protocol tcp \
     --port 22 \
     --cidr $YOUR_IP/32
   ```

2. **Enable HTTPS**: Use port 443 instead of 80 with SSL certificate:
   ```bash
   # Install certbot on allocator
   sudo certbot --nginx -d lablink.yourdomain.com
   ```

3. **Restrict HTTP**: Limit to known client IPs if possible

#### Client VM Security Group

**Inbound Rules**:

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP | Your IP | SSH access |

**Outbound Rules**:

| Port | Protocol | Destination | Purpose |
|------|----------|-------------|---------|
| All | All | 0.0.0.0/0 | Internet access (packages, GitHub) |

**Recommendations**:

1. **Restrict outbound**: If possible, limit to specific destinations:
   - Package repos (apt, pip)
   - GitHub
   - Allocator IP

2. **VPC Endpoints**: Use VPC endpoints for AWS services (S3, EC2) to avoid internet routing

### VPC Configuration

For production, use a dedicated VPC:

```hcl
resource "aws_vpc" "lablink" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "lablink-vpc"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.lablink.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "us-west-2a"
  map_public_ip_on_launch = true

  tags = {
    Name = "lablink-public-subnet"
  }
}

resource "aws_subnet" "private" {
  vpc_id            = aws_vpc.lablink.id
  cidr_block        = "10.0.2.0/24"
  availability_zone = "us-west-2a"

  tags = {
    Name = "lablink-private-subnet"
  }
}
```

**Benefits**:
- Isolation from other workloads
- Custom network ACLs
- VPC Flow Logs for monitoring

## Staging Mode Security

**Warning**: Staging mode (`ssl.staging: true`) serves unencrypted HTTP traffic. All data transmitted between users and the allocator is sent in plaintext.

### Data Exposed in Staging Mode

When using staging mode, the following information is transmitted unencrypted:

- Admin usernames and passwords
- Database credentials
- VM allocation requests
- Research data filenames and metadata
- SSH keys and access tokens
- All HTTP request/response data

### When Staging Mode is Acceptable

Use staging mode only when:

- Testing in isolated VPCs with no internet access
- Accessing via VPN on private networks
- Local testing on development machines
- Short-term infrastructure testing (less than 1 hour)
- Automated CI/CD testing pipelines
- No sensitive data is involved

### When Production Mode is Required

Use production mode (`ssl.staging: false`) for:

- Any internet-accessible deployment
- Handling sensitive research data
- Multi-user environments
- Long-running deployments
- Production or staging environments
- Compliance requirements (HIPAA, GDPR, etc.)

### Mitigations for Staging Mode

If you must use staging mode with potentially sensitive data:

1. **Restrict access to your IP only**:
   ```hcl
   # In Terraform security group
   ingress {
     from_port   = 80
     to_port     = 80
     protocol    = "tcp"
     cidr_blocks = ["YOUR_IP/32"]
   }
   ```

2. **Use a VPN** - All access through VPN tunnel

3. **Deploy in private VPC** - No internet gateway

4. **Time-limited** - Switch to production mode as soon as testing is complete

5. **Monitor access** - Check CloudWatch logs for unexpected connections

### Switching to Production Mode

To switch a deployment from staging to production:

1. Update configuration:
   ```yaml
   ssl:
     staging: false
   ```

2. Redeploy:
   ```bash
   terraform apply
   ```

3. Wait for Let's Encrypt certificate (30-60 seconds)

4. Access via HTTPS:
   ```
   https://your-domain.com
   ```

5. Clear browser HSTS cache if you previously accessed via HTTP (see [Troubleshooting](troubleshooting.md#browser-cannot-access-http-staging-mode))

## Secrets Management

### Environment Variables

For development:

```bash
export DB_PASSWORD="secure_password"
export ADMIN_PASSWORD="secure_admin_password"
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."
```

**Pros**:
- Simple
- No external dependencies

**Cons**:
- Visible in process list
- Can leak in logs
- Not encrypted at rest

### AWS Secrets Manager

For production:

**Store secrets**:
```bash
aws secretsmanager create-secret \
  --name lablink/config \
  --secret-string '{
    "db_password": "secure_db_password",
    "admin_password": "secure_admin_password"
  }'
```

**Retrieve in application**:
```python
import boto3
import json

def get_secrets():
    client = boto3.client('secretsmanager', region_name='us-west-2')
    response = client.get_secret_value(SecretId='lablink/config')
    secrets = json.loads(response['SecretString'])
    return secrets

secrets = get_secrets()
db_password = secrets['db_password']
admin_password = secrets['admin_password']
```

**Pros**:
- Encrypted at rest and in transit
- Automatic rotation
- Audit logs (CloudTrail)
- Versioning

**Cons**:
- Additional cost ($0.40/secret/month)
- Requires IAM permissions

### GitHub Secrets

For CI/CD workflows, GitHub Secrets provide secure password storage.

**Add secrets**:
1. Go to repository **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Add both required secrets:
   - Name: `ADMIN_PASSWORD`, Value: your secure admin password
   - Name: `DB_PASSWORD`, Value: your secure database password
4. Click **Add secret** for each

**How it works**:

The deployment workflow automatically injects secrets into configuration files before Terraform runs:

```yaml
- name: Inject Password Secrets
  env:
    ADMIN_PASSWORD: ${{ secrets.ADMIN_PASSWORD || 'CHANGEME_admin_password' }}
    DB_PASSWORD: ${{ secrets.DB_PASSWORD || 'CHANGEME_db_password' }}
  run: |
    sed -i "s/PLACEHOLDER_ADMIN_PASSWORD/${ADMIN_PASSWORD}/g" "$CONFIG_FILE"
    sed -i "s/PLACEHOLDER_DB_PASSWORD/${DB_PASSWORD}/g" "$CONFIG_FILE"
```

This replaces `PLACEHOLDER_ADMIN_PASSWORD` and `PLACEHOLDER_DB_PASSWORD` in config files with actual values from secrets, preventing passwords from appearing in Terraform logs.

**Pros**:
- Integrated with GitHub Actions
- Encrypted at rest and in transit
- Not visible in workflow logs
- Prevents password exposure in Terraform apply output

**Cons**:
- Only available in workflows
- Can't be read after creation

## SSH Key Security

### Key Generation

Terraform generates SSH keys automatically:

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

**Good**:
- Unique key per environment
- 4096-bit RSA (strong)

**Bad**:
- Stored in Terraform state (plaintext)
- Artifacts expire (GitHub Actions)

### Key Permissions

**Always set proper permissions**:

```bash
chmod 600 ~/lablink-key.pem
```

**Why**: Prevents SSH from rejecting key:
```
Permissions 0644 for 'lablink-key.pem' are too open.
It is required that your private key files are NOT accessible by others.
```

### Key Rotation

Rotate keys regularly:

```bash
# Destroy and recreate infrastructure
terraform destroy -var="resource_suffix=dev"
terraform apply -var="resource_suffix=dev"

# New keys generated automatically
```

**Frequency**: Every 90 days for production

### Key Storage

**Never**:
- Commit keys to version control
- Share keys via email/Slack
- Store keys in cloud storage without encryption

**Instead**:
- Use SSH agent: `ssh-add ~/lablink-key.pem`
- Store in password manager
- Use AWS Systems Manager Session Manager (no SSH needed)

### Session Manager (Alternative to SSH)

Use AWS Systems Manager for SSH-less access:

```bash
# Install Session Manager plugin
# macOS
brew install --cask session-manager-plugin

# Start session
aws ssm start-session --target i-xxxxx
```

**Benefits**:
- No SSH keys needed
- Audit logs in CloudTrail
- Fine-grained IAM control

## Data Encryption

### Encryption at Rest

#### Terraform State

S3 bucket encryption (AES-256):
```bash
aws s3api put-bucket-encryption \
  --bucket tf-state-lablink \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }'
```

#### EBS Volumes

Encrypt EC2 instance volumes:

```hcl
resource "aws_instance" "lablink_allocator" {
  ami           = var.ami_id
  instance_type = "t2.micro"

  root_block_device {
    volume_size           = 30
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }
}
```

#### Database

For RDS (if using external database):
```hcl
resource "aws_db_instance" "lablink" {
  storage_encrypted = true
  kms_key_id        = aws_kms_key.lablink.arn
}
```

### Encryption in Transit

#### HTTPS for Allocator

Use Let's Encrypt certificate:

```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>

# Install certbot
sudo apt-get update
sudo apt-get install -y certbot python3-certbot-nginx

# Get certificate
sudo certbot --nginx -d lablink.yourdomain.com --non-interactive --agree-tos -m your@email.com

# Auto-renewal
sudo systemctl enable certbot.timer
```

Update security group to allow port 443.

#### PostgreSQL SSL

Enable SSL for database connections:

**`postgresql.conf`**:
```
ssl = on
ssl_cert_file = '/etc/ssl/certs/server.crt'
ssl_key_file = '/etc/ssl/private/server.key'
```

Client connection:
```python
import psycopg2

conn = psycopg2.connect(
    host="allocator-ip",
    database="lablink_db",
    user="lablink",
    password="password",
    sslmode="require"  # Force SSL
)
```

## Monitoring & Auditing

### CloudTrail

Enable CloudTrail for AWS API auditing:

```bash
aws cloudtrail create-trail \
  --name lablink-trail \
  --s3-bucket-name lablink-cloudtrail-logs

aws cloudtrail start-logging --name lablink-trail
```

**Logs include**:
- EC2 instance launches/terminations
- Security group changes
- IAM role assumptions
- S3 access

### VPC Flow Logs

Monitor network traffic:

```bash
aws ec2 create-flow-logs \
  --resource-type VPC \
  --resource-ids vpc-xxxxx \
  --traffic-type ALL \
  --log-destination-type cloud-watch-logs \
  --log-group-name lablink-vpc-flow-logs
```

### Application Logging

Log security events in application:

```python
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Log authentication attempts
@app.route('/admin')
@requires_auth
def admin():
    logger.info(f"Admin access by {request.remote_addr}")
    return render_template('admin.html')

# Log VM requests
@app.route('/request_vm', methods=['POST'])
def request_vm():
    logger.info(f"VM requested by {request.form.get('email')} from {request.remote_addr}")
    # ... handle request
```

## Compliance & Best Practices

### Security Checklist

- [ ] Changed default admin password
- [ ] Changed default database password
- [ ] Enabled HTTPS for allocator
- [ ] Restricted SSH access to known IPs
- [ ] Enabled S3 bucket encryption
- [ ] Enabled EBS volume encryption
- [ ] Set up CloudTrail logging
- [ ] Set up billing alerts
- [ ] Rotated SSH keys (if older than 90 days)
- [ ] Reviewed IAM role permissions
- [ ] Enabled MFA for AWS account
- [ ] Set up VPC Flow Logs
- [ ] Documented security procedures

### Regular Security Tasks

| Task | Frequency |
|------|-----------|
| Review CloudTrail logs | Weekly |
| Rotate SSH keys | Every 90 days |
| Update dependencies | Monthly |
| Review security group rules | Quarterly |
| Audit IAM permissions | Quarterly |
| Penetration testing | Annually |

### Incident Response

If security incident occurs:

1. **Isolate**: Modify security groups to block traffic
2. **Investigate**: Review CloudTrail, VPC Flow Logs, application logs
3. **Contain**: Terminate compromised instances
4. **Recover**: Deploy from known-good state
5. **Learn**: Document incident, improve security

## Security Resources

- [AWS Security Best Practices](https://docs.aws.amazon.com/security/)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [CIS AWS Foundations Benchmark](https://www.cisecurity.org/benchmark/amazon_web_services)

## Next Steps

- **[AWS Setup](aws-setup.md)**: Secure AWS resource configuration
- **[Deployment](deployment.md)**: Secure deployment practices
- **[Troubleshooting](troubleshooting.md)**: Security-related issues