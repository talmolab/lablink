# Validate Terraform Configurations

```bash
cd packages/allocator/src/lablink_allocator_service/terraform
mv backend.tf backend.tf.bak      # S3 backend needs AWS credentials
terraform init && terraform validate && terraform fmt -check
mv backend.tf.bak backend.tf
```

This validates the **client VM** Terraform only. Allocator infrastructure Terraform
lives in the separate `talmolab/lablink-template` repo — the CLI downloads it from
tagged releases, so changes there need a new tag plus a `TEMPLATE_VERSION` /
`TEMPLATE_SHA256` bump in `packages/cli/src/lablink_cli/__init__.py`.
