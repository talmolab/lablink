# Architecture

This page describes LabLink's architecture, components, and how they interact.

## System Overview

```mermaid
graph TB
    subgraph GitHub["GitHub"]
        SourceCode[Source Code<br/>Repository]
        Actions[GitHub Actions<br/>CI/CD]
        SourceCode --> Actions
    end

    subgraph Artifacts["Build Artifacts"]
        DockerImages[Docker Images<br/>ghcr.io]
        TerraformDeploy[Terraform Apply<br/>Infrastructure]
    end

    Actions --> DockerImages
    Actions --> TerraformDeploy

    subgraph AWS["AWS Cloud"]
        subgraph AllocatorInstance["Allocator EC2 Instance"]
            subgraph AllocatorContainer["Docker Container: lablink-allocator"]
                Flask[Flask App<br/>Port 80<br/><br/>• Web UI<br/>• API<br/>• Terraform]
                PostgreSQL[(PostgreSQL DB<br/>Port 5432<br/><br/>• VM table<br/>• Triggers<br/>• Listen/Notify)]
                Flask <--> PostgreSQL
            end
        end

        subgraph ClientInstances["Client EC2 Instances (Dynamic)"]
            subgraph ClientContainer["Docker Container: lablink-client"]
                Subscribe[Subscribe Service<br/><br/>• Heartbeat<br/>• GPU Check<br/>• Status]
                Research[Research Code<br/>User Repo<br/><br/>• SLEAP/Custom<br/>• Your Software]
                Subscribe --> Research
            end
            Note[Multiple instances,<br/>dynamically created]
        end

        subgraph AWSResources["AWS Resources"]
            SecurityGroups[Security Groups<br/>• Port 80<br/>• Port 22<br/>• Port 5432]
            ElasticIPs[Elastic IPs<br/>Static IPs]
            S3[S3 Bucket<br/>TF State]
        end
    end

    TerraformDeploy --> AllocatorInstance
    DockerImages -.-> AllocatorContainer
    DockerImages -.-> ClientContainer
    Flask -->|spawns via<br/>Terraform| ClientInstances
    Subscribe -.->|heartbeat,<br/>status updates| Flask

    style GitHub fill:#f0f0f0
    style Artifacts fill:#e1f5ff
    style AWS fill:#fff4e1
    style AllocatorInstance fill:#ffe6e6
    style AllocatorContainer fill:#fff
    style ClientInstances fill:#e6ffe6
    style ClientContainer fill:#fff
    style AWSResources fill:#f0f0f0
    style Flask fill:#4a90e2,color:#fff
    style PostgreSQL fill:#336791,color:#fff
    style Subscribe fill:#4a90e2,color:#fff
    style Research fill:#8bc34a,color:#fff
```

## Component Details

### Allocator Service

**Purpose**: Central management server for VM allocation and orchestration.

**Technology Stack**:

- **Flask**: Web application framework
- **PostgreSQL**: Relational database for VM state
- **SQLAlchemy**: ORM for database operations
- **Terraform**: Infrastructure provisioning
- **Docker**: Containerization

**Key Responsibilities**:

1. **Web Interface**:

   - Admin dashboard for VM management
   - VM creation interface
   - Instance listing and monitoring

2. **API Endpoints**:

   - `/request_vm`: Allocate VM to user
   - `/admin/create`: Create new VM instances
   - `/admin/instances`: List all instances
   - `/admin/destroy`: Destroy instances
   - `/vm_startup`: Client registration

3. **Database Management**:

   - Tracks VM states (available, in-use, failed)
   - PostgreSQL listen/notify for real-time updates
   - Automated triggers for state changes

4. **Infrastructure Orchestration**:
   - Spawns client VMs via Terraform
   - Manages AWS credentials
   - Handles security group configuration

**Configuration**: See `packages/allocator/src/lablink_allocator/conf/structured_config.py`

### Client Service

**Purpose**: Runs on dynamically created VMs to execute research workloads.

**Technology Stack**:

- **Python**: Service implementation
- **Docker**: Container runtime
- **Custom Software**: SLEAP or user-defined

**Key Responsibilities**:

1. **Health Monitoring**:

   - GPU health checks (every 20 seconds)
   - System resource monitoring
   - Reports status to allocator

2. **Allocator Communication**:

   - Heartbeat mechanism
   - Status updates (in-use, available)
   - Failure reporting

