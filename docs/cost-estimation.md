# Cost Estimation

This guide helps you understand and estimate AWS costs for running LabLink.

## Cost Overview

LabLink costs consist of:

1. **Infrastructure costs** (one-time or monthly)
2. **Compute costs** (per hour, based on usage)
3. **Storage costs** (monthly)
4. **Data transfer costs** (per GB)

## AWS Pricing Calculator

For exact pricing, use the [AWS Pricing Calculator](https://calculator.aws/).

!!! note
    Prices shown are for **us-west-2** region as of January 2025. Check current AWS pricing for your region.

## Infrastructure Costs (Minimal)

### S3 Bucket (Terraform State)

**Purpose**: Store Terraform state files

| Item | Usage | Monthly Cost |
|------|-------|--------------|
| Storage | < 1 GB | $0.02 |
| Requests | ~ 100/month | $0.01 |
| Versioning | Enabled | Included |

**Estimated Monthly Cost**: **$0.05**

### Elastic IPs

**Purpose**: Static IP addresses for allocators

| Item | Quantity | Monthly Cost |
|------|----------|--------------|
| Elastic IP (associated) | 2 (test, prod) | $0.00 |
| Elastic IP (unassociated) | 0 | $0.00 |

!!! warning
    Unassociated Elastic IPs cost **$0.005/hour** ($3.60/month). Always associate or release unused IPs.

**Estimated Monthly Cost**: **$0.00** (when associated)

### Route 53 (Optional)

**Purpose**: DNS management for custom domains

| Item | Quantity | Monthly Cost |
|------|----------|--------------|
| Hosted Zone | 1 | $0.50 |
| Queries | 1M | $0.40 |

**Estimated Monthly Cost**: **$0.90**

### Total Infrastructure Cost

**Without Route 53**: **~$0.05/month**
**With Route 53**: **~$0.95/month**

## Compute Costs (Variable)

### Allocator Instance

Costs for running the allocator EC2 instance.

#### Instance Type Options

| Instance Type | vCPUs | RAM | Price (On-Demand) | Monthly (24/7) |
|---------------|-------|-----|-------------------|----------------|
| **t2.micro** | 1 | 1 GB | $0.0116/hour | $8.50 |
| **t2.small** | 1 | 2 GB | $0.023/hour | $16.79 |
| **t2.medium** | 2 | 4 GB | $0.0464/hour | $33.87 |
| **t3.micro** | 2 | 1 GB | $0.0104/hour | $7.59 |
| **t3.small** | 2 | 2 GB | $0.0208/hour | $15.18 |

**Recommended**: **t2.micro** for dev/test, **t2.small** for production

**Estimated Monthly Cost**: **$8.50 - $17** (if running 24/7)

#### Cost Optimization

**Option 1: Terminate When Not Needed**
- Stop allocator during off-hours
- Cost: Only when running
- Example: 8 hours/day × 20 days = 160 hours = $1.86/month (t2.micro)

**Option 2: Reserved Instances** (1-year commitment)
- Up to 75% savings
- t2.micro: $5.03/month (vs $8.50)

**Option 3: Savings Plans**
- Flexible commitment
- Similar savings to Reserved Instances

### Client VM Instances

Costs for running research workload VMs.

#### GPU Instance Types

| Instance Type | GPU | vCPUs | RAM | GPU Memory | Price/Hour | Monthly (24/7) |
|---------------|-----|-------|-----|------------|------------|----------------|
| **g4dn.xlarge** | T4 | 4 | 16 GB | 16 GB | $0.526 | $384 |
| **g4dn.2xlarge** | T4 | 8 | 32 GB | 16 GB | $0.752 | $549 |
| **g4dn.4xlarge** | T4 | 16 | 64 GB | 16 GB | $1.204 | $879 |
| **g5.xlarge** | A10G | 4 | 16 GB | 24 GB | $1.006 | $735 |
| **g5.2xlarge** | A10G | 8 | 32 GB | 24 GB | $1.212 | $885 |
| **p3.2xlarge** | V100 | 8 | 61 GB | 16 GB | $3.06 | $2,234 |

**Most Common**: **g4dn.xlarge** (good balance of performance and cost)

#### Cost Optimization Strategies

**Option 1: Spot Instances** (Up to 90% savings)

```hcl
# terraform/main.tf
resource "aws_instance" "client" {
  instance_market_options {
    market_type = "spot"
    spot_options {
      max_price = "0.20"  # Max price you're willing to pay
    }
  }
}
```

- **g4dn.xlarge Spot**: ~$0.158/hour (vs $0.526 on-demand)
- **Savings**: 70%
- **Risk**: Can be terminated if capacity needed

**Option 2: Terminate After Use**
- Only run VMs when actively working
- Cost: Per-hour usage only

**Example**: 10 VMs × 8 hours = 80 hours × $0.526 = **$42.08**

**Option 3: Right-Size Instance Types**
- Use smallest instance that meets requirements
- Test on smaller instances first

#### CPU-Only Instance Types (Non-GPU)

For non-GPU workloads:

| Instance Type | vCPUs | RAM | Price/Hour | Monthly (24/7) |
|---------------|-------|-----|------------|----------------|
| **c5.xlarge** | 4 | 8 GB | $0.17 | $124 |
| **c5.2xlarge** | 8 | 16 GB | $0.34 | $248 |
| **c6i.xlarge** | 4 | 8 GB | $0.17 | $124 |

**Use Case**: Data processing without GPU requirements

## Storage Costs

### EBS Volumes (EC2 Storage)

| Volume Type | Allocator | Client VM | Price/GB-Month |
|-------------|-----------|-----------|----------------|
| **gp3** | 30 GB | 100 GB | $0.08 |

**Allocator**: 30 GB × $0.08 = **$2.40/month**
**Client VM**: 100 GB × $0.08 = **$8.00/month per VM**

**Note**: EBS charges apply even for stopped instances. Terminate to avoid charges.

### S3 Storage (Backups)

| Item | Usage | Monthly Cost |
|------|-------|--------------|
| Standard Storage | 10 GB | $0.23 |
| Glacier (Archive) | 100 GB | $0.40 |

**Use Case**: Database backups, logs, artifacts

## Data Transfer Costs

### Inbound (Free)

- Data transfer **into** AWS is free
- Pulling Docker images: Free
- SSH/API calls into instances: Free

### Outbound

| Destination | Price per GB |
|-------------|--------------|
| First 100 GB/month | Free |
| Next 10 TB/month | $0.09 |
| Internet (general) | $0.09 |

**Typical Usage**: < 100 GB/month (covered by free tier)

### Inter-Region Transfer

If using resources across regions:

| Transfer Type | Price per GB |
|---------------|--------------|
| Cross-region | $0.02 |

**Avoid**: Keep all resources in same region

## Example Cost Scenarios

### Scenario 1: Development/Testing

**Setup**:
- 1 allocator (t2.micro)
- 2 client VMs (g4dn.xlarge)
- Running 40 hours/month

**Costs**:
- Infrastructure: $0.05/month
- Allocator: 40 hours × $0.0116 = $0.46
- Client VMs: 2 × 40 hours × $0.526 = $42.08
- Storage: $2.40 (allocator) + $16.00 (2 clients) = $18.40

**Total**: **~$61/month**

### Scenario 2: Light Production Use

**Setup**:
- 1 allocator (t2.small, 24/7)
- 5 client VMs (g4dn.xlarge)
- VMs running 160 hours/month each

**Costs**:
- Infrastructure: $0.95/month (with Route 53)
- Allocator: $16.79/month
- Client VMs: 5 × 160 hours × $0.526 = $420.80
- Storage: $2.40 + (5 × $8.00) = $42.40

**Total**: **~$481/month**

### Scenario 3: Heavy Production Use

**Setup**:
- 1 allocator (t2.small, 24/7, Reserved Instance)
- 20 client VMs (g4dn.xlarge, Spot Instances)
- VMs running 320 hours/month each

**Costs**:
- Infrastructure: $0.95/month
- Allocator: $5.03/month (Reserved Instance)
- Client VMs: 20 × 320 hours × $0.158 (Spot) = $1,011.20
- Storage: $2.40 + (20 × $8.00) = $162.40

**Total**: **~$1,182/month**

**Savings vs On-Demand**: ~$3,200/month (70% reduction)

### Scenario 4: Minimal (Cost-Conscious)

**Setup**:
- 1 allocator (t2.micro)
- 3 client VMs (g4dn.xlarge, Spot)
- Only running when actively working (40 hours/month)

**Costs**:
- Infrastructure: $0.05/month
- Allocator: 40 hours × $0.0116 = $0.46
- Client VMs: 3 × 40 hours × $0.158 (Spot) = $18.96
- Storage: Minimal (terminate when done) = $0.50

**Total**: **~$20/month**

## Cost Monitoring

### Set Up Billing Alerts

**Step 1: Create SNS Topic**
```bash
aws sns create-topic --name lablink-billing-alerts
```

**Step 2: Subscribe Email**
```bash
aws sns subscribe \
  --topic-arn arn:aws:sns:us-west-2:ACCOUNT_ID:lablink-billing-alerts \
  --protocol email \
  --notification-endpoint your-email@example.com
```

**Step 3: Create Budget**
```bash
aws budgets create-budget --account-id ACCOUNT_ID --budget file://budget.json
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

### View Current Costs

**AWS Console**:
1. Navigate to **Billing Dashboard**
2. View **Cost Explorer**
3. Filter by tag `Project: LabLink`

**AWS CLI**:
```bash
aws ce get-cost-and-usage \
  --time-period Start=2025-01-01,End=2025-01-31 \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --filter file://filter.json
```

**`filter.json`**:
```json
{
  "Tags": {
    "Key": "Project",
    "Values": ["LabLink"]
  }
}
```

### Tag Resources

Tag all resources for cost tracking:

```hcl
# terraform/main.tf
resource "aws_instance" "lablink_allocator" {
  # ... other config

  tags = {
    Name    = "lablink-allocator-${var.environment}"
    Project = "LabLink"
    Environment = var.environment
    ManagedBy = "Terraform"
  }
}
```

View costs by tag in Cost Explorer.

## Cost Optimization Checklist

- [ ] Use Spot Instances for client VMs (70-90% savings)
- [ ] Terminate VMs when not in use
- [ ] Use Reserved Instances for always-on allocators (75% savings)
- [ ] Right-size instance types (don't over-provision)
- [ ] Use gp3 volumes instead of gp2 (20% cheaper)
- [ ] Set up billing alerts
- [ ] Monitor costs weekly in Cost Explorer
- [ ] Tag all resources for cost attribution
- [ ] Use Lifecycle Policies to delete old S3 backups
- [ ] Terminate (not stop) unused instances
- [ ] Release unused Elastic IPs
- [ ] Clean up old EBS snapshots

## Free Tier

New AWS accounts get 12 months of free tier:

| Service | Free Tier (Monthly) |
|---------|---------------------|
| EC2 (t2.micro) | 750 hours |
| EBS (gp2/gp3) | 30 GB |
| S3 | 5 GB storage |
| Data Transfer | 100 GB out |

**Note**: GPU instances (g4dn, g5, p3) are **not** included in free tier.

## Hidden Costs to Watch

1. **Unassociated Elastic IPs**: $3.60/month each
2. **Stopped instances with EBS**: Storage charges still apply
3. **Old EBS snapshots**: Accumulate over time
4. **Unused load balancers**: $16-18/month
5. **NAT Gateways**: $32/month + data transfer
6. **Idle RDS instances**: $15-200/month

**Solution**: Regular cleanup and monitoring

## Cost Comparison

### LabLink vs Self-Managed

| Aspect | LabLink | Self-Managed |
|--------|---------|--------------|
| Infrastructure setup | $0-1/month | $0 |
| Allocator runtime | $8-17/month | $0 (your time) |
| Client VMs | Same | Same |
| Management time | Minimal | Significant |

**LabLink advantage**: Time savings outweigh small infrastructure costs

### LabLink vs Managed Services

| Service | Monthly Cost (5 VMs) | Setup Complexity |
|---------|----------------------|------------------|
| **LabLink** | ~$481 | Moderate |
| **AWS Batch** | ~$500+ | High |
| **SageMaker** | ~$600+ | Moderate |
| **Cloud GPUs (vast.ai)** | ~$200-400 | Low |

**LabLink advantage**: Balance of cost, features, and control

## Budget Recommendations

### By Use Case

| Use Case | Recommended Monthly Budget |
|----------|----------------------------|
| Individual researcher (occasional) | $50-100 |
| Individual researcher (regular) | $200-500 |
| Small research group | $500-1,500 |
| Large research group | $1,500-5,000+ |

## Next Steps

- **[AWS Setup](aws-setup.md)**: Set up billing alerts
- **[Configuration](configuration.md)**: Choose cost-effective instance types
- **[Deployment](deployment.md)**: Deploy with cost optimization

## Questions About Costs?

- Check [AWS Pricing](https://aws.amazon.com/pricing/)
- Use [AWS Pricing Calculator](https://calculator.aws/)
- Contact AWS Support for enterprise pricing