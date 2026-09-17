# Quickstart: Template repo

Deploy LabLink to AWS by creating a repository from
[lablink-template](https://github.com/talmolab/lablink-template). Its GitHub
Actions workflow runs OpenTofu against S3-backed state when you push to `test`
or start **Deploy LabLink Infrastructure** manually. Pushing to `main` alone
does not deploy.

!!! tip "Prefer a local flow?"
    The [CLI quickstart](cli/first-deployment.md) is the recommended route for
    a standard deployment. Use this template when you want to maintain its
    OpenTofu resources or GitHub Actions workflow.

## Prerequisites

Before starting, ensure you have completed:

- [x] [Prerequisites](prerequisites.md): AWS Account, AWS CLI, GitHub CLI (`gh`), and Git installed

## Step 1: Create Your Repository

<div class="video-container">
  <video controls width="100%">
    <source src="../assets/videos/step1-create-repo.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

Click the **"Use this template"** button on the [lablink-template repository](https://github.com/talmolab/lablink-template) to create your own deployment repository.

Then clone your new repository:

```bash
git clone https://github.com/YOUR_ORG/YOUR_REPO.git
cd YOUR_REPO
```

## Step 2: Run Setup

<div class="video-container">
  <video controls width="100%">
    <source src="../assets/videos/step2-run-setup.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

Run the setup script to create all required AWS resources and configure GitHub secrets:

```bash
./scripts/setup.sh
```

The script will prompt you for:

- AWS region (e.g., `us-west-2`)
- S3 bucket name for OpenTofu state
- GitHub repository (e.g., `YOUR_ORG/YOUR_REPO`)
- Optional DNS settings (Route 53)

It automatically:

- Creates an OIDC identity provider for GitHub Actions
- Creates an IAM role with required permissions
- Creates an S3 bucket for OpenTofu state with versioning
- Creates a DynamoDB table for state locking
- Optionally creates a Route 53 hosted zone
- Sets four GitHub repository secrets: `AWS_ROLE_ARN`, `AWS_REGION`, `ADMIN_PASSWORD`, `DB_PASSWORD`
- Generates secure passwords for admin and database access

For the resources and IAM permissions the script creates, see
[AWS Setup](aws-setup.md).

## Step 3: Configure

After setup completes, the script automatically runs `./scripts/configure.sh` to generate your deployment configuration.

Either tool below writes `lablink-infrastructure/config/config.yaml`. The
shell script retains its example-file comments and all fields. The CLI wizard
rewrites the file without comments and does not expose every template field,
including `allocator.image_tag` and `machine.image`; use the shell script or
edit those fields in the file when needed.

=== "Shell script (no install)"

    ```bash
    ./scripts/configure.sh
    ```

    Included in the template repo, so there is nothing extra to install.

=== "Optional CLI wizard"

    ```bash
    uv tool install lablink-cli
    lablink configure --template
    ```

    The same interactive wizard the [CLI quickstart](cli/first-deployment.md) uses — arrow-key menus, live validation, and a built-in editor for custom startup scripts. Run it from your repository root.

    `--template` is what makes it write the repo's config file instead of `~/.lablink/config.yaml`, fill in the password placeholders the deploy workflow expects, and skip the AWS state setup that Step 2 already did. See the [CLI reference](reference/cli.md#configuring-a-template-repo) for details.

Both tools leave the passwords as `PLACEHOLDER_ADMIN_PASSWORD` and
`PLACEHOLDER_DB_PASSWORD`. **Deploy LabLink Infrastructure** replaces them
with the `ADMIN_PASSWORD` and `DB_PASSWORD` secrets from Step 2, so leave
those placeholders unchanged in the committed config.

!!! note "Re-running Configuration"
    You can re-run either tool at any time to update settings; both load your existing values as the defaults.

## Step 4: Commit and Deploy

<div class="video-container">
  <video controls width="100%">
    <source src="../assets/videos/step4-commit-deploy.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

Run `./scripts/doctor.sh` for a local preflight check. Commit your
configuration, then push to the branch you want to use:

```bash
git add lablink-infrastructure/config/config.yaml
git commit -m "Add deployment configuration"
git push
```

Start the deployment in one of two ways:

- Push the commit to `test`. That branch triggers the **Deploy LabLink
  Infrastructure** workflow for the `test` environment. Set the repository
  variable `DEPLOYMENT_NAME` to your config's deployment name first; otherwise
  the workflow uses `my-lablink`.
- In the **Actions** tab, select **Deploy LabLink Infrastructure** and click
  **Run workflow**. Enter `deployment_name` and choose `test`, `prod`, or
  `ci-test` for `environment`.

<div class="video-container">
  <video controls width="100%">
    <source src="../assets/videos/step4-deploy.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

Monitor the run in the **Actions** tab. It will:

- Authenticate to AWS via OIDC
- Pull the configured allocator image and validate `config.yaml`
- Replace password placeholders and pin `deployment_name` / `environment` in the working copy
- Initialize OpenTofu with the S3 backend
- Deploy the allocator EC2 instance, security groups, and SSH key pair
- Upload the allocator SSH key as an artifact retained for one day, then verify the deployment
- Run `tofu destroy` if the apply step fails

## Step 5: Verify

<div class="video-container">
  <video controls width="100%">
    <source src="../assets/videos/step5-verify.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

Once the deployment completes:

### Access the Web UI

1. Find `allocator_fqdn` in the workflow's OpenTofu output. It contains the
   full URL, including `http://` or `https://` for your selected SSL mode.
2. Open that URL in your browser.
3. Log in with the configured `app.admin_user` and the `ADMIN_PASSWORD` saved
   during setup.

### Create Test VMs

1. Open `/admin` on the allocator URL.
2. Click **Create New VM Instance**, which opens the **Launch New LabLink Instances** page
3. Enter number of VMs (try 1-2 for testing)
4. Click **Launch VMs** and allow about 5–7 minutes for startup; check the
   instance status before inviting participants.

### Verify Deployment Script (Optional)

The template includes a verification script:

```bash
./scripts/verify-deployment.sh test
```

## Step 6: Cleanup

<div class="video-container">
  <video controls width="100%">
    <source src="../assets/videos/step6-cleanup.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

When you're done testing, destroy the infrastructure:

=== "Via GitHub Actions"

    Run **Destroy LabLink Infrastructure** from the Actions tab with the same
    `deployment_name` and `environment`, and enter `yes` for `confirm_destroy`.
    It attempts to destroy client VMs before the allocator infrastructure.

=== "Via OpenTofu"

    Destroy client VMs from the allocator admin UI first. From the repository
    root, initialize the same environment and destroy the allocator:

    ```bash
    ./scripts/init-terraform.sh test
    cd lablink-infrastructure
    tofu destroy -var="deployment_name=my-lablink" -var="environment=test"
    ```

=== "Cleanup Orphaned Resources"

    If resources were left behind (e.g., from a failed destroy), use the cleanup script:

    ```bash
    ./scripts/cleanup-orphaned-resources.sh test --dry-run
    ./scripts/cleanup-orphaned-resources.sh test
    ```

!!! warning "AWS Costs"
    EC2 instances incur charges while running. Always destroy test resources when not in use. See [Cost Estimation](cost-estimation.md) for details.

## Next Steps

- **[Configuration](configuration.md)**: Customize instance types, machine images, and deployment settings
- **[Adapting for Your Software](adapting.md)**: Install your own tutorial software on client VMs
- **[Deployment](deployment.md)**: Production deployment with CI/CD workflows
- **[Security](security.md)**: Review security best practices before going to production
