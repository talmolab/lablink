# Terraform in Lablink

## Overview
This directory contains the Terraform configuration files for the Lablink project. The Terraform configuration files are used to create the infrastructure for the Lablink project. The infrastructure creates the following resources:
 
- A database instance in Google Spanner for VM assignment.
- A Cloud Run service for the VM assignment.
- A service account for each resource in the VM assignment infrastructure.

## Prerequisites

Before you can use the Terraform configuration files, running Terraform commands, you need to install Terraform. You can install Terraform by following the instructions in the [Terraform documentation](https://learn.hashicorp.com/tutorials/terraform/install-cli).

Also, you need to have a Google Cloud Platform (GCP) account and a project in GCP. You can create a GCP account and a project in the [Google Cloud Platform Official Website](https://cloud.google.com/gcp).

## Configuration

The Terraform configuration files are located in the `terraform` directory. The configuration files are organized as follows:

- `main.tf`: The main Terraform configuration file that defines the resources to create.
- `variables.tf`: The Terraform variables file that defines the input variables for the Terraform configuration files.
- `outputs.tf`: The Terraform outputs file that defines the output variables for the Terraform configuration files.
- `provider.tf`: The Terraform provider file that defines the provider for the Terraform configuration files.

## Installation

To install the Terraform configuration files, clone the repository:

```bash
git clone https://github.com/talmolab/lablink.git
```

## Usage

After creating a GCP account and a project, you need to create a service account in GCP and download the service account key. You can create a service account linked to the Terraform configuration files by running the following command:

```bash
bash create_service_account.sh
```

This will create a service account in GCP and download the service account key to the `terraform` directory.

To use the Terraform configuration files, you need to run this command to initialize the Terraform configuration files:

```bash
cd terraform
terraform init
```

After initializing the Terraform configuration files, you can run the following command to check what the resources will be created:

```bash
terraform plan
```

To create the infrastructure, you can run the following command:
```bash
terraform apply
```

To destroy the infrastructure, you can run the following command:

```bash
terraform destroy
```
