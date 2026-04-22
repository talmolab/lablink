# First Deployment

This walkthrough takes you from a clean install through a live allocator and back to an empty AWS account. Budget about 15 minutes end to end.

## Before you start

Make sure you've completed [Installation](installation.md) and that `lablink doctor` reports clean values for "Terraform installed" and "AWS credentials". The other checks will light up as you go.

## Step 1: Configure

```bash
lablink configure
```

This launches an interactive TUI wizard that walks you through:

- **Deployment name** — a short label (e.g. `sleap-workshop`, `dev`). Used to tag AWS resources and as the folder name under `~/.lablink/deploys/`.
- **AWS region** — e.g. `us-west-2`. Must be a region the CLI has an AMI mapping for (run `lablink doctor` to see the list).
- **Machine settings** — client VM instance type and AMI. Defaults come from the bundled `lablink-template` config.
- **DNS / SSL** — optional Route 53 domain and ACM certificate configuration.
- **Monitoring** — optional CloudWatch alarms and CloudTrail.

The wizard writes `~/.lablink/config.yaml` and then **automatically runs `lablink setup`** to create the two AWS resources Terraform needs before it can run:

1. An **S3 bucket** for Terraform state (versioned + encrypted).
2. A **DynamoDB table** for state locking.

!!! tip "Re-running the wizard"
    `lablink configure` is idempotent. Run it again anytime to edit the config — it loads your existing values as defaults.

You can inspect what was written with:

```bash
lablink show-config
```

## Step 2: Sanity check

```bash
lablink doctor
```

All six checks should now pass:

```text
┌─────────────────────────┬────────┬─────────────────────────────────────┐
│ Check                   │ Status │ Detail                              │
├─────────────────────────┼────────┼─────────────────────────────────────┤
│ Terraform installed     │ PASS   │ v1.6.6 (/usr/local/bin/terraform)   │
│ Config file             │ PASS   │ ~/.lablink/config.yaml              │
│ Config validates        │ PASS   │ No errors                           │
│ AWS credentials         │ PASS   │ Account: 123…, Identity: arn:…      │
│ S3 state bucket         │ PASS   │ tf-state-lablink-…                  │
│ AMI for region          │ PASS   │ us-west-2 → ami-0bd08c9d…           │
└─────────────────────────┴────────┴─────────────────────────────────────┘
```

If any row is `FAIL`, the detail column tells you which command to run next (usually `lablink configure` or `aws configure`).

## Step 3: Deploy

```bash
lablink deploy
```

This will:

1. Download the pinned `lablink-template` Terraform files into `~/.lablink/cache/terraform/<version>/` (first run only).
2. Copy them into a working directory at `~/.lablink/deploys/<deployment-name>/`.
3. Prompt you once for an **admin password** and **database password**. These are injected into the Terraform variables — they are not stored in `config.yaml`.
4. Run `terraform init` + `terraform apply`, showing the plan and asking for confirmation.
5. Wait for the allocator EC2 instance to come up and its `/api/health` endpoint to report `healthy`.

Expect 2–5 minutes for Terraform + another 1–3 minutes for the allocator to finish its first-boot container start.

!!! tip "Skip interactive confirmations"
    Pass `-y` / `--yes` to skip Terraform plan confirmation. Admin/DB passwords are still prompted for.

When deploy completes, note the `ec2_public_ip` in the Terraform output — that's your allocator URL.

## Step 4: Verify

```bash
lablink status
```

This shows four sections:

- **Terraform State** — outputs like `ec2_public_ip`, `ec2_public_dns`, and any DNS/ALB records.
- **Health Checks** — DNS resolution (if you configured a domain), `/api/health` response, and SSL certificate expiry (if HTTPS is enabled).
- **Client VMs** — per-VM state reported by the allocator (empty until you run `lablink launch-client`).
- **Cost Estimate** — daily and monthly dollar estimates for the allocator, EBS, optional ALB/Route 53, and running client VMs.

Open the allocator in a browser using `http://<ec2_public_ip>` (or your configured domain) and log in with username `admin` and the admin password you entered during deploy.

## Step 5: Launch a client VM

```bash
lablink launch-client --num-vms 1
```

The CLI calls the allocator's create-VM endpoint, which provisions the instance via the allocator's own Terraform workspace (not the CLI's). Run `lablink status` again to see the new VM appear.

## Step 6: Tear down

When you're done, destroy everything the CLI created:

```bash
lablink destroy
```

This runs `terraform destroy` on the deployment workspace and removes the EC2 instance, security groups, key pair, and any ALB/Route 53 records Terraform owns. Client VMs launched through the allocator are destroyed along with the allocator.

!!! warning "Costs don't stop until destroy finishes"
    The allocator EC2 instance, EBS volume, and (if configured) ALB accrue charges while running. See [Cost Estimation](../cost-estimation.md).

After destroy, the S3 state bucket and DynamoDB lock table still exist — they're cheap (~$0.05/month) and reused on the next deploy. If you want to remove them too, see [cleanup](managing-deployments.md#cleanup-orphaned-resources).

## Next steps

- [Managing Deployments](managing-deployments.md) — day-to-day operations, logs, metrics export.
- [CLI Reference](../reference/cli.md) — every command and flag.
- [Configuration](../configuration.md) — full reference for the `config.yaml` schema the wizard writes.