3. **Research Execution**:
   - Clones configured repository
   - Runs containerized research software
   - Executes user-defined CRD commands

**Configuration**: See `packages/client/src/lablink_client/conf/structured_config.py`

### Database Schema

**Table: `vms`**

| Column        | Type         | Description                         |
| ------------- | ------------ | ----------------------------------- |
| `id`          | SERIAL       | Primary key                         |
| `hostname`    | VARCHAR(255) | VM hostname/identifier              |
| `email`       | VARCHAR(255) | User email                          |
| `status`      | VARCHAR(50)  | VM status (available/in-use/failed) |
| `crd_command` | TEXT         | Command to execute on VM            |
| `created_at`  | TIMESTAMP    | Creation timestamp                  |
| `updated_at`  | TIMESTAMP    | Last update timestamp               |

**Triggers**:

- `notify_vm_update`: Sends PostgreSQL NOTIFY on row changes

### VM State Machine

The `status` field in the `vms` table follows this lifecycle:

```mermaid
stateDiagram-v2
    [*] --> available: VM Created<br/>(terraform apply)

    available --> in_use: Software process starts<br/>(detected by update_inuse_status)
    in_use --> available: Software process stops<br/>(task complete or crash)

    available --> failed: Startup failure<br/>(boot error)
    in_use --> failed: Health check failed<br/>(GPU error, system crash)

    failed --> available: Admin intervention<br/>(manual reset)
    failed --> [*]: VM Destroyed<br/>(terraform destroy)
    available --> [*]: VM Destroyed<br/>(terraform destroy)
    in_use --> [*]: Force destroy<br/>(admin action)

    note right of available
        VM ready, waiting
        Software not running
        Heartbeat active
    end note

    note right of in_use
        Configured software running
        User workload active
        Sending status updates
    end note

    note right of failed
        Requires attention
        Health checks failing
        Removed from pool
    end note
```

**State Transitions**:

- **available → in_use**: Configured software process starts running on the VM
- **in_use → available**: Software process stops (task complete or process ends)
- **available/in_use → failed**: Health checks fail or errors occur
- **failed → available**: Admin manually resets and fixes the VM
- **any → [*]**: VM is destroyed via Terraform

**Note**: The `in_use` status indicates whether the configured software (e.g., SLEAP) is actively running on the VM, not whether a user has been assigned the VM. This is monitored by the `update_inuse_status` service which checks for the configured process.

### Infrastructure Components

#### Security Groups

**Allocator Security Group**:

- Port 80 (HTTP): Web interface and API
- Port 22 (SSH): Administrative access
- Port 5432 (PostgreSQL): Database connections from clients

**Client Security Groups**:

- Port 22 (SSH): Administrative access
- Egress: Full internet access for package downloads

#### Networking

- **Elastic IPs**: Static IPs for allocators (one per environment)
- **VPC**: Default VPC or custom (configurable)
- **Route 53** (Optional): DNS management for friendly URLs

#### Storage

- **S3 Buckets**: Terraform state storage

  - Separate state per environment (dev/test/prod)
  - Versioning enabled
  - Encrypted at rest

- **EBS Volumes**: Instance root volumes
  - Allocator: 30GB (configurable)
  - Clients: Depends on AMI

## Data Flow

### VM Request Flow

```mermaid
sequenceDiagram
    actor User
    participant WebUI as Web UI/API
    participant Flask as Flask App
    participant DB as PostgreSQL
    participant Client as Client VM

    User->>WebUI: Submit VM request
    WebUI->>Flask: POST /request_vm
    Flask->>DB: SELECT * FROM vms<br/>WHERE status='available'<br/>LIMIT 1

    alt VM Available
        DB-->>Flask: Return VM details
        Flask-->>WebUI: Return VM hostname<br/>and connection details
        WebUI-->>User: Display VM info
        Flask->>DB: PostgreSQL NOTIFY<br/>vm_update
        DB-->>Client: Notify event
    else No VM Available
        DB-->>Flask: No results
        Flask-->>WebUI: Error: No VMs available
        WebUI-->>User: Queue request or<br/>show error message
    end

    Note over Client: Later: update_inuse_status service<br/>monitors for software process
    Client->>Client: Software process starts
    Client->>Flask: Update status to in-use
    Flask->>DB: UPDATE vms<br/>SET status='in-use'
```

### VM Creation Flow

