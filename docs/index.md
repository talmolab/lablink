# LabLink

**Cloud-based virtual teaching lab accessible through Chrome browser.**

Deploy tutorial environments to AWS with pre-installed software—students only need a web browser to get started.

---

## Getting Started

=== "Prerequisites"

    :material-clipboard-check-outline: Set up your AWS account, credentials, and required tools before deployment.

    [:octicons-arrow-right-24: View requirements](prerequisites.md)

=== "Quickstart"

    :material-rocket-launch: Deploy LabLink to AWS in 15 minutes with our step-by-step guide.

    [:octicons-arrow-right-24: Get started](quickstart.md)

=== "Configuration"

    :material-cog: Customize your deployment with environment variables, instance types, and more.

    [:octicons-arrow-right-24: Configure](configuration.md)

## Components

<div class="grid cards" markdown>

- :material-server: **Allocator**

    ---

    Web service managing VM requests, user authentication, and database operations.

    [:octicons-arrow-right-24: Learn more](architecture.md)

- :material-desktop-tower: **Client VMs**

    ---

    EC2 instances running pre-installed tutorial software with GPU support and health monitoring.

    [:octicons-arrow-right-24: Learn more](adapting.md)

- :material-cloud-outline: **Infrastructure**

    ---

    Terraform templates for AWS deployment including VPC, security groups, and auto-scaling.

    [:octicons-arrow-right-24: AWS setup](aws-setup.md)

</div>

## Resources

- [:fontawesome-brands-github: GitHub](https://github.com/talmolab/lablink) - Source code, issues, and contributions
- [:material-file-document-multiple: Template](https://github.com/talmolab/lablink-template) - Ready-to-use deployment template
- [:material-help-circle: Support](https://github.com/talmolab/lablink/issues) - Report issues or request features
