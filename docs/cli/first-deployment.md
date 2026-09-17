# First Deployment

This walkthrough takes you from a clean install through a live allocator and
then tears down the deployment. The shared state bucket and lock table remain
for reuse. Budget about 15 minutes end to end.

!!! note "This is the AWS path"
    Everything below assumes the default `provider: aws` — the allocator on EC2,
    client VMs provisioned by OpenTofu. To run the allocator on a machine you
    already have and register your own client boxes instead, follow
    [Bring-Your-Own Clients](byo-clients.md); it needs no AWS account and no
    OpenTofu.

## Before you start

Make sure you've completed [Installation](installation.md) and that `lablink doctor` reports clean values for "OpenTofu installed" and "AWS credentials". The other checks will light up as you go.

## Step 1: Configure

```bash
lablink configure
```

<div class="video-container">
  <video controls width="100%">
    <source src="../../assets/videos/cli-01-configure.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

This launches an interactive TUI wizard that walks you through:

- **Deployment name and provider** — the label used for AWS resources and the working directory under `~/.lablink/deploy/`; choose AWS for this guide.
- **Region and machine** — choose an AWS region, client instance type, software, and optional repository. The client AMI can resolve automatically in-region or be set in `machine.ami_id`; `lablink doctor` verifies it.
- **DNS and SSL** — choose IP-only, Let's Encrypt, Cloudflare, ACM, or self-signed TLS.
- **Startup, monitoring, and review** — set optional startup and session-metrics options, then review the config.

The wizard writes `~/.lablink/config.yaml` and then **automatically runs `lablink setup`** to create the AWS resources OpenTofu needs before it can run:

1. An **S3 bucket** for OpenTofu state (versioning enabled).
2. A **DynamoDB table** for state locking.

If you enabled a Terraform-managed DNS zone, setup also creates the Route 53
zone. It writes `bucket_name` and, when applicable, `dns.zone_id` back to the
config file.

(Manual-provider configs skip that step — there's no remote state to bootstrap.)

!!! tip "Re-running the wizard"
    `lablink configure` is idempotent. Run it again anytime to edit the config — it loads your existing values as defaults.

You can inspect what was written with:

```bash
lablink show-config
```

Before deploying, edit `db.password` in `~/.lablink/config.yaml` to a strong
unique value. The wizard and AWS deploy prompt do not collect the database
password; the schema default is `lablink`. The admin password is prompted for
in Step 3 and stays in the deployment working copy.

## Step 2: Sanity check

```bash
lablink doctor
```

<div class="video-container">
  <video controls width="100%">
    <source src="../../assets/videos/cli-02-doctor.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

*The clip starts with `lablink show-config` from Step 1, then runs `doctor`.*

The AWS path runs seven checks, including an OpenTofu version check (minimum
1.10.0), a `Client AMI` check against EC2 in your chosen region, and a `Viewer
streaming` check. The latter warns if HTTP would disable H.264 in the browser.
See [`doctor`](../reference/cli.md#doctor) for the full list. If a row is
`FAIL`, follow the action in its detail column before deploying. `doctor`
currently exits with code 0 even when a check fails, so inspect the table.

## Step 3: Deploy

```bash
lablink deploy
```

<div class="video-container">
  <video controls width="100%">
    <source src="../../assets/videos/cli-03-deploy.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

*Recorded at 4× — the real `tofu apply` and health wait take 3–8 minutes. Continues into Step 4's `lablink status`.*

This will:

1. Download the pinned `lablink-template` OpenTofu files into `~/.lablink/cache/terraform/<version>/` (first run only).
2. Copy them into a working directory at `~/.lablink/deploy/<deployment-name>/<environment>/`.
3. Prompt you for an **admin username** (default `admin`) and **admin password** on each AWS deploy. These are written into the working copy of `config.yaml`, not `~/.lablink/config.yaml`.
4. Run `tofu init` + `tofu apply`, showing the plan and asking for confirmation.
5. Wait for the allocator EC2 instance to come up and its `/api/health` endpoint to report `healthy`.

Expect 2–5 minutes for OpenTofu + another 1–3 minutes for the allocator to finish its first-boot container start.

!!! tip "Skip interactive confirmations"
    Pass `-y` / `--yes` to skip OpenTofu plan confirmation. The admin credentials are still prompted for.

When deploy completes, use the `Admin URL` printed by `lablink status`. It
accounts for the chosen DNS and SSL settings.

## Step 4: Verify

```bash
lablink status
```

The output includes OpenTofu state, health checks, client inventory, and a
daily cost estimate. See the [status reference](../reference/cli.md#status)
for each section.

Open the printed `Admin URL` in a browser and log in with the credentials you
entered during deploy.

## Step 5: Launch a client VM

```bash
lablink client launch --num-vms 1
```

<div class="video-container">
  <video controls width="100%">
    <source src="../../assets/videos/cli-04-launch-destroy.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

*Also recorded at 4×, and continues through Step 6's `lablink destroy`.*

The CLI calls the allocator's create-VM endpoint, which provisions the instance via the allocator's own OpenTofu workspace (not the CLI's). Run `lablink status` again to see the new VM appear.

## Step 6: Tear down

When you're done, destroy everything the CLI created:

```bash
lablink destroy
```

This runs `tofu destroy` on the deployment workspace and removes the EC2 instance, security groups, key pair, and any ALB/Route 53 records OpenTofu owns. Client VMs launched through the allocator are destroyed along with the allocator.

!!! warning "Costs don't stop until destroy finishes"
    The allocator EC2 instance, EBS volume, and (if configured) ALB accrue charges while running. See [Cost Estimation](../cost-estimation.md).

After destroy, the S3 state bucket and DynamoDB lock table still exist for a
future deploy. `lablink cleanup` clears per-deployment state objects and lock
entries, but does not delete the bucket or table.

## Next steps

- [Managing Deployments](managing-deployments.md) — day-to-day operations, logs, metrics export.
- [CLI Reference](../reference/cli.md) — every command and flag.
- [Configuration](../configuration.md) — full reference for the `config.yaml` schema the wizard writes.
