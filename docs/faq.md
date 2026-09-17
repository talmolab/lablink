# Frequently Asked Questions

Use [Troubleshooting](troubleshooting.md) for a failing deployment and
`lablink doctor` to check CLI prerequisites.

## Deployment

??? note "Do I need AWS?"
    Only for `provider: aws`. With `provider: manual`, the allocator runs in
    Docker on a machine you control and you register client boxes yourself.
    See [Bring-Your-Own Clients](cli/byo-clients.md).

??? note "Can I deploy without GitHub Actions?"
    Yes. The recommended AWS path is `lablink configure` followed by
    `lablink deploy`. If you own a template repository, you can also run its
    OpenTofu files locally with the current `deployment_name` and
    `environment` inputs; see
    [Manual OpenTofu Deployment](deployment.md#method-2-manual-opentofu-deployment).

??? note "What triggers a template-repository deployment?"
    **Deploy LabLink Infrastructure** runs for a push to `test`, manual
    dispatch with `deployment_name` and `environment`, or its configured
    repository dispatch. A push to `main` alone does not deploy. The workflow
    reads `allocator.image_tag` from `config.yaml`; it has no image-tag input.
    See [Template Repository Deployment](deployment.md#method-1-github-actions).

??? note "Can I use another AWS region?"
    Yes. The allocator AMI resolves per region. Set `app.region` and either
    leave `machine.ami_id` empty to resolve the default Deep Learning Base
    client AMI in that region, or provide a compatible AMI ID. `lablink doctor`
    checks that the selected image exists there. See
    [Configuration](configuration.md#ami-id).

??? note "Can I use my own image or software?"
    Yes. `machine.image` selects the client Docker image and
    `machine.ami_id` selects its AWS AMI on either AWS deployment path. The
    client AMI must have Docker, an NVIDIA driver, and the NVIDIA container
    runtime for GPU workloads. See [Adapting LabLink](adapting.md).

## Access and security

??? note "How do I set passwords?"
    The CLI prompts or uses saved values according to provider. A template
    repository keeps password placeholders in the committed config and
    replaces them from GitHub secrets during its workflow. See
    [Change Default Passwords](security.md#change-default-passwords).

??? note "Why does the browser show 'Not Secure'?"
    `ssl.provider: none` serves HTTP. Choose an HTTPS mode in
    [Configuration](configuration.md#ssl-providers) before public use. An
    HTTP viewer also loses H.264 streaming and falls back to JPEG/WebP.

??? note "Can I change SSL mode later?"
    Yes. Change `ssl.provider` and its required DNS or certificate settings,
    then redeploy through the same path. Use `lablink deploy` for the CLI or
    **Deploy LabLink Infrastructure** for a template repository. See
    [DNS Configuration](dns-configuration.md).

??? note "Are allocator and client SSH keys the same?"
    No. The deployment state holds the allocator key. The allocator's own
    OpenTofu workspace generates the client-VM keypair; its output is
    `lablink_private_key_pem`. See [SSH Access](security.md#ssh-access).

## Operations

??? note "How do I create client VMs?"
    Use **Create New VM Instance** in the admin dashboard or
    `lablink client launch --num-vms N`. The allocator's `POST /api/launch`
    takes `num_vms`, returns `202` with a `job_id`, and exposes progress at
    `/api/operations`. See [Workshop Guide](workshop-guide.md).

??? note "What happens when I destroy the allocator?"
    `lablink destroy` on AWS destroys the client fleet as part of the CLI
    workflow. The template's **Destroy LabLink Infrastructure** workflow
    attempts client-VM teardown from S3 state before removing the allocator.
    Use the same deployment name and environment used for apply. See
    [Destroying a Deployment](deployment.md#destroying-a-deployment).

??? note "Do stopped instances or Elastic IPs cost money?"
    A stopped EC2 instance stops its compute usage charge, while attached EBS
    storage still accrues charges. AWS bills public IPv4 addresses whether
    associated or idle. See [Cost Estimation](cost-estimation.md).

## Help

??? note "Where can I report a bug or ask a question?"
    Search [GitHub Issues](https://github.com/talmolab/lablink/issues), then
    open a new issue with the commands you ran, the result, relevant logs,
    and your environment. The repository does not have Discussions enabled.
