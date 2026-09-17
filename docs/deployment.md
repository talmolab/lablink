# Template Repository Deployment

The [template repository](https://github.com/talmolab/lablink-template) holds
the OpenTofu files and GitHub Actions workflows for an AWS deployment. Start
with [Quickstart: Template repo](quickstart-template.md) to create a repository,
run `scripts/setup.sh`, and prepare `lablink-infrastructure/config/config.yaml`.
For a standard deployment from your own machine, use the
[LabLink CLI](cli/first-deployment.md).

## Method 1: GitHub Actions

**Deploy LabLink Infrastructure** runs when you push to the `test` branch, or
when you start it from the Actions tab with a `deployment_name` and an
`environment` (`test`, `prod`, or `ci-test`). A push to `main` does not deploy.
For a `test` push, set the repository variable `DEPLOYMENT_NAME` to the name
you want; otherwise the workflow uses `my-lablink`.

The workflow uses the `AWS_ROLE_ARN`, `AWS_REGION`, `ADMIN_PASSWORD`, and
`DB_PASSWORD` repository secrets created by `scripts/setup.sh`. It pulls the
image named by `allocator.image_tag` and validates the config. In its working
copy, it replaces the password placeholders and sets `deployment_name` and
`environment` to the workflow inputs, then runs OpenTofu 1.12.5 against the
S3 backend. It verifies the deployment and uploads the allocator SSH key as
an artifact retained for one day. If apply fails, it runs `tofu destroy`.

See [the quickstart](quickstart-template.md#step-4-commit-and-deploy) for the
full workflow and verification steps. The workflow does not build images;
publish an image separately and select its tag in `config.yaml`.

## Method 2: Manual OpenTofu Deployment

Use this when you need to run the template's OpenTofu files locally. It still
uses the S3 state bucket and DynamoDB lock table created by `scripts/setup.sh`.
You need OpenTofu 1.10.0 or newer, AWS credentials, and a configured template
repository checkout. Run `./scripts/doctor.sh` first.

The template expects real credentials in the local
`lablink-infrastructure/config/config.yaml` for a direct apply. Replace
`PLACEHOLDER_ADMIN_PASSWORD` and `PLACEHOLDER_DB_PASSWORD` with strong values
in your private working copy, and restore the placeholders before committing
the file. Set top-level `deployment_name` and `environment` in that copy to
the same values you pass with `-var`; GitHub Actions performs those changes
automatically on its path.

From the repository root, initialize the backend for the environment:

```bash
./scripts/init-terraform.sh test
cd lablink-infrastructure
```

The init script reads `bucket_name` and `app.region` from `config.yaml` and
uses `backend-test.hcl`; use `dev`, `ci-test`, or `prod` in place of `test` when
appropriate. Run the plan and apply with the same deployment name and
environment:

```bash
tofu plan -var="deployment_name=my-lablink" -var="environment=test"
tofu apply -var="deployment_name=my-lablink" -var="environment=test"
```

The template's input variables are `region`, `deployment_name`,
`environment`, and `repository`. Image tags, client instance type, and Elastic
IP strategy come from `config.yaml` (`allocator.image_tag`, `machine`, and
`eip.strategy`); they are not `-var` arguments. The allocator instance type is
`t3.large` in the template. Its root volume uses the AMI default; client root
volumes are 80 GiB.

## Environment-Specific Configurations

`dev`, `test`, `ci-test`, and `prod` each use a separate S3 state key selected
by `scripts/init-terraform.sh`. The same `deployment_name` can be used across
environments, but pass the intended environment to both init and every
`tofu plan`, `apply`, or `destroy` command. OpenTofu tags resources with the
deployment name and environment.

The allocator's public address is available from the outputs:

```bash
tofu output -raw allocator_fqdn
tofu output -raw ec2_public_ip
```

For DNS and TLS choices, see [DNS Configuration](dns-configuration.md) and
[Configuration](configuration.md). The admin dashboard has a **Create New VM
Instance** button that opens **Launch New LabLink Instances**; choose a count
and click **Launch VMs**. Client VM provisioning runs asynchronously.

## Updating a Deployment

Update the config or OpenTofu files in your template checkout, reinitialize
the intended environment, and review the plan before applying it. With GitHub
Actions, commit the config and run **Deploy LabLink Infrastructure** again.
The workflow's `deployment_name` and `environment` must match the deployment
you intend to update.

## Destroying a Deployment

The safest template path is **Destroy LabLink Infrastructure** in the Actions
tab. Enter the original `deployment_name` and `environment` and set
`confirm_destroy` to `yes`. The workflow attempts to destroy client VMs from
their S3 state before destroying the allocator infrastructure.

For a local OpenTofu teardown, destroy the client VMs through the allocator
admin UI first. From the template repository root, initialize the same
backend and destroy the allocator:

```bash
./scripts/init-terraform.sh test
cd lablink-infrastructure
tofu destroy -var="deployment_name=my-lablink" -var="environment=test"
```

If a failed run leaves tagged resources behind, preview the template's
cleanup script before using it:

```bash
./scripts/cleanup-orphaned-resources.sh test --deployment-name my-lablink --dry-run
```

For deployment failures, see [Troubleshooting](troubleshooting.md).
