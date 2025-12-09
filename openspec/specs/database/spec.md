# Database Specification

## Purpose

Define the PostgreSQL database schema for VM state management, including tables, triggers, and state transitions.

## Requirements

### Requirement: VMs Table Schema
The database SHALL store VM information in a `vms` table with the following schema.

#### Scenario: Table structure
- **GIVEN** a PostgreSQL database
- **WHEN** the schema is initialized
- **THEN** the `vms` table exists with columns:
  - `id`: SERIAL PRIMARY KEY
  - `hostname`: VARCHAR(255) NOT NULL UNIQUE
  - `email`: VARCHAR(255) (nullable, assigned user)
  - `status`: VARCHAR(50) NOT NULL
  - `crd_command`: TEXT (nullable, command to run)
  - `created_at`: TIMESTAMP DEFAULT NOW()
  - `updated_at`: TIMESTAMP DEFAULT NOW()

### Requirement: VM State Machine
VMs SHALL transition through defined states based on their lifecycle.

#### Scenario: Initial state
- **GIVEN** a new VM registers via `/vm_startup`
- **WHEN** the VM is recorded in the database
- **THEN** the status is set to "available"

#### Scenario: Transition to in-use
- **GIVEN** a VM with status "available"
- **WHEN** research software starts running on the VM
- **THEN** the status transitions to "in-use"

#### Scenario: Transition back to available
- **GIVEN** a VM with status "in-use"
- **WHEN** research software stops running
- **THEN** the status transitions to "available"

#### Scenario: Transition to failed
- **GIVEN** a VM in any state
- **WHEN** health checks fail or an error occurs
- **THEN** the status transitions to "failed"

### Requirement: Real-time Update Notifications
The database SHALL notify the allocator of VM state changes for real-time updates.

#### Scenario: Notify on VM update
- **GIVEN** the `notify_vm_update` trigger is configured
- **WHEN** any row in the `vms` table is updated
- **THEN** a PostgreSQL NOTIFY is sent on the `vm_updates` channel
- **AND** the payload contains the updated VM information

### Requirement: Hostname Uniqueness
Each VM hostname SHALL be unique in the database.

#### Scenario: Prevent duplicate hostnames
- **GIVEN** a VM with hostname "vm-001" exists
- **WHEN** attempting to insert another VM with hostname "vm-001"
- **THEN** the database rejects the insert with a unique constraint violation

### Requirement: Timestamp Auto-Update
The `updated_at` timestamp SHALL automatically update when a VM record changes.

#### Scenario: Auto-update timestamp
- **GIVEN** a VM record exists
- **WHEN** the record is updated
- **THEN** the `updated_at` field is set to the current timestamp