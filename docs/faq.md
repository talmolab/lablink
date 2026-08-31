# Frequently Asked Questions (FAQ)

Common questions about LabLink. If something here doesn't resolve your problem, [Troubleshooting](troubleshooting.md) goes deeper on failures, and `lablink doctor` checks your setup directly.

## General

??? note "What is LabLink?"
    LabLink is a virtual teaching lab accessible through a web browser. It gives participants a full desktop with your software pre-installed — they need nothing but a browser. You can run it on AWS, or on hardware you already own.

??? note "Who is LabLink for?"
    - Instructors running hands-on software workshops or tutorials
    - Research labs teaching computational tools to students or collaborators
    - Anyone who needs to give participants a pre-configured desktop environment without local installation

??? note "What cloud providers does LabLink support?"
    **AWS (Amazon Web Services)** is the only cloud provider — the `aws` provider uses EC2, S3 and IAM.

    You can also skip the cloud entirely. The `manual` provider runs the allocator as a docker-compose stack and lets you register client machines you already own. See [Bring-Your-Own Clients](cli/byo-clients.md).

??? note "Is LabLink free?"
    LabLink itself is open-source and free. On the `aws` provider you pay for the AWS resources you use (EC2 instances, S3 storage, and so on) — see [Cost Estimation](cost-estimation.md). On the `manual` provider you're running on your own hardware, so there's no cloud bill at all.

## Installation & setup

