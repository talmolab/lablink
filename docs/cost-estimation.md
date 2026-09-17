# Cost Estimation

LabLink's AWS costs depend on your region, instance types, how long the
allocator and client VMs run, attached storage, public IPv4 addresses, data
transfer, and optional DNS or load balancing. Check the
[AWS Pricing Calculator](https://calculator.aws/) for a current estimate
before deploying.

## Get a deployment estimate

For a CLI deployment, run `lablink status`. Its **Cost Estimate (daily)**
section uses the AWS Pricing API when available and a built-in fallback table
otherwise. It includes the allocator, EBS, optional ALB and Route 53 costs,
and client VMs.

The template repository also has a script. Run it from the root of your
template checkout; it reads
`lablink-infrastructure/config/config.yaml`:

```bash
./scripts/estimate-costs.sh
```

The script requires `jq`; the AWS CLI enables live price lookups. Its current
allocator EBS estimate assumes a 20 GiB root volume, while the template does
not set `root_block_device` and uses the selected AMI's default. Check the
deployed volume size before relying on that line of the estimate.

## Compute

The template runs one `t3.large` allocator. Its instance type is fixed in
`lablink-infrastructure/main.tf`; `machine.machine_type` selects the **client
VM** type. The allocator accrues EC2 charges while running. Client EC2 usage
scales with the number of machines and their running hours:

```text
client compute cost = client count × hours running × hourly instance price
```

Destroy client VMs when a workshop ends. Stopping an EC2 instance ends its
compute usage charge, but its EBS volumes still accrue storage charges; see
[AWS's instance lifecycle guide](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html).

### GPU Instance Types

The CLI wizard offers these GPU client types; `config.yaml` can specify any
EC2 instance type supported in your region. Use the
[AWS Pricing Calculator](https://calculator.aws/) for current regional prices.

| Type | GPU | vCPUs | RAM | GPU memory |
|---|---|---:|---:|---:|
| `g4dn.xlarge` | T4 | 4 | 16 GiB | 16 GiB |
| `g4dn.2xlarge` | T4 | 8 | 32 GiB | 16 GiB |
| `g5.xlarge` | A10G | 4 | 16 GiB | 24 GiB |
| `g5.2xlarge` | A10G | 8 | 32 GiB | 24 GiB |
| `p3.2xlarge` | V100 | 8 | 61 GiB | 16 GiB |

The CPU-only wizard choices are `t3.large`, `t3.xlarge`, `t3.2xlarge`,
`m5.xlarge`, and `m5.2xlarge`. LabLink does not currently provision Spot
client instances.

## Storage and networking

- **EBS:** The template sets client root volumes to 80 GiB. It leaves the
  allocator root volume at the AMI default. EBS storage can keep accruing
  charges while an instance is stopped.
- **Public IPv4:** AWS currently charges **$0.005 per address-hour** for both
  associated and idle public IPv4 addresses, including Elastic IPs. One
  continuously allocated address is about $3.65 for a 730-hour month. Check
  [Amazon VPC pricing](https://aws.amazon.com/vpc/pricing/) for the current
  rate and any applicable credits.
- **State storage:** The S3 state bucket and DynamoDB lock table remain after
  a deployment is destroyed. S3 versioning retains old state versions until
  you manage them.
- **Optional services:** Route 53 hosted zones and DNS queries, an ALB for
  `ssl.provider: acm`, and internet data transfer can add charges. The
  template does not create S3 database backups or CloudWatch log storage as
  part of a standard deployment.

## Track and limit spending

Use AWS Cost Explorer or a budget in the Billing console to track actual
charges. Template resources are tagged with
`Project=<deployment_name>`, `Environment=<environment>`, and
`ManagedBy=terraform`; filter by those values to inspect a deployment.
The template's tag names are fixed in its OpenTofu files.

AWS Free Tier terms depend on when the account was created and its plan.
Accounts created on or after July 15, 2025 use the newer credit-based
program; see the [AWS Free Tier guide](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier.html)
and your account's Billing console. Do not assume a `t3.large` allocator or
GPU client is covered by an older micro-instance allowance.

For deployment teardown, see [Managing Deployments](cli/managing-deployments.md#destroy-the-deployment)
or [Template Repository Deployment](deployment.md#destroying-a-deployment).