```mermaid
sequenceDiagram
    actor Admin
    participant Flask as Flask App
    participant Terraform
    participant AWS as AWS EC2
    participant VM as Client VM Instance
    participant Docker as Docker Container

    Admin->>Flask: POST /admin/create<br/>(instance_count)
    Flask->>Terraform: Execute terraform apply<br/>(subprocess)

    Terraform->>AWS: Create security group
    Terraform->>AWS: Generate SSH key pair
    Terraform->>AWS: Launch EC2 instance<br/>with user_data script
    AWS-->>Terraform: Return instance details<br/>(hostname, IP, etc.)
    Terraform-->>Flask: Provisioning complete

    Note over VM: Boot sequence begins
    VM->>VM: Execute user_data script

    VM->>Docker: Pull Docker image<br/>from ghcr.io
    VM->>VM: Clone user repository<br/>(if configured)
    VM->>Docker: Start client service<br/>(subscribe, check_gpu, etc.)
    Docker->>Flask: POST /vm_startup<br/>(hostname registration)

    Flask-->>Admin: VMs created successfully<br/>(show instance details)
```

### Health Check Flow

```mermaid
sequenceDiagram
    participant Client as Client VM
    participant Flask as Flask App
    participant DB as PostgreSQL

    Note over Client: Every 20 seconds

    loop Health Check Cycle
        Client->>Client: Check GPU status
        Client->>Client: Check system resources

        alt GPU/System Healthy
            Client->>Flask: POST /health_check<br/>(status: healthy)
            Flask->>DB: Verify VM record
            Flask-->>Client: ACK
        else GPU/System Unhealthy
            Client->>Flask: POST /health_check<br/>(status: failed)
            Flask->>DB: UPDATE vms<br/>SET status='failed'
            Flask-->>Client: ACK
            Note over DB: VM marked as failed<br/>removed from available pool
        end
    end
```

## Deployment Environments

LabLink supports multiple isolated environments:

| Environment | Purpose           | Image Tag   | Terraform Backend  |
| ----------- | ----------------- | ----------- | ------------------ |
| `dev`       | Local development | `*-test`    | Local state        |
| `test`      | Staging/testing   | `*-test`    | `backend-test.hcl` |
| `prod`      | Production        | Pinned tags | `backend-prod.hcl` |

Each environment has:

- Separate Terraform state
- Unique resource naming (`-dev`, `-test`, `-prod` suffix)
- Independent AWS resources

## CI/CD Pipeline

See [Workflows](workflows.md) for detailed CI/CD architecture.

**Key Workflows**:

1. **Build Images** (`lablink-images.yml`):

   - Triggers on code changes
   - Builds allocator and client Docker images
   - Pushes to GitHub Container Registry

2. **Terraform Deploy** (`lablink-allocator-terraform.yml`):

   - Triggers on branch push or manual dispatch
   - Applies infrastructure changes
   - Supports environment selection

3. **Destroy** (`lablink-allocator-destroy.yml`):
   - Manual trigger only
   - Safely destroys environment resources

## Security Architecture

- **OIDC Authentication**: GitHub Actions authenticate to AWS without stored credentials
- **SSH Keys**: Auto-generated per environment, ephemeral artifacts
- **Secrets**: Managed via GitHub Secrets and AWS Secrets Manager
- **Network**: Security groups restrict access by port and source

See [Security](security.md) for detailed security considerations.

## Scalability Considerations

**Current Architecture**:

- Single allocator per environment
- Multiple clients per allocator
- Database handles concurrent requests

**Scaling Options**:

- Horizontal: Multiple allocators with load balancer
- Vertical: Larger instance types for allocator
- Database: RDS for managed PostgreSQL at scale

## Technology Choices

| Component     | Technology      | Rationale                          |
| ------------- | --------------- | ---------------------------------- |
| Web Framework | Flask           | Lightweight, Python ecosystem      |
| Database      | PostgreSQL      | LISTEN/NOTIFY, ACID compliance     |
| IaC           | Terraform       | Declarative, AWS support           |
| Containers    | Docker          | Portability, dependency isolation  |
| CI/CD         | GitHub Actions  | Native GitHub integration          |
| Config        | Hydra/OmegaConf | Structured configs, easy overrides |

## Next Steps

- **[Configuration](configuration.md)**: Customize components
- **[Deployment](deployment.md)**: Deploy the system
- **[Testing](testing.md)**: Test the codebase
