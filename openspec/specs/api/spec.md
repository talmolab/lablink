# API Specification

## Purpose

Define the HTTP API endpoints provided by the allocator service for VM management, user requests, and client registration.

## Requirements

### Requirement: API Authentication
The allocator SHALL authenticate machine-to-machine API requests using a shared bearer token.

#### Scenario: Valid bearer token
- **GIVEN** a client VM with the correct API token
- **WHEN** the client sends a request with `Authorization: Bearer <token>` header
- **THEN** the request is processed normally

#### Scenario: Missing or invalid bearer token
- **GIVEN** a request without a valid bearer token
- **WHEN** the request is sent to a token-protected endpoint
- **THEN** HTTP 401 Unauthorized is returned

#### Scenario: Student-facing endpoint exemption
- **GIVEN** the `/api/request_vm` endpoint
- **WHEN** a user submits a VM request without a bearer token
- **THEN** the request is processed normally (no token required)

### Requirement: Home Page
The allocator SHALL provide a home page for users to request VMs.

#### Scenario: Access home page
- **GIVEN** the allocator is running
- **WHEN** a user accesses `GET /`
- **THEN** the home page is displayed with VM request form

### Requirement: VM Request Endpoint
The allocator SHALL provide an endpoint for users to request VM assignment.

#### Scenario: Request VM successfully
- **GIVEN** an available VM exists in the database
- **WHEN** a user submits `POST /request_vm` with form data:
  - `email`: User's email address
  - `crd_command`: Command to run on the VM
- **THEN** the response contains the assigned VM hostname and status

#### Scenario: No VMs available
- **GIVEN** no VMs are in "available" state
- **WHEN** a user submits `POST /request_vm`
- **THEN** the response indicates no VMs are available

### Requirement: Admin Dashboard
The allocator SHALL provide an authenticated admin dashboard for VM management.

#### Scenario: Access admin dashboard
- **GIVEN** valid admin credentials
- **WHEN** an admin accesses `GET /admin`
- **THEN** the admin dashboard is displayed with VM management options

#### Scenario: Unauthorized access
- **GIVEN** invalid or missing credentials
- **WHEN** a user accesses `GET /admin`
- **THEN** HTTP 401 Unauthorized is returned

### Requirement: VM Creation Endpoint
The allocator SHALL provide an endpoint to create new client VMs via Terraform.

#### Scenario: Create VMs
- **GIVEN** valid admin credentials
- **WHEN** an admin submits `POST /admin/create` with form data:
  - `instance_count`: Number of VMs to create
- **THEN** Terraform is invoked to create the specified number of EC2 instances
- **AND** the response confirms creation initiated

### Requirement: VM List Endpoint
The allocator SHALL provide an endpoint to view all VMs.

#### Scenario: List all VMs
- **GIVEN** valid admin credentials
- **WHEN** an admin accesses `GET /admin/instances`
- **THEN** a list of all VMs with their states is returned

### Requirement: VM Destruction Endpoint
The allocator SHALL provide an endpoint to destroy all client VMs.

#### Scenario: Destroy all VMs
- **GIVEN** valid admin credentials
- **WHEN** an admin submits `POST /admin/destroy`
- **THEN** Terraform is invoked to destroy all client VM instances
- **AND** the response confirms destruction initiated

### Requirement: VM Startup Registration
The allocator SHALL provide an endpoint for client VMs to register on startup.

#### Scenario: Client VM registers
- **GIVEN** a newly started client VM
- **WHEN** the client submits `POST /vm_startup` with form data:
  - `hostname`: The VM's hostname
- **THEN** the VM is recorded in the database as "available"
- **AND** the response confirms registration

### Requirement: Health Check Endpoint
The allocator SHALL provide endpoints for client VMs to report health status.

#### Scenario: GPU health check
- **GIVEN** a registered client VM
- **WHEN** the client submits health check data
- **THEN** the VM's health status is updated in the database

### Requirement: Status Update Endpoint
The allocator SHALL provide an endpoint for client VMs to update their in-use status.

#### Scenario: Update to in-use
- **GIVEN** a registered client VM running research software
- **WHEN** the client reports software is running
- **THEN** the VM status is updated to "in-use"

#### Scenario: Update to available
- **GIVEN** a client VM that was in-use
- **WHEN** the client reports software has stopped
- **THEN** the VM status is updated to "available"