??? note "Do I need an AWS account?"
    Only for the `aws` provider, which needs permissions to create EC2 instances, security groups and other resources.

    With `provider: manual` you need no AWS account, no OpenTofu and no `gh` — just Docker on the allocator host and on each client box. See [Prerequisites](prerequisites.md#pick-your-path-first).

??? note "Can I run LabLink without AWS?"
    Yes — that's the `manual` provider. The allocator runs as a docker-compose stack on a machine you already have, and you register your own client boxes with `lablink client register` rather than provisioning them.

    Only the `aws` provider *creates* machines for you, and that's the part that needs AWS.

??? note "How long does setup take?"
    - **Initial AWS setup**: 1-2 hours (first time)
    - **Local testing**: 5-10 minutes
    - **First deployment**: 10-15 minutes

## Configuration

??? note "How do I change the GPU type?"
    Edit the allocator configuration:

    ```yaml
    # lablink-infrastructure/config/config.yaml
    machine:
      machine_type: "g5.xlarge"  # Change to desired instance type
    ```

    See [Configuration → Machine Type Options](configuration.md#machine-type-options) for available types.

    Note this sets the **client VM** type. The allocator's own instance type is fixed at `t3.large` in OpenTofu and isn't a config key.

??? note "How do I use my own research software?"
    1. Create a Docker image with your software
    2. Push to a container registry (e.g. ghcr.io)
    3. Update configuration with your image URL
    4. Optionally specify your code repository

    See [Adapting LabLink](adapting.md) for the full guide.

??? note "Can I use a different AWS region?"
    Not today — `us-west-2` is the only supported region.

    AMI IDs are region-scoped, and both LabLink images (the client VM image and the
    allocator's own) exist only in `us-west-2`. Setting `app.region` to anything else
    is refused at plan time by a precondition in the deployment template, so it fails
    before creating anything rather than half-deploying.

    Supporting another region means copying both images into it with
    `aws ec2 copy-image`, pointing `machine.ami_id` at the client copy, and updating
    the allocator AMI in
    [lablink-template](https://github.com/talmolab/lablink-template). If you need a
    particular region, open an issue.

??? note "Can I use a custom AMI?"
    Yes. Create an AMI with your software pre-installed:

    ```bash
    aws ec2 create-image --instance-id i-xxxxx --name "my-custom-ami"
    ```

    Then point the config at it:

    ```yaml
    machine:
      ami_id: "ami-your-custom-ami-id"
    ```

    See [Adapting LabLink → Custom AMI](adapting.md#custom-ami).

??? note "How do I change default passwords?"
    **Critical for production.** Replace `PLACEHOLDER_ADMIN_PASSWORD` and `PLACEHOLDER_DB_PASSWORD` in your config before deploying. See [Security → Change Default Passwords](security.md#change-default-passwords) for all methods.

## SSL and access

??? note "Why does my browser say “Not Secure”?"
    You're deploying with `ssl.provider: "none"`, which serves HTTP only (no encryption). This is expected for testing.

    To get a secure HTTPS connection with a browser padlock, set `ssl.provider` to `letsencrypt`, `cloudflare`, or `acm` and redeploy.

    See [Configuration → SSL Options](configuration.md#ssltls-options-ssl).

??? note "Why can't I access the allocator in my browser?"
    If your browser cannot connect to `http://your-domain.com`:

    1. Make sure you explicitly type `http://` (not `https://`)
    2. Clear your browser's HSTS cache (see [Troubleshooting → Reaching the allocator](troubleshooting.md#reaching-the-allocator))
    3. Try incognito/private browsing mode
    4. Try accessing via IP address: `http://<allocator-ip>:5000`

??? note "Which SSL provider should I use?"
    **Use `ssl.provider: "none"` for:**

    - Initial testing and development
    - Frequent deployments (unlimited — no certificates are issued)
    - Testing infrastructure changes
    - CI/CD automated tests

    **Use `letsencrypt`, `cloudflare`, or `acm` for:**

    - Production deployments
    - Internet-accessible allocators
    - Handling sensitive data
    - Long-running deployments

    **Key difference:** `none` = HTTP only (fast, unlimited, no encryption). The others = HTTPS with trusted certificates. Only `letsencrypt` is rate limited.

    See [Configuration → SSL/TLS Options](configuration.md#ssltls-options-ssl).

??? note "How many times can I redeploy?"
    Unlimited with `ssl.provider: "none"` — no certificates are issued, so no rate limits.

    With `letsencrypt` you're limited to **5 duplicate certificates per domain per week**. Redeploying the same test hostname repeatedly will exhaust that quota and the allocator will serve a TLS error until it resets. Use a fresh hostname for throwaway deployments, or `none` while iterating.

    `cloudflare` and `acm` have no such limit.

??? note "Can I switch SSL providers later?"
    Yes. Change the configuration and redeploy:

    ```yaml
    ssl:
      provider: "letsencrypt"
      email: "you@example.com"  # required for Let's Encrypt
    ```

    Then run:

    ```bash
    tofu apply
    ```

    The allocator will obtain a trusted certificate and start serving HTTPS. You may need to clear your browser's HSTS cache.

## Deployment

??? note "What's the difference between dev, test, and prod environments?"
    | Environment | Purpose | Image Tags | OpenTofu State |
    |-------------|---------|------------|-----------------|
    | **dev** | Local development | `-test` | Local file |
    | **test** | Staging/pre-prod | `-test` | S3 bucket |
    | **prod** | Production | Pinned versions | S3 bucket |

    See [Deployment → Environment-Specific Configurations](deployment.md#environment-specific-configurations).

??? note "How do I deploy to production?"
    1. Navigate to the **Actions** tab in GitHub
    2. Select "Deploy LabLink Infrastructure" (`terraform-deploy.yml`)
    3. Click **Run workflow**
    4. Select the `prod` environment
    5. Enter a specific image tag (e.g. `v1.0.0`)
    6. Click **Run workflow**

    **Never use `:latest` in production.**

??? note "Can I deploy without GitHub Actions?"
    Yes — either `lablink deploy` from the CLI, or OpenTofu directly:

    ```bash
    cd lablink-infrastructure
    tofu init
    tofu apply -var="resource_suffix=prod" -var="allocator_image_tag=v1.0.0"
    ```

    See [Deployment → Method 2: Manual OpenTofu](deployment.md#method-2-manual-opentofu-deployment).

??? note "How do I update an existing deployment?"
    ```bash
    git pull
    tofu apply -var="resource_suffix=prod" -var="allocator_image_tag=v1.1.0"
    ```

    This replaces the EC2 instance with the new image.

## Operations

??? note "How do I create client VMs?"
    **Via the web UI**: log in to the allocator, go to **Admin → Create New VM Instance**, enter the number of VMs, and submit.

    **Via the API**:

    ```bash
    curl -X POST http://<allocator-ip>:5000/api/launch \
      -u admin:password \
      -d "instance_count=5"
    ```

??? note "How do I check VM status?"
    **Via the web UI**: **Admin → View Current Instances**.

    **Via the CLI**: `lablink status`.

    **Via the database**:

    ```bash
    ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>
    sudo docker exec <container-id> psql -U lablink -d lablink_db \
      -c "SELECT hostname, status, useremail FROM vms;"
    ```

??? note "How do I destroy a deployment?"
    **Via GitHub Actions** (template repo): Actions → "Destroy LabLink Infrastructure" (`terraform-destroy.yml`) → type `yes` to confirm and select the environment.

    **Via the CLI**: `lablink destroy`.

    **Via OpenTofu**:

    ```bash
    tofu destroy -var="resource_suffix=dev"
    ```

??? note "What happens if I destroy the allocator?"
    - The allocator EC2 instance is terminated
    - Database data is lost unless backed up
    - Client VMs keep running — destroy them separately, **first**

    Destroy client VMs before the allocator, or you'll be cleaning them up by hand from the EC2 console.

## Troubleshooting

??? note "PostgreSQL won't start after deployment"
    The container's `start.sh` starts Postgres and waits on `pg_isready` before Flask boots, so this normally means the cluster died rather than that it never started. Check, then restart it in place:

    ```bash
    sudo docker exec <container-id> pg_isready -U lablink
    sudo docker exec -it <container-id> pg_ctlcluster 17 main restart
    ```

    See [Troubleshooting → Inside the allocator](troubleshooting.md#inside-the-allocator).

??? note "I can't SSH into the instance"
    1. Key permissions: `chmod 600 ~/lablink-key.pem`
    2. Security group allows port 22
    3. Correct IP address
    4. Correct user — it's `ubuntu`

    See [Troubleshooting → SSH access](troubleshooting.md#ssh-access).

??? note "Client VMs aren't being created"
    1. AWS credentials resolve inside the allocator container
    2. Allocator container logs show the OpenTofu error
    3. The IAM role has EC2 permissions

    See [Troubleshooting → Client VMs](troubleshooting.md#client-vms-aws-provider).

??? note "I'm getting billed unexpectedly"
    - Check for running EC2 instances you forgot to terminate
    - Set up billing alerts (see [AWS Setup → Billing Alerts](aws-setup.md#step-8-billing-alerts))
    - Review the [Cost Estimation](cost-estimation.md) guide

## Costs

??? note "How much does LabLink cost to run?"
    **Always-on:**

    - Allocator (t3.large): $0.0832/hour (~$61/month if running 24/7)
    - S3 bucket: ~$0.05/month
    - Elastic IP: free while associated

    **Per client VM, while running:**

    - g4dn.xlarge: $0.526/hour

    See [Cost Estimation](cost-estimation.md) for a detailed breakdown and worked scenarios.

??? note "How can I reduce costs?"
    1. **Destroy VMs when not in use** — they're the dominant cost
    2. **Destroy the allocator between workshops** — it's the only always-on charge
    3. **Use Spot Instances** for client VMs (roughly 70% off on-demand)
    4. **Use smaller instance types** for testing
    5. **Set up billing alerts** to catch surprises early

??? note "Do I get charged for stopped instances?"
    - **EC2 instances**: no compute charges, but EBS storage charges continue
    - **Elastic IPs**: free while associated, $0.005/hour if unassociated

    **Best practice**: terminate rather than stop when you're done.

## Advanced

??? note "Can I use RDS instead of PostgreSQL in Docker?"
    No. PostgreSQL runs inside the allocator container with a fixed identity
    (database `lablink_db`, user `lablink`, `localhost:5432`) — only the
    password is configurable. The database is created fresh with each
    deployment and torn down with it, so an external managed database has
    nothing to persist.

??? note "Can I use LabLink with multiple AWS accounts?"
    Yes. Deploy separate instances with different AWS credentials or roles per account.

??? note "Can I add my own API endpoints?"
    Yes. Add a route in `packages/allocator/src/lablink_allocator_service/routes/`, then rebuild the image and redeploy:

    ```python
    @bp.route("/my-custom-endpoint", methods=["POST"])
    def my_custom_endpoint():
        return jsonify({"status": "success"})
    ```

    See [API Endpoints](api-endpoints.md) for the existing routes and their auth requirements.

## Security

??? note "Is it safe to use default passwords?"
    **No.** Change them immediately for any non-local deployment.

    See [Security → Change Default Passwords](security.md#change-default-passwords).

??? note "How are AWS credentials stored?"
    For GitHub Actions: **OIDC**, so nothing is stored.

    For local use: the AWS credentials file or environment variables.

    **Never commit credentials to version control.**

??? note "How are SSH keys managed?"
    - OpenTofu generates unique keys per environment
    - Keys are stored in OpenTofu state
    - GitHub Actions exposes keys as temporary artifacts (1 day expiration)
    - Rotate keys by destroying and recreating infrastructure

    See [Security & Access → SSH Key Management](security.md#ssh-key-management).

## Contributing

??? note "Can I contribute to LabLink?"
    Yes — LabLink is open-source and contributions are welcome. Fork the repository, create a feature branch, make your changes, add tests, and submit a pull request. See [Contributing](contributing.md).

??? note "How do I report bugs?"
    Open an issue on [GitHub](https://github.com/talmolab/lablink/issues) with the description, steps to reproduce, expected vs actual behaviour, logs or error messages, and your environment details.

??? note "Where can I ask questions?"
    - **GitHub Issues**: bugs and feature requests
    - **GitHub Discussions**: questions and general discussion

## Comparison

??? note "How is LabLink different from AWS Batch?"
    | Feature | LabLink | AWS Batch |
    |---------|---------|-----------|
    | Setup complexity | Moderate | High |
    | Custom software | Easy (Docker) | Easy (Docker) |
    | GPU support | Yes | Yes |
    | Cost | Pay for VMs | Pay for VMs + Batch overhead |
    | Web UI | Included | Requires building |
    | VM management | Automated | Automated |
    | Learning curve | Moderate | Steep |

    **LabLink advantage**: simpler setup, included web UI, research-focused.

??? note "How is LabLink different from Kubernetes?"
    LabLink is simpler and more focused:

    - **LabLink**: VM allocation for research workloads
    - **Kubernetes**: general-purpose container orchestration

    If you need simple VM management for research, use LabLink. If you need complex microservices orchestration, use Kubernetes.

## Still have questions?

Check the [documentation index](index.md), search [existing issues](https://github.com/talmolab/lablink/issues), then open a new one.
