# AWS Setup from Scratch

This comprehensive guide walks you through setting up all required AWS resources for LabLink deployment from scratch.

## Overview

To deploy LabLink, you'll need:

1. AWS account with appropriate permissions
2. S3 bucket for Terraform state
3. Elastic IPs for each environment
4. IAM role for GitHub Actions (OIDC)
5. Optional: Route 53 hosted zone for DNS

## Prerequisites

- AWS account with admin access (or appropriate IAM permissions)
- [AWS CLI installed and configured](prerequisites.md#2-aws-cli)
- Basic understanding of AWS services

## Step 1: IAM Permissions Setup

### Create IAM User (If Needed)

If you don't have an IAM user with sufficient permissions:

```bash
aws iam create-user --user-name lablink-admin
```

### Attach Required Policies

Attach these managed policies for LabLink operations:

```bash
aws iam attach-user-policy \
  --user-name lablink-admin \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess

aws iam attach-user-policy \
  --user-name lablink-admin \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

aws iam attach-user-policy \
  --user-name lablink-admin \
  --policy-arn arn:aws:iam::aws:policy/IAMFullAccess
```

### Create Access Keys

For local Terraform usage:

```bash
aws iam create-access-key --user-name lablink-admin
```

Save the `AccessKeyId` and `SecretAccessKey` securely.

Configure AWS CLI:
```bash
aws configure
# Enter AccessKeyId
# Enter SecretAccessKey
# Enter region (e.g., us-west-2)
# Enter output format (json)
```

## Step 2: S3 Bucket for Terraform State

### Create S3 Bucket

Choose a globally unique bucket name:

```bash
export BUCKET_NAME="tf-state-lablink-allocator-bucket-$(date +%s)"

aws s3api create-bucket \
  --bucket $BUCKET_NAME \
  --region us-west-2 \
  --create-bucket-configuration LocationConstraint=us-west-2
```

### Enable Versioning

Protect against accidental deletions:

```bash
aws s3api put-bucket-versioning \
  --bucket $BUCKET_NAME \
  --versioning-configuration Status=Enabled
```

### Enable Encryption

Encrypt state files at rest:

```bash
aws s3api put-bucket-encryption \
  --bucket $BUCKET_NAME \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }'
```

### Block Public Access

Ensure bucket is private:

```bash
aws s3api put-public-access-block \
  --bucket $BUCKET_NAME \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

### Update Configuration

Update bucket name in your LabLink configuration:

**`lablink-allocator/lablink-allocator-service/conf/config.yaml`**:
```yaml
bucket_name: "tf-state-lablink-allocator-bucket-1234567890"
```

**`lablink-allocator/backend-test.hcl`** and **`backend-prod.hcl`**:
```hcl
bucket = "tf-state-lablink-allocator-bucket-1234567890"
key    = "lablink-allocator-<env>/terraform.tfstate"
region = "us-west-2"
```

## Step 3: Elastic IP Allocation

Allocate static IPs for test and production environments.

### Allocate Elastic IPs

```bash
# Test environment
aws ec2 allocate-address --region us-west-2 --tag-specifications \
  'ResourceType=elastic-ip,Tags=[{Key=Environment,Value=test},{Key=Project,Value=lablink}]'

# Production environment
aws ec2 allocate-address --region us-west-2 --tag-specifications \
  'ResourceType=elastic-ip,Tags=[{Key=Environment,Value=prod},{Key=Project,Value=lablink}]'
```

### Record Allocation IDs

Save the `AllocationId` from each command output (format: `eipalloc-xxxxx`).

### Tag Elastic IPs

```bash
aws ec2 create-tags \
  --resources eipalloc-test-xxxxx \
  --tags Key=Name,Value=lablink-test-eip

aws ec2 create-tags \
  --resources eipalloc-prod-xxxxx \
  --tags Key=Name,Value=lablink-prod-eip
```

### Update Terraform Configuration

**`lablink-allocator/main.tf`**:
```hcl
variable "allocated_eip" {
  description = "Pre-allocated Elastic IP for production/test"
  type        = string
  default     = ""
}

resource "aws_eip_association" "lablink" {
  count         = var.allocated_eip != "" ? 1 : 0
  instance_id   = aws_instance.lablink_allocator.id
  allocation_id = var.allocated_eip
}
```

Use when deploying:
```bash
terraform apply \
  -var="resource_suffix=test" \
  -var="allocated_eip=eipalloc-test-xxxxx"
```

## Step 4: OIDC Configuration

Set up OpenID Connect for GitHub Actions to authenticate to AWS without storing credentials.

### Create OIDC Provider

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

### Create IAM Role for GitHub Actions

Save this as `github-trust-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::YOUR_ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
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

Replace `YOUR_ACCOUNT_ID` with your AWS account ID (find with `aws sts get-caller-identity`).

Create the role:

```bash
aws iam create-role \
  --role-name github-lablink-deploy \
  --assume-role-policy-document file://github-trust-policy.json
```

### Attach Permissions to Role

Create permissions policy `github-lablink-permissions.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:*",
        "s3:*",
        "iam:GetRole",
        "iam:PassRole",
        "route53:*"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::tf-state-lablink-*/*"
    }
  ]
}
```

Attach policy:

```bash
aws iam put-role-policy \
  --role-name github-lablink-deploy \
  --policy-name lablink-deploy-permissions \
  --policy-document file://github-lablink-permissions.json
```

### Update GitHub Workflow

Update the role ARN in `.github/workflows/lablink-allocator-terraform.yml`:

```yaml
- name: Configure AWS credentials via OIDC
  uses: aws-actions/configure-aws-credentials@v3
  with:
    role-to-assume: arn:aws:iam::YOUR_ACCOUNT_ID:role/github-lablink-deploy
    aws-region: us-west-2
```

## Step 5: Security Groups (Optional Pre-Creation)

Terraform creates security groups automatically, but you can pre-create them for more control.

### Allocator Security Group

```bash
# Create security group
ALLOCATOR_SG=$(aws ec2 create-security-group \
  --group-name lablink-allocator-sg \
  --description "LabLink Allocator Security Group" \
  --vpc-id vpc-xxxxx \
  --output text --query 'GroupId')

# Allow HTTP (port 80)
aws ec2 authorize-security-group-ingress \
  --group-id $ALLOCATOR_SG \
  --protocol tcp \
  --port 80 \
  --cidr 0.0.0.0/0

# Allow SSH (port 22)
aws ec2 authorize-security-group-ingress \
  --group-id $ALLOCATOR_SG \
  --protocol tcp \
  --port 22 \
  --cidr 0.0.0.0/0

# Allow PostgreSQL from VPC (port 5432)
aws ec2 authorize-security-group-ingress \
  --group-id $ALLOCATOR_SG \
  --protocol tcp \
  --port 5432 \
  --source-group $ALLOCATOR_SG
```

## Step 6: Route 53 DNS (Optional)

Set up custom domains for your allocators.

### Create Hosted Zone

```bash
aws route53 create-hosted-zone \
  --name lablink.yourdomain.com \
  --caller-reference $(date +%s)
```

Note the hosted zone ID from the output.

### Create DNS Records

After deploying allocator, create A record:

```bash
# Get allocator IP
ALLOCATOR_IP=$(terraform output -raw ec2_public_ip)

# Create/update DNS record
aws route53 change-resource-record-sets \
  --hosted-zone-id Z1234567890ABC \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "lablink-test.yourdomain.com",
        "Type": "A",
        "TTL": 300,
        "ResourceRecords": [{"Value": "'$ALLOCATOR_IP'"}]
      }
    }]
  }'
```

### Update Name Servers

Update your domain registrar with the Route 53 name servers (from hosted zone output).

## Step 7: Secrets Manager (Optional)

Store sensitive configuration in AWS Secrets Manager instead of config files.

### Create Secrets

```bash
# Database password
aws secretsmanager create-secret \
  --name lablink/db-password \
  --secret-string "your-secure-db-password" \
  --region us-west-2

# Admin password
aws secretsmanager create-secret \
  --name lablink/admin-password \
  --secret-string "your-secure-admin-password" \
  --region us-west-2
```

### Retrieve in Application

Modify your application code to fetch secrets:

```python
import boto3
from botocore.exceptions import ClientError

def get_secret(secret_name, region_name="us-west-2"):
    """Retrieve secret from AWS Secrets Manager."""
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        response = client.get_secret_value(SecretId=secret_name)
        return response['SecretString']
    except ClientError as e:
        raise e

# Usage
db_password = get_secret("lablink/db-password")
admin_password = get_secret("lablink/admin-password")
```

## Step 8: CloudWatch Monitoring (Optional)

Set up monitoring and alerts for your infrastructure.

### Enable CloudWatch Logs

Update user data script to send logs to CloudWatch:

```bash
#!/bin/bash

# Install CloudWatch agent
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
dpkg -i amazon-cloudwatch-agent.deb

# Configure CloudWatch agent
cat > /opt/aws/amazon-cloudwatch-agent/etc/config.json <<EOF
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/syslog",
            "log_group_name": "/aws/ec2/lablink-allocator",
            "log_stream_name": "{instance_id}/syslog"
          }
        ]
      }
    }
  }
}
EOF

# Start agent
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -s -c file:/opt/aws/amazon-cloudwatch-agent/etc/config.json
```

### Create CloudWatch Alarms

```bash
# CPU utilization alarm
aws cloudwatch put-metric-alarm \
  --alarm-name lablink-allocator-cpu-high \
  --alarm-description "Alert when CPU exceeds 80%" \
  --metric-name CPUUtilization \
  --namespace AWS/EC2 \
  --statistic Average \
  --period 300 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2 \
  --dimensions Name=InstanceId,Value=i-xxxxx
```

## Step 9: Billing Alerts

Set up cost monitoring to avoid unexpected charges.

### Enable Billing Alerts

```bash
aws ce put-cost-anomaly-monitor \
  --anomaly-monitor file://billing-monitor.json
```

**`billing-monitor.json`**:
```json
{
  "MonitorName": "LabLink Cost Monitor",
  "MonitorType": "DIMENSIONAL",
  "MonitorDimension": "SERVICE"
}
```

### Create Budget

```bash
aws budgets create-budget \
  --account-id YOUR_ACCOUNT_ID \
  --budget file://budget.json \
  --notifications-with-subscribers file://subscribers.json
```

**`budget.json`**:
```json
{
  "BudgetName": "LabLink Monthly Budget",
  "BudgetLimit": {
    "Amount": "100",
    "Unit": "USD"
  },
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST"
}
```

**`subscribers.json`**:
```json
[
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 80
    },
    "Subscribers": [
      {
        "SubscriptionType": "EMAIL",
        "Address": "your-email@example.com"
      }
    ]
  }
]
```

## Verification Checklist

After completing setup, verify:

- [ ] S3 bucket created with versioning and encryption
- [ ] Elastic IPs allocated for test and prod
- [ ] OIDC provider created
- [ ] IAM role for GitHub Actions configured
- [ ] GitHub workflow has correct role ARN
- [ ] (Optional) Route 53 hosted zone created
- [ ] (Optional) Secrets Manager secrets created
- [ ] (Optional) CloudWatch monitoring configured
- [ ] (Optional) Billing alerts set up

## Testing Your Setup

### Test AWS CLI Access

```bash
aws sts get-caller-identity
aws s3 ls
aws ec2 describe-regions
```

### Test Terraform

```bash
cd lablink-allocator
terraform init
terraform validate
```

### Test GitHub Actions

Push a commit to trigger workflows:

```bash
git commit --allow-empty -m "Test GitHub Actions"
git push origin main
```

Check Actions tab in GitHub.

## Common Issues

### OIDC Provider Already Exists

**Error**: `EntityAlreadyExists: Provider with URL ... already exists`

**Solution**: Use existing provider, just create new role

### S3 Bucket Name Taken

**Error**: `BucketAlreadyExists`

**Solution**: Choose a different bucket name (must be globally unique)

### IAM Permission Denied

**Error**: `AccessDenied: User ... is not authorized to perform`

**Solution**: Ensure IAM user/role has required permissions

## Cost Estimation

Estimated monthly costs for AWS resources:

| Resource | Usage | Estimated Cost |
|----------|-------|----------------|
| S3 Bucket | <1 GB, versioning | $0.05/month |
| Elastic IPs | 2 IPs (test, prod) | $0.00 (while associated) |
| Route 53 Hosted Zone | 1 zone | $0.50/month |
| Secrets Manager | 2 secrets | $0.80/month |

**Total AWS Setup Cost**: ~$1.35/month

Running EC2 instances cost extra. See [Cost Estimation](cost-estimation.md) for details.

## Next Steps

With AWS resources configured:

1. **[Deployment](deployment.md)**: Deploy LabLink
2. **[Security](security.md)**: Review security best practices
3. **[Workflows](workflows.md)**: Understand CI/CD pipelines

## Cleanup

To remove all AWS resources:

```bash
# Delete S3 bucket (remove objects first)
aws s3 rm s3://$BUCKET_NAME --recursive
aws s3api delete-bucket --bucket $BUCKET_NAME

# Release Elastic IPs
aws ec2 release-address --allocation-id eipalloc-test-xxxxx
aws ec2 release-address --allocation-id eipalloc-prod-xxxxx

# Delete IAM role
aws iam delete-role-policy --role-name github-lablink-deploy --policy-name lablink-deploy-permissions
aws iam delete-role --role-name github-lablink-deploy

# Delete OIDC provider
aws iam delete-open-id-connect-provider \
  --open-id-connect-provider-arn arn:aws:iam::YOUR_ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com
```