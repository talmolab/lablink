# LabLink Allocator
Lablink has folowing componenets:
- Dockerfile - This is the docker file for creating the lablink-allocator 
            -- It installs postgre sql
            -- Installs terraform (Used for VM creation)
            -- Runs generate-init-sql.py file which generates init.sql, which used set up db, user and trigger
            -- Installs required packages from requirements.txt
            -- Runs start.sh script

- start.sh - This file is the startup script for lablink-allocator image
           -- It runs init.sql
           -- It run main.py which intiliazes flask app


- main.tf (in root directory) - For allocator-image EC2 server creation
         -- Creates a security group for EC2, exposing ports 5000(flask port), 22(SSH port)
         -- Creates ec2 instance, with allocator test image 

- generate-init-sql.py  - This file contains python script to generate init.sql file, after importing config.

- lablink-allocator service:

  -> pg_hba.conf - Defines a custom pg_hba.conf file for postgre
                -- It replaces the existing pg_hba.conf file in one of the steps in the docker file.
                -- Added the following configuration: host    all             all             0.0.0.0/0            md5
                -- Hence we needed a custom conf file
                -- This configuration was required to be added, in order to make the postgre sql server remotely accessible

   -> terraform/main.tf - This file is for creating VM instances
         -- Creates a security group for EC2
         -- Creates 'instance_count' number of EC2 instances
        
   -> main.py - This file contains flask app routes. It manages creation of VMs, assigning VMs, and displaying list of existing VMs
        -- /request_vm - Its a POST method. Takes in email and CRD command as input. Queries vms table, and assigns the first avaible vm.
        -- /admin/create - Renders create vm instances page
        -- /admin - Renders admin page with two options, create instances or view instances
        -- /admin/instances - Renders view instances, containing a table of existing instances
        -- /launch - called from /create page. Using subprocess and terraform creates VM instances. Takes instance_count as input. this runs the 'terraform/main.tf' file.
        -- /admin/set-aws-credentials - Sets the AWS credentials for terraform to use. It takes in the access key and secret key as input. It creates a file called 'aws_credentials' in the terraform directory, which is used by terraform to create instances.
         -- /admin/instances - Displays the existing vms in a table
         -- /admin/destroy - Destroys the existing instances. It runs the 'terraform destroy' command using subprocess. It also deletes the security group created by terraform.
         -- /vm_startup - This is a POST method that takes in hostname as input. It listens for the message of database changeto be received from the database.
      -> Configurations in the structured_config.py file:
        - `db.dbname`: The name of the database to connect to.
        - `db.user`: The username for the database connection.
        - `db.password`: The password for the database connection.
        - `db.host`: The host address of the database.
        - `db.port`: The port number for the database connection.
        - `db.table_name`: The name of the table to query for VM assignments.
        - `machine.machine_type`: The type of machine to be used for the client's VM.
          - Default: `g4dn.xlarge` with NVIDIA T4 GPU.
        - `machine.ami_id`: The Amazon Machine Image (AMI) ID to be used for the client's VM instances.
          - Default: `ami-067cc81f948e50e06` (ubuntu 20.04 with Docker installed).
        - `machine.image`: The Docker image ID to be used for the client's VM instances.
          - Default: `ghcr.io/talmolab/lablink-client-base-image:latest` (latest version of LabLink client base image).
        - `machine.repository` (Optional): GitHub repository URL for the client's VM instances to clone.
   -> templates/index.html - Takes email and crd command as input and submits to /request_vm

   -> templates/create-instances.html - Takes in no of instances count and submits to /launch

   -> templates/instances.html - Displays the existing vms in a table 


Current issues/workarounds:
  - terraform/main.tf - We have currently tested this locally, that is by giving the AWS credentials from access keys in AWS(in main.tf file).
  - When creating both allocator instance or VM instance, we can't modify the same instance the next time from terraform. We need to delete the EC2 instances first. Once they are sucessfully deleted, we need to delete the security group, associated with instances.
  - allocator EC2 creation - Once allocator EC2 is created, in order to allow client access postgre sql, Right now it is requiring us to manually restart the server every time. Tried multiple ways, but oculdn't debug and achieve it through code
       Following are the steps to restart the postgre server:
         - ssh -i "sleap-lablink.pem" ubuntu@00.00.00.01 (Replace with the EC2 public IP)
         - sudo docker ps
         - sudo docker exec -it <docker name> bash
         - /etc/init.d/postgresql restart
  - 

## Description
This folder contains the Dockerfile and configuration files for the LabLink Allocator service. The LabLink Allocator is responsible for managing VM assignments and database interactions for the LabLink infrastructure. It includes a Flask-based web application and a PostgreSQL database.

The allocator service is designed to run on a Linux system and can be deployed using Docker. It provides endpoints for VM assignment and includes a web interface for submitting VM details.

- The repository has CI set up in `.github/workflows` for building and pushing the image when making changes.
  - The workflow uses the `linux/amd64` platform to build.
- The service can be deployed locally or on a cloud platform using Terraform configurations provided in the `terraform` directory.

## Installation

**Make sure to have Docker Daemon running first**

You can pull the image if you don't have it built locally, or need to update the latest, with:

```bash
docker pull ghcr.io/talmolab/lablink-allocator-image:latest
```

## Usage
To run the LabLink Allocator service locally, use the following command:

```bash
docker run -d -p 5000:5000 ghcr.io/talmolab/lablink-allocator-image:latest
```

This will expose the Flask application on port `5000`.

### Endpoints
- **Home Page**: Accessible at `http://localhost:5000/`. Displays a form for submitting VM details.
- **VM Request Endpoint**: Submit VM details via a POST request to `/request_vm`.

### Example Usage
To assign a VM, you can use the form on the home page or send a POST request with the required fields:

```bash
curl -X POST http://localhost:5000/request_vm \
  -d "email=user@example.com" \
  -d "crd_command=example_command"
```

## Deployment with Terraform
The LabLink Allocator can be deployed to AWS using the Terraform configuration provided in the `terraform` directory. Follow these steps:

1. Navigate to the `terraform` directory:
   ```bash
   cd terraform
   ```

2. Initialize Terraform:
   ```bash
   terraform init
   ```

3. Plan the deployment:
   ```bash
   terraform plan
   ```

4. Apply the deployment:
   ```bash
   terraform apply
   ```

This will create an EC2 instance running the LabLink Allocator service.

## Build
To build and push via automated CI, just push changes to a branch.

- Pushes to `main` result in an image with the tag `latest`.
- Pushes to other branches have tags with `-test` appended.
- See `.github/workflows` for testing and production workflows.

To test `test` images locally after pushing via CI:

```bash
docker pull ghcr.io/talmolab/lablink-allocator-image:linux-amd64-test
```

Then:

```bash
docker run -d -p 5000:5000 ghcr.io/talmolab/lablink-allocator-image:linux-amd64-test
```

To build locally for testing, use the command:

```bash
docker build --no-cache -t lablink-allocator -f .\lablink-allocator\Dockerfile .
docker run -d -p 5000:5000 --name lablink-allocator lablink-allocator
```