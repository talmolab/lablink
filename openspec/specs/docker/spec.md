# Docker Specification

## Purpose

Define the Docker image build strategy for allocator and client services, including development and production variants.

## Requirements

### Requirement: Dual Dockerfile Strategy
Each package SHALL have two Dockerfiles for different use cases.

#### Scenario: Development Dockerfile
- **GIVEN** a package with `Dockerfile.dev`
- **WHEN** building with `docker build -f Dockerfile.dev .`
- **THEN** the image:
  - Copies local source code into the image
  - Uses `uv sync --extra dev` with lockfile for reproducible builds
  - Includes dev dependencies (pytest, ruff, coverage)
  - Creates virtual environment with explicit path

#### Scenario: Production Dockerfile
- **GIVEN** a package with `Dockerfile`
- **WHEN** building with `docker build --build-arg PACKAGE_VERSION=x.x.x -f Dockerfile .`
- **THEN** the image:
  - Installs from PyPI using `uv pip install`
  - Uses specific pinned version from build argument
  - Excludes source code (smaller image)
  - Excludes dev dependencies

### Requirement: Explicit Virtual Environment Paths
Docker images SHALL use explicit venv paths to avoid path resolution issues.

#### Scenario: Allocator venv location
- **GIVEN** an allocator Docker image
- **WHEN** the container starts
- **THEN** the virtual environment is at `/app/.venv`
- **AND** Python is `/app/.venv/bin/python`

#### Scenario: Client venv location
- **GIVEN** a client Docker image
- **WHEN** the container starts
- **THEN** the virtual environment is at `/home/client/.venv`
- **AND** Python is `/home/client/.venv/bin/python`

### Requirement: Console Script Entry Points
Packages SHALL define console script entry points in `pyproject.toml`.

#### Scenario: Allocator entry points
- **GIVEN** an allocator package installation
- **WHEN** the package is installed
- **THEN** the following console scripts are available:
  - `lablink-allocator` - Runs the Flask application
  - `generate-init-sql` - Generates PostgreSQL init script

#### Scenario: Client entry points
- **GIVEN** a client package installation
- **WHEN** the package is installed
- **THEN** the following console scripts are available:
  - `subscribe` - Allocator subscription service
  - `check_gpu` - GPU health check
  - `update_inuse_status` - Status update service

### Requirement: Python Version Consistency
Docker images SHALL use consistent Python versions.

#### Scenario: Allocator Python version
- **GIVEN** an allocator Docker image
- **WHEN** checking Python version
- **THEN** Python 3.11 is used (from `ghcr.io/astral-sh/uv:python3.11` base)

#### Scenario: Client Python version
- **GIVEN** a client Docker image
- **WHEN** checking Python version
- **THEN** Python 3.11 is used

### Requirement: Start Script Activation
Docker containers SHALL use start scripts that activate the virtual environment.

#### Scenario: Venv activation
- **GIVEN** a Docker container with `start.sh`
- **WHEN** the container starts
- **THEN** the start script runs `source /path/to/.venv/bin/activate`
- **AND** subsequent commands use the activated venv

### Requirement: CUDA Support for Client
Client Docker images SHALL include NVIDIA CUDA for GPU workloads.

#### Scenario: CUDA availability
- **GIVEN** a client Docker image
- **WHEN** the container runs with `--gpus all`
- **THEN** CUDA 12.8.1 is available
- **AND** PyTorch can detect GPU devices