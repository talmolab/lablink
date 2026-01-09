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
- Chosen AWS region for deployment

## Choosing an AWS Region

Before starting, select the AWS region where you'll deploy LabLink. This is an important decision that affects performance, cost, and compliance.

### Region Selection Criteria

**1. Latency & Geographic Proximity**
- Choose a region closest to your users for best performance
- Lower latency = better user experience for VM access
- Test latency: `ping ec2.{region}.amazonaws.com`

**2. Instance Availability**
- Not all instance types are available in all regions
- GPU instances (g4dn, g5, p3) have limited regional availability
- Check availability: [AWS Regional Services](https://aws.amazon.com/about-aws/global-infrastructure/regional-product-services/)

**3. Pricing**
- EC2 pricing varies by region (5-30% difference)
- US regions are typically cheaper than EU/Asia
- Check pricing: [EC2 Pricing Calculator](https://calculator.aws/)

**4. Compliance & Data Residency**
- GDPR (Europe): Use `eu-west-1`, `eu-central-1`
- HIPAA (US Healthcare): Any US region with BAA
- Data sovereignty requirements may mandate specific regions

**5. Service Availability**
- All LabLink features require: EC2, VPC, S3, Route 53
- These are available in all commercial regions

### Recommended Regions

| Region                       | Code             | Best For                   | Notes                                          |
| ---------------------------- | ---------------- | -------------------------- | ---------------------------------------------- |
| **US East (N. Virginia)**    | `us-east-1`      | US East Coast, lowest cost | Largest region, occasional availability issues |
| **US West (Oregon)**         | `us-west-2`      | US West Coast, default     | Good balance of cost and stability             |
| **Europe (Ireland)**         | `eu-west-1`      | Europe, GDPR               | Best EU region for cost and availability       |
| **Asia Pacific (Tokyo)**     | `ap-northeast-1` | Asia                       | Good for Asian users                           |
| **Asia Pacific (Singapore)** | `ap-southeast-1` | Southeast Asia             | Alternative for Asian users                    |

### List All Available Regions

```bash
# AWS CLI
aws ec2 describe-regions --output table

# Or with region names
aws ec2 describe-regions --query "Regions[*].[RegionName,OptInStatus]" --output table
```

### Test Latency to Regions

```bash
# Test ping to various regions (macOS/Linux)
for region in us-east-1 us-west-2 eu-west-1 ap-northeast-1; do
  echo -n "$region: "
  ping -c 3 ec2.$region.amazonaws.com | grep avg | awk -F'/' '{print $5 " ms"}'
done
```

### Configure Your Region Choice

Once you've selected a region, you'll need to configure it in two places:

1. **GitHub Secret**: `AWS_REGION` (covered in Step 4.6)
2. **config.yaml**: Must match the secret (covered later)

**Example:**

```yaml
# lablink-infrastructure/config/config.yaml
app:
  region: "us-west-2" # Must match AWS_REGION secret
```

## Step 1: IAM Permissions Setup

### 1.1 Create IAM User (If Needed)

If you don't have an IAM user with sufficient permissions:

```bash
aws iam create-user --user-name lablink-admin
```

### 1.2 Attach Required Policies

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

### 1.3 Create Access Keys

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

### 2.1 Create S3 Bucket

Choose a globally unique bucket name:

```bash
export BUCKET_NAME="tf-state-lablink-allocator-bucket-$(date +%s)"

aws s3api create-bucket \
  --bucket $BUCKET_NAME \
  --region us-west-2 \
  --create-bucket-configuration LocationConstraint=us-west-2
```

### 2.2 Enable Versioning

Protect against accidental deletions:

```bash
aws s3api put-bucket-versioning \
  --bucket $BUCKET_NAME \
  --versioning-configuration Status=Enabled
```

### 2.3 Enable Encryption

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

### 2.4 Block Public Access

Ensure bucket is private:

```bash
aws s3api put-public-access-block \
  --bucket $BUCKET_NAME \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

### 2.5 Update Configuration

Update bucket name in your LabLink configuration:

**`lablink-infrastructure/config/config.yaml`**:

```yaml
bucket_name: "tf-state-lablink-allocator-bucket-1234567890"
```

**`lablink-infrastructure/backend-test.hcl`** and **`backend-prod.hcl`**:

```hcl
bucket = "tf-state-lablink-allocator-bucket-1234567890"
key    = "lablink-allocator-<env>/terraform.tfstate"
region = "us-west-2"
```

## Step 3: Elastic IP Allocation

Allocate static IPs for test and production environments.

### 3.1 Allocate Elastic IPs

```bash
# Test environment
aws ec2 allocate-address --region us-west-2 --tag-specifications \
  'ResourceType=elastic-ip,Tags=[{Key=Environment,Value=test},{Key=Project,Value=lablink}]'

# Production environment
aws ec2 allocate-address --region us-west-2 --tag-specifications \
  'ResourceType=elastic-ip,Tags=[{Key=Environment,Value=prod},{Key=Project,Value=lablink}]'
```

### 3.2 Record Allocation IDs

Save the `AllocationId` from each command output (format: `eipalloc-xxxxx`).

### 3.3 Tag Elastic IPs

```bash
aws ec2 create-tags \
  --resources eipalloc-test-xxxxx \
  --tags Key=Name,Value=lablink-test-eip

aws ec2 create-tags \
  --resources eipalloc-prod-xxxxx \
  --tags Key=Name,Value=lablink-prod-eip
```

### 3.4 Update Terraform Configuration

**`lablink-infrastructure/main.tf`**:

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

## Step 4: GitHub Actions OIDC Configuration

Set up OpenID Connect (OIDC) for GitHub Actions to authenticate to AWS without storing long-term credentials. This is the **recommended and most secure** method for CI/CD authentication.

### 4.1: Check for Existing OIDC Provider

Before creating a new OIDC provider, check if one already exists:

#### AWS CLI

```bash
# Check your current AWS account
aws sts get-caller-identity

# List OIDC providers
aws iam list-open-id-connect-providers
```

Look for a provider with URL `token.actions.githubusercontent.com`.

#### AWS Console

1. Go to **IAM → Identity providers**
2. Look for provider with URL `token.actions.githubusercontent.com`
3. If it exists, note the ARN and skip to Step 4.2

### 4.2: Create OIDC Provider (If Needed)

#### AWS CLI

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

**Note:** If you get `EntityAlreadyExists` error, the provider already exists. You can proceed to create the IAM role.

#### AWS Console

1. Go to **IAM → Identity providers**
2. Click **Add provider**
3. Select **OpenID Connect**
4. Provider URL: `https://token.actions.githubusercontent.com`
5. Click **Get thumbprint** (should show `6938fd4d98bab03faadb97b34396831e3780aea1`)
6. Audience: `sts.amazonaws.com`
7. Click **Add provider**

### 4.3: Create IAM Role for GitHub Actions

#### Option A: AWS CLI (Recommended for Multiple Repositories)

**Step 1:** Get your AWS account ID:

```bash
aws sts get-caller-identity --query "Account" --output text
```

**Step 2:** Create trust policy file `github-trust-policy.json`:

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
          "token.actions.githubusercontent.com:sub": [
            "repo:YOUR_ORG/lablink:*",
            "repo:YOUR_ORG/lablink-template:*",
            "repo:YOUR_ORG/sleap-lablink:*"
          ]
        }
      }
    }
  ]
}
```

**Important:** Replace:

- `YOUR_ACCOUNT_ID` with your AWS account ID (from Step 1)
- `YOUR_ORG` with your GitHub organization/username (e.g., `talmolab`)

**Step 3:** Create the IAM role:

```bash
aws iam create-role \
  --role-name GitHubActionsLabLinkRole \
  --assume-role-policy-document file://github-trust-policy.json \
  --description "Role for GitHub Actions to deploy LabLink infrastructure"
```

**Step 4:** Note the role ARN from the output (format: `arn:aws:iam::ACCOUNT_ID:role/GitHubActionsLabLinkRole`)

#### Option B: AWS Console

**Step 1:** Create the role

1. Go to **IAM → Roles**
2. Click **Create role**
3. Select **Web identity** as trusted entity type
4. Choose:
   - Identity provider: `token.actions.githubusercontent.com`
   - Audience: `sts.amazonaws.com`
5. Click **Next**

**Step 2:** Skip permissions for now (we'll add them in Step 4.4)

1. Click **Next**
2. Role name: `GitHubActionsLabLinkRole`
3. Description: `Role for GitHub Actions to deploy LabLink infrastructure`
4. Click **Create role**

**Step 3:** Edit trust policy for multiple repositories

1. Click on the newly created role
2. Go to **Trust relationships** tab
3. Click **Edit trust policy**
4. Replace the trust policy with:

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
          "token.actions.githubusercontent.com:sub": [
            "repo:YOUR_ORG/lablink:*",
            "repo:YOUR_ORG/lablink-template:*",
            "repo:YOUR_ORG/sleap-lablink:*"
          ]
        }
      }
    }
  ]
}
```

1. Replace `YOUR_ACCOUNT_ID` and `YOUR_ORG` with your values
2. Click **Update policy**

### 4.4: Attach Permissions to Role

The role needs permissions to manage EC2, S3, Route53, IAM, and other AWS resources for infrastructure deployment.

#### Option A: AWS CLI - Use AWS Managed Policies (Recommended)

Attach multiple AWS managed policies to provide the required permissions:

```bash
# Core infrastructure permissions
aws iam attach-role-policy \
  --role-name GitHubActionsLabLinkRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess

aws iam attach-role-policy \
  --role-name GitHubActionsLabLinkRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

aws iam attach-role-policy \
  --role-name GitHubActionsLabLinkRole \
  --policy-arn arn:aws:iam::aws:policy/IAMFullAccess

aws iam attach-role-policy \
  --role-name GitHubActionsLabLinkRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess

# Monitoring and logging permissions
aws iam attach-role-policy \
  --role-name GitHubActionsLabLinkRole \
  --policy-arn arn:aws:iam::aws:policy/CloudWatchLogsFullAccess

aws iam attach-role-policy \
  --role-name GitHubActionsLabLinkRole \
  --policy-arn arn:aws:iam::aws:policy/AWSCloudTrail_FullAccess

# Lambda and notifications permissions
aws iam attach-role-policy \
  --role-name GitHubActionsLabLinkRole \
  --policy-arn arn:aws:iam::aws:policy/AWSLambda_FullAccess

aws iam attach-role-policy \
  --role-name GitHubActionsLabLinkRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonSNSFullAccess
```

**Note:** This approach uses 8 AWS managed policies that provide full access to the required services. While broader than strictly necessary, it ensures all Terraform operations succeed without permission errors.

| Policy                     | Purpose                                            |
| -------------------------- | -------------------------------------------------- |
| `AmazonEC2FullAccess`      | EC2 instances, security groups, key pairs, EIPs    |
| `AmazonS3FullAccess`       | Terraform state, CloudTrail logs                   |
| `IAMFullAccess`            | Roles, instance profiles for CloudWatch/CloudTrail |
| `AmazonDynamoDBFullAccess` | Terraform state locking                            |
| `CloudWatchLogsFullAccess` | Log groups, metric filters, alarms                 |
| `AWSCloudTrail_FullAccess` | Audit logging                                      |
| `AWSLambda_FullAccess`     | Log processing functions                           |
| `AmazonSNSFullAccess`      | Alert notifications                                |

#### Option B: AWS CLI - Create Custom Policy

For more restrictive permissions, create a custom policy that covers all LabLink Terraform resources including EC2, ALB, CloudTrail, CloudWatch, Lambda, SNS, and Budgets.

Create `lablink-terraform-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TerraformStateManagement",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:GetBucketVersioning",
        "s3:GetBucketPolicy",
        "s3:GetBucketAcl"
      ],
      "Resource": [
        "arn:aws:s3:::lablink-terraform-state-*",
        "arn:aws:s3:::lablink-terraform-state-*/*",
        "arn:aws:s3:::tf-state-lablink-*",
        "arn:aws:s3:::tf-state-lablink-*/*"
      ]
    },
    {
      "Sid": "DynamoDBStateLocking",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:DeleteItem",
        "dynamodb:DescribeTable"
      ],
      "Resource": "arn:aws:dynamodb:*:*:table/lock-table"
    },
    {
      "Sid": "EC2FullAccess",
      "Effect": "Allow",
      "Action": ["ec2:*"],
      "Resource": "*"
    },
    {
      "Sid": "IAMRolesAndInstanceProfiles",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:GetRole",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:PassRole",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:GetRolePolicy",
        "iam:CreateInstanceProfile",
        "iam:DeleteInstanceProfile",
        "iam:GetInstanceProfile",
        "iam:AddRoleToInstanceProfile",
        "iam:RemoveRoleFromInstanceProfile",
        "iam:ListInstanceProfilesForRole",
        "iam:ListAttachedRolePolicies",
        "iam:ListRolePolicies"
      ],
      "Resource": [
        "arn:aws:iam::*:role/lablink*",
        "arn:aws:iam::*:role/lablink_*",
        "arn:aws:iam::*:instance-profile/lablink*",
        "arn:aws:iam::*:instance-profile/lablink_*"
      ]
    },
    {
      "Sid": "Route53DNS",
      "Effect": "Allow",
      "Action": [
        "route53:ListHostedZones",
        "route53:GetHostedZone",
        "route53:ListResourceRecordSets",
        "route53:ChangeResourceRecordSets",
        "route53:GetChange"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ApplicationLoadBalancer",
      "Effect": "Allow",
      "Action": [
        "elasticloadbalancing:CreateLoadBalancer",
        "elasticloadbalancing:DeleteLoadBalancer",
        "elasticloadbalancing:DescribeLoadBalancers",
        "elasticloadbalancing:DescribeLoadBalancerAttributes",
        "elasticloadbalancing:ModifyLoadBalancerAttributes",
        "elasticloadbalancing:CreateTargetGroup",
        "elasticloadbalancing:DeleteTargetGroup",
        "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeTargetGroupAttributes",
        "elasticloadbalancing:ModifyTargetGroupAttributes",
        "elasticloadbalancing:RegisterTargets",
        "elasticloadbalancing:DeregisterTargets",
        "elasticloadbalancing:DescribeTargetHealth",
        "elasticloadbalancing:CreateListener",
        "elasticloadbalancing:DeleteListener",
        "elasticloadbalancing:DescribeListeners",
        "elasticloadbalancing:ModifyListener",
        "elasticloadbalancing:AddTags",
        "elasticloadbalancing:RemoveTags",
        "elasticloadbalancing:DescribeTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ACMCertificates",
      "Effect": "Allow",
      "Action": [
        "acm:DescribeCertificate",
        "acm:ListCertificates",
        "acm:GetCertificate"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchLogsAndAlarms",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:DeleteLogGroup",
        "logs:DescribeLogGroups",
        "logs:PutRetentionPolicy",
        "logs:DeleteRetentionPolicy",
        "logs:CreateLogStream",
        "logs:DeleteLogStream",
        "logs:PutLogEvents",
        "logs:PutMetricFilter",
        "logs:DeleteMetricFilter",
        "logs:DescribeMetricFilters",
        "logs:PutSubscriptionFilter",
        "logs:DeleteSubscriptionFilter",
        "logs:DescribeSubscriptionFilters",
        "logs:TagResource",
        "logs:UntagResource",
        "logs:ListTagsForResource",
        "cloudwatch:PutMetricAlarm",
        "cloudwatch:DeleteAlarms",
        "cloudwatch:DescribeAlarms",
        "cloudwatch:EnableAlarmActions",
        "cloudwatch:DisableAlarmActions",
        "cloudwatch:TagResource",
        "cloudwatch:UntagResource",
        "cloudwatch:ListTagsForResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudTrail",
      "Effect": "Allow",
      "Action": [
        "cloudtrail:CreateTrail",
        "cloudtrail:DeleteTrail",
        "cloudtrail:DescribeTrails",
        "cloudtrail:GetTrailStatus",
        "cloudtrail:StartLogging",
        "cloudtrail:StopLogging",
        "cloudtrail:UpdateTrail",
        "cloudtrail:PutEventSelectors",
        "cloudtrail:GetEventSelectors",
        "cloudtrail:AddTags",
        "cloudtrail:RemoveTags",
        "cloudtrail:ListTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudTrailS3Bucket",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:DeleteBucket",
        "s3:PutBucketPolicy",
        "s3:DeleteBucketPolicy",
        "s3:GetBucketPolicy",
        "s3:PutBucketAcl",
        "s3:GetBucketAcl",
        "s3:PutEncryptionConfiguration",
        "s3:GetEncryptionConfiguration",
        "s3:PutBucketVersioning",
        "s3:GetBucketVersioning",
        "s3:PutBucketPublicAccessBlock",
        "s3:GetBucketPublicAccessBlock",
        "s3:PutLifecycleConfiguration",
        "s3:GetLifecycleConfiguration",
        "s3:PutBucketTagging",
        "s3:GetBucketTagging",
        "s3:ListBucket",
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::lablink-cloudtrail-*",
        "arn:aws:s3:::lablink-cloudtrail-*/*"
      ]
    },
    {
      "Sid": "Lambda",
      "Effect": "Allow",
      "Action": [
        "lambda:CreateFunction",
        "lambda:DeleteFunction",
        "lambda:GetFunction",
        "lambda:GetFunctionConfiguration",
        "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration",
        "lambda:AddPermission",
        "lambda:RemovePermission",
        "lambda:GetPolicy",
        "lambda:InvokeFunction",
        "lambda:TagResource",
        "lambda:UntagResource",
        "lambda:ListTags"
      ],
      "Resource": "arn:aws:lambda:*:*:function:lablink*"
    },
    {
      "Sid": "SNSNotifications",
      "Effect": "Allow",
      "Action": [
        "sns:CreateTopic",
        "sns:DeleteTopic",
        "sns:GetTopicAttributes",
        "sns:SetTopicAttributes",
        "sns:Subscribe",
        "sns:Unsubscribe",
        "sns:ListSubscriptionsByTopic",
        "sns:Publish",
        "sns:TagResource",
        "sns:UntagResource",
        "sns:ListTagsForResource"
      ],
      "Resource": "arn:aws:sns:*:*:lablink*"
    },
    {
      "Sid": "Budgets",
      "Effect": "Allow",
      "Action": [
        "budgets:ViewBudget",
        "budgets:CreateBudgetAction",
        "budgets:DeleteBudgetAction",
        "budgets:UpdateBudgetAction",
        "budgets:ExecuteBudgetAction",
        "budgets:ModifyBudget"
      ],
      "Resource": "*"
    }
  ]
}
```

**Note:** This policy covers all AWS services used by the LabLink Terraform configuration:

| Service        | Purpose                                                             |
| -------------- | ------------------------------------------------------------------- |
| **S3**         | Terraform state storage, CloudTrail logs                            |
| **DynamoDB**   | Terraform state locking                                             |
| **EC2**        | Allocator and client VM instances, security groups, key pairs, EIPs |
| **IAM**        | Instance profiles, CloudWatch agent roles, CloudTrail roles         |
| **Route53**    | DNS records for allocator endpoints                                 |
| **ELB**        | Application Load Balancer for HTTPS termination                     |
| **ACM**        | SSL/TLS certificates                                                |
| **CloudWatch** | Logs, metric filters, alarms for monitoring                         |
| **CloudTrail** | Audit logging and compliance                                        |
| **Lambda**     | Log processing functions                                            |
| **SNS**        | Alert notifications                                                 |
| **Budgets**    | Cost monitoring and alerts                                          |

Attach the custom policy:

```bash
aws iam put-role-policy \
  --role-name GitHubActionsLabLinkRole \
  --policy-name LabLinkTerraformPolicy \
  --policy-document file://lablink-terraform-policy.json
```

#### Option C: AWS Console

1. Go to **IAM → Roles**
2. Click on `GitHubActionsLabLinkRole`
3. Click **Add permissions** → **Attach policies**
4. Search for and attach each of these policies:

      - `AmazonEC2FullAccess`
      - `AmazonS3FullAccess`
      - `IAMFullAccess`
      - `AmazonDynamoDBFullAccess`
      - `CloudWatchLogsFullAccess`
      - `AWSCloudTrail_FullAccess`
      - `AWSLambda_FullAccess`
      - `AmazonSNSFullAccess`

5. Click **Add permissions** after selecting each policy

### 4.5: Verify Role Configuration

#### AWS CLI

Check the role exists and has correct trust policy:

```bash
# Get role details
aws iam get-role --role-name GitHubActionsLabLinkRole

# Check trust policy
aws iam get-role --role-name GitHubActionsLabLinkRole \
  --query "Role.AssumeRolePolicyDocument" --output json

# List attached policies
aws iam list-attached-role-policies --role-name GitHubActionsLabLinkRole

# List inline policies
aws iam list-role-policies --role-name GitHubActionsLabLinkRole
```

Verify the trust policy includes all your deployment repositories.

#### AWS Console

1. Go to **IAM → Roles** → `GitHubActionsLabLinkRole`
2. **Trust relationships** tab: Verify repositories are listed
3. **Permissions** tab: Verify required managed policies or custom policy is attached
4. Copy the **ARN** (e.g., `arn:aws:iam::711387140753:role/GitHubActionsLabLinkRole`)

### 4.6: Add GitHub Secrets

Four secrets are required for GitHub Actions workflows to deploy infrastructure securely.

#### For Template Repository (`lablink-template`)

1. Go to repository **Settings** → **Secrets and variables** → **Actions**
2. **Add AWS_ROLE_ARN secret:**
      - Click **New repository secret**
      - Name: `AWS_ROLE_ARN`
      - Value: `arn:aws:iam::YOUR_ACCOUNT_ID:role/GitHubActionsLabLinkRole`
      - Click **Add secret**
3. **Add AWS_REGION secret:**
      - Click **New repository secret**
      - Name: `AWS_REGION`
      - Value: Your chosen region (e.g., `us-west-2`, `eu-west-1`, `ap-northeast-1`)
      - Click **Add secret**
4. **Add ADMIN_PASSWORD secret:**
      - Click **New repository secret**
      - Name: `ADMIN_PASSWORD`
      - Value: Your secure admin password (use a password manager to generate)
      - Click **Add secret**
5. **Add DB_PASSWORD secret:** - Click **New repository secret** - Name: `DB_PASSWORD` - Value: Your secure database password (use a password manager to generate) - Click **Add secret**

**Note:** The template repository can safely include these secrets because:

- Repository permissions control who can trigger workflows
- Secrets are NOT copied when creating repos from the template
- External users must configure their own AWS credentials, region, and passwords

**Security:** The workflow automatically injects `ADMIN_PASSWORD` and `DB_PASSWORD` into configuration files before Terraform runs, replacing `PLACEHOLDER_ADMIN_PASSWORD` and `PLACEHOLDER_DB_PASSWORD`. This prevents passwords from appearing in Terraform logs.

#### For Deployment Repositories (e.g., `sleap-lablink`)

After creating a repository from the template:

1. Go to the new repository **Settings** → **Secrets and variables** → **Actions**
2. **Add all four secrets** (same process as above): - `AWS_ROLE_ARN`: Same ARN as template repository - `AWS_REGION`: Your chosen region for this deployment - `ADMIN_PASSWORD`: Your secure admin password - `DB_PASSWORD`: Your secure database password

**Important:**

- Each deployment repository needs these secrets added manually after creation
- Different deployments can use different regions if needed
- Region in secret must match region in `config/config.yaml`
- Use strong, unique passwords for each deployment

### 4.7: Update Trust Policy for New Repositories

When you create new deployment repositories, update the trust policy to include them:

#### AWS CLI

```bash
# Edit trust-policy.json to add new repository:
# "repo:YOUR_ORG/new-deployment:*"

# Update the role
aws iam update-assume-role-policy \
  --role-name GitHubActionsLabLinkRole \
  --policy-document file://trust-policy.json

# Verify update
aws iam get-role --role-name GitHubActionsLabLinkRole \
  --query "Role.AssumeRolePolicyDocument.Statement[0].Condition.StringLike"
```

#### AWS Console

1. Go to **IAM → Roles** → `GitHubActionsLabLinkRole`
2. **Trust relationships** tab
3. Click **Edit trust policy**
4. Add new repository to the `token.actions.githubusercontent.com:sub` array:

   ```json
   "token.actions.githubusercontent.com:sub": [
     "repo:YOUR_ORG/lablink:*",
     "repo:YOUR_ORG/lablink-template:*",
     "repo:YOUR_ORG/sleap-lablink:*",
     "repo:YOUR_ORG/new-deployment:*"
   ]
   ```

5. Click **Update policy**

### 4.8: Verify GitHub Actions Can Assume Role

The workflows already include the OIDC authentication step:

```yaml
- name: Configure AWS credentials via OIDC
  uses: aws-actions/configure-aws-credentials@v3
  with:
    role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
    aws-region: us-west-2
```

Test by triggering a workflow:

1. Go to **Actions** tab in GitHub
2. Select a workflow (e.g., **Terraform Deploy**)
3. Click **Run workflow**
4. Check the logs for successful AWS authentication

### Troubleshooting OIDC Setup

#### Error: "Not authorized to perform sts:AssumeRoleWithWebIdentity"

**Cause:** Repository not in trust policy

**Solution:** Add repository to trust policy (Step 4.7)

#### Error: "No OpenID Connect provider found"

**Cause:** OIDC provider doesn't exist

**Solution:** Create OIDC provider (Step 4.2)

#### Error: "Access Denied" during deployment

**Cause:** Role lacks required permissions

**Solution:** Attach required AWS managed policies or verify custom policy (Step 4.4)

#### Verify Trust Policy Includes Repository

```bash
# CLI: Check which repos can use the role
aws iam get-role --role-name GitHubActionsLabLinkRole \
  --query "Role.AssumeRolePolicyDocument.Statement[0].Condition.StringLike" \
  --output json
```

**Console:** IAM → Roles → GitHubActionsLabLinkRole → Trust relationships

## Step 5: Find AMI IDs for Your Region

AMI IDs are region-specific. You'll need to find the correct Ubuntu 24.04 AMI IDs for your chosen region.

### Find Ubuntu 24.04 AMIs

#### AWS CLI Method (Recommended)

**For Allocator (Ubuntu 24.04 with Docker):**

```bash
aws ec2 describe-images \
  --region YOUR_REGION \
  --owners 099720109477 \
  --filters "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" \
            "Name=state,Values=available" \
  --query 'sort_by(Images, &CreationDate)[-1].[ImageId,Name,CreationDate]' \
  --output table
```

**For Client VMs (Ubuntu 24.04 with Docker + NVIDIA):**

```bash
# First, find latest Ubuntu 24.04
aws ec2 describe-images \
  --region YOUR_REGION \
  --owners 099720109477 \
  --filters "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" \
            "Name=state,Values=available" \
  --query 'sort_by(Images, &CreationDate)[-1].[ImageId,Name]' \
  --output table

# Note: For GPU instances, you may need to use NVIDIA's Deep Learning AMI
# or install NVIDIA drivers via user_data
```

#### AWS Console Method

1. Go to **EC2 → AMI Catalog** in your chosen region
2. Search for "ubuntu 24.04"
3. Select "AWS Marketplace AMIs" or "Community AMIs"
4. Filter by:
   - Owner: Canonical (099720109477)
   - Architecture: 64-bit (x86)
   - Root device type: EBS
5. Choose the most recent "ubuntu-noble-24.04" AMI
6. Copy the AMI ID (e.g., `ami-0bd08c9d4aa9f0bc6`)

### Update Configuration with AMI IDs

Once you have the AMI IDs for your region, update `config/config.yaml`:

```yaml
# lablink-infrastructure/config/config.yaml
machine:
  ami_id: "ami-XXXXXXXXX" # Client VM AMI for your region
  # ...

allocator_instance:
  ami_id: "ami-YYYYYYYYY" # Allocator AMI for your region
```

### LabLink Custom AMIs (us-west-2 only)

LabLink maintains custom AMIs with Docker and NVIDIA drivers pre-installed, **only available in us-west-2**:

**Client VM AMI (Ubuntu 24.04 + Docker + NVIDIA):**

- AMI ID: `ami-0601752c11b394251`
- Description: Custom Ubuntu image with Docker and Nvidia GPU Driver pre-installed
- Architecture: x86_64
- Source: Ubuntu Server 24.04 LTS (HVM), SSD Volume Type

**Allocator VM AMI (Ubuntu 24.04 + Docker):**

- AMI ID: `ami-0bd08c9d4aa9f0bc6`
- Description: Custom Ubuntu image with Docker pre-installed
- Architecture: x86_64
- Source: Ubuntu Server 24.04 LTS (HVM), SSD Volume Type

### Using LabLink in Other Regions

If you're deploying to a region other than `us-west-2`, you have two options:

**Option 1: Copy Custom AMIs to Your Region (Recommended)**

Copy the LabLink custom AMIs to your preferred region:

```bash
# Copy Client AMI from us-west-2
aws ec2 copy-image \
  --source-region us-west-2 \
  --source-image-id ami-0601752c11b394251 \
  --name "lablink-client-ubuntu-24.04-docker-nvidia" \
  --description "Custom Ubuntu image with Docker and Nvidia GPU Driver" \
  --region YOUR_REGION

# Copy Allocator AMI from us-west-2
aws ec2 copy-image \
  --source-region us-west-2 \
  --source-image-id ami-0bd08c9d4aa9f0bc6 \
  --name "lablink-allocator-ubuntu-24.04-docker" \
  --description "Custom Ubuntu image with Docker" \
  --region YOUR_REGION
```

The copy process takes 10-30 minutes. Note the new AMI IDs from the output and update your `config/config.yaml`.

**Option 2: Use Standard Ubuntu 24.04 AMIs**

Use standard Ubuntu AMIs (Docker and NVIDIA drivers will be installed via user_data):

```bash
# Find latest Ubuntu 24.04 in your region
aws ec2 describe-images \
  --region YOUR_REGION \
  --owners 099720109477 \
  --filters "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" \
            "Name=state,Values=available" \
  --query 'sort_by(Images, &CreationDate)[-1].[ImageId,Name]' \
  --output table
```

**Note:** Standard AMIs require modifying user_data scripts to install Docker and NVIDIA drivers on first boot, increasing deployment time by ~5-10 minutes.

## Step 6: Security Groups (Optional Pre-Creation)

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

### Terraform-Managed CloudWatch Resources

When you deploy LabLink using Terraform, the following CloudWatch resources are automatically created:

**CloudWatch Agent Role**: Terraform creates an IAM role (`lablink_cloud_watch_agent_role_<suffix>`) that allows client VMs to send logs and metrics to CloudWatch. This role includes permissions for:

- `logs:CreateLogGroup` - Create new log groups
- `logs:CreateLogStream` - Create log streams within groups
- `logs:PutLogEvents` - Write log entries
- `logs:DescribeLogStreams` - List available log streams
- `cloudwatch:PutMetricData` - Send custom metrics

**CloudTrail Logs**: CloudTrail events are automatically sent to CloudWatch Logs for security monitoring.

**Metric Filters & Alarms**: Terraform creates CloudWatch metric filters to monitor:

| Metric Filter        | Purpose                                        | Alarm Threshold  |
| -------------------- | ---------------------------------------------- | ---------------- |
| `RunInstances`       | Detect mass instance launches                  | >10 in 5 minutes |
| `LargeInstances`     | Monitor expensive instance types (p4d, p3, g5) | Any launch       |
| `UnauthorizedCalls`  | Track API permission failures                  | >5 in 5 minutes  |
| `TerminateInstances` | High termination rate detection                | >10 in 5 minutes |

**SNS Notifications**: Alarms send notifications to the `lablink-admin-alerts-<suffix>` SNS topic, which emails the configured admin.

### Manual CloudWatch Configuration (Optional)

For additional monitoring beyond what Terraform provides:

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

**Required Setup:**

- [ ] S3 bucket created with versioning and encryption
- [ ] DynamoDB table created for state locking (if using remote state)
- [ ] Elastic IPs allocated for test and prod
- [ ] OIDC provider created
- [ ] IAM role for GitHub Actions configured with required permissions
- [ ] GitHub repository secrets configured (`AWS_ROLE_ARN`, `AWS_REGION`, `ADMIN_PASSWORD`, `DB_PASSWORD`)
- [ ] AMI IDs configured for your region

**Optional Setup:**

- [ ] Route 53 hosted zone created (for custom domain)
- [ ] ACM certificate created (for HTTPS via ALB)
- [ ] Secrets Manager secrets created
- [ ] Budget alerts configured

**Terraform-Managed (Automatic):**

The following resources are created automatically by Terraform during deployment:

- [ ] Application Load Balancer (ALB) with HTTPS listener
- [ ] CloudTrail trail with S3 bucket for logs
- [ ] CloudWatch log groups and metric filters
- [ ] SNS topic for admin alerts
- [ ] IAM roles for CloudWatch agent and CloudTrail
- [ ] Security groups for allocator and ALB
- [ ] Monthly budget with alert thresholds

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

| Resource             | Usage              | Estimated Cost           |
| -------------------- | ------------------ | ------------------------ |
| S3 Bucket            | <1 GB, versioning  | $0.05/month              |
| Elastic IPs          | 2 IPs (test, prod) | $0.00 (while associated) |
| Route 53 Hosted Zone | 1 zone             | $0.50/month              |
| Secrets Manager      | 2 secrets          | $0.80/month              |

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
