# AWS Setup for the Template Repository

The [template quickstart](quickstart-template.md) runs `./scripts/setup.sh`
to create the AWS and GitHub resources for a template-repository deployment.
The [CLI path](cli/first-deployment.md) uses `lablink configure` and
`lablink setup` instead. This page explains what the template setup script
creates and which settings need attention afterward.

## Before setup

You need an AWS account with permission to create IAM, EC2, S3, DynamoDB,
and, if you enable Route 53, DNS resources. Install and authenticate the
[AWS CLI](prerequisites.md#aws-cli) and [GitHub CLI](prerequisites.md), and
clone your own copy of
[lablink-template](https://github.com/talmolab/lablink-template). Run the
script from that repository's root:

```bash
./scripts/setup.sh
```

The script prompts for an AWS region, state-bucket name, GitHub repository,
optional Route 53 DNS, and admin/database passwords. It then runs
`./scripts/configure.sh` to write
`lablink-infrastructure/config/config.yaml`. Re-run `configure.sh` to edit the
config later; re-running `setup.sh` is unnecessary for routine changes.

## What setup creates

| Resource | Purpose |
|---|---|
| GitHub Actions OIDC provider and `github-actions-lablink` IAM role | Lets your repository's workflow request short-lived AWS credentials |
| S3 state bucket | Holds OpenTofu state; `setup.sh` enables versioning on a newly created bucket |
| DynamoDB `lock-table` | Serializes state changes |
| Route 53 hosted zone, when selected | Holds DNS records for the configured domain |
| Repository secrets `AWS_ROLE_ARN`, `AWS_REGION`, `ADMIN_PASSWORD`, `DB_PASSWORD` | Supplies the workflow with its role, region, and passwords |

The setup script does not explicitly configure S3 bucket encryption or public
access blocking. Apply your account's bucket policy and encryption standards
separately if they are required. The backend config sets `encrypt = true` for
state operations.

Before deploying, run the template preflight check:

```bash
./scripts/doctor.sh
```

The GitHub Actions deploy workflow also requires a repository variable named
`DEPLOYMENT_NAME` when it is triggered by a push to `test`; without it, the
workflow uses `my-lablink`. A manual run takes `deployment_name` and
`environment` as inputs.

## Region, images, and Elastic IP

Set `app.region` in `config.yaml` and use the same region for the GitHub
`AWS_REGION` secret. The allocator uses a stock Ubuntu 24.04 AMI resolved
through a public SSM parameter in that region. Its instance type is
`t3.large`; the template does not set a root block device, so the AMI's
default root volume applies. Client VMs use an 80 GiB root volume and need
an image with Docker, NVIDIA drivers, and the NVIDIA container runtime when
GPU access is required. A stock Ubuntu client AMI does not provide those.

`eip.strategy: dynamic` creates an Elastic IP for the deployment. Use
`persistent` to reuse an existing EIP; in that case, pre-allocate one and tag
it with `Name=<deployment_name>-eip-<environment>` and
`Environment=<environment>`. No `allocated_eip` OpenTofu variable or manual
EIP association edit is used. See [DNS Configuration](dns-configuration.md)
for domain and TLS choices.

## Step 4: GitHub Actions OIDC Configuration

The setup script creates or reuses the OIDC provider
`token.actions.githubusercontent.com` and role `github-actions-lablink`.
The role trust policy permits `sts:AssumeRoleWithWebIdentity` only for the
configured repository (`repo:<owner>/<repo>:*`) with audience
`sts.amazonaws.com`. If you point another repository at the same role,
update its trust policy or run setup for that repository.

The script attaches these AWS managed policies to the role:

- `AmazonEC2FullAccess`
- `AmazonS3FullAccess`
- `IAMFullAccess`
- `AmazonDynamoDBFullAccess`
- `AmazonSSMReadOnlyAccess` for the allocator AMI's public SSM parameter
- `AmazonRoute53FullAccess` when Route 53 DNS is enabled

These permissions are broad. If you replace them with a custom policy, it
must cover resources created by the current template, including its IAM
policies and roles. Check `main.tf` in the template version you deploy rather
than copying an older policy example.

## Verify and clean up

`./scripts/doctor.sh` checks the config, AWS resources, GitHub settings, and
workflow preconditions. To deploy, follow
[Quickstart: Template repo](quickstart-template.md#step-4-commit-and-deploy).
Use **Destroy LabLink Infrastructure** with matching `deployment_name` and
`environment` to remove a deployment. It destroys client VMs before the
allocator infrastructure.

The state bucket, `lock-table`, OIDC provider, and role are shared setup
resources and outlive an individual deployment. Before removing them, verify
that no environment still uses their state or role. The IAM role name created
by `setup.sh` is `github-actions-lablink`.
