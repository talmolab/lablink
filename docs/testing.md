# Testing

This guide covers testing LabLink components, including unit tests, integration tests, and end-to-end testing.

## Testing Overview

LabLink uses **pytest** for testing Python code. The testing strategy includes:

- **Unit tests**: Test individual functions and classes (mocked dependencies)
- **Integration tests**: Test component interactions
- **End-to-end tests**: Test full workflows from API to VM creation
- **Infrastructure tests**: Validate Terraform configurations

## Continuous Integration (CI)

### CI Pipeline

**Workflow**: `.github/workflows/ci.yml`

**Triggers**:
- Pull requests to `main`
- Pushes to `main` or development branches

**Steps**:
1. Setup Python environment
2. Install dependencies
3. Run linting (ruff)
4. Run unit tests with pytest
5. Generate coverage reports

**CI runs**:
- Allocator service tests
- Client service tests
- Mock tests only (no AWS resources)

### View CI Results

1. Navigate to **Actions** tab in GitHub
2. Click on CI workflow run
3. View test results and coverage

## Local Testing

### Prerequisites

- Python 3.9+
- `uv` package manager (recommended) or `pip`
- Allocator and client service code

### Setup Test Environment

#### Using uv (Recommended)

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Navigate to service directory
cd lablink-allocator/lablink-allocator-service

# Install dependencies including test deps
uv sync --extra dev

# Or for client
cd lablink-client-base/lablink-client-service
uv sync --extra dev
```

#### Using pip

```bash
cd lablink-allocator/lablink-allocator-service

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -e ".[dev]"
```

### Run Unit Tests

#### Allocator Service

```bash
cd lablink-allocator/lablink-allocator-service

# Run all tests
PYTHONPATH=. pytest

# Run with verbose output
PYTHONPATH=. pytest -v

# Run specific test file
PYTHONPATH=. pytest tests/test_api_calls.py

# Run specific test
PYTHONPATH=. pytest tests/test_api_calls.py::test_request_vm
```

#### Client Service

```bash
cd lablink-client-base/lablink-client-service

# Run all tests
PYTHONPATH=. pytest

# Run specific tests
PYTHONPATH=. pytest tests/test_check_gpu.py
PYTHONPATH=. pytest tests/test_subscribe.py
```

### Run with Coverage

```bash
# Generate coverage report
PYTHONPATH=. pytest --cov=lablink_allocator_service --cov-report=html

# View coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

### Run Linting

```bash
# Check code quality with ruff
ruff check .

# Auto-fix issues
ruff check --fix .

# Format code
ruff format .
```

## Test Structure

### Allocator Service Tests

Located in `lablink-allocator/lablink-allocator-service/tests/`:

| Test File | Purpose |
|-----------|---------|
| `test_api_calls.py` | Test Flask API endpoints |
| `test_admin_auth.py` | Test admin authentication |
| `test_pages.py` | Test web page rendering |
| `test_terraform_api.py` | Test Terraform integration |
| `utils/test_aws_utils.py` | Test AWS utility functions |
| `utils/test_terraform_utils.py` | Test Terraform utilities |
| `utils/test_scp.py` | Test SCP file transfer |

### Client Service Tests

Located in `lablink-client-base/lablink-client-service/tests/`:

| Test File | Purpose |
|-----------|---------|
| `test_check_gpu.py` | Test GPU health check |
| `test_subscribe.py` | Test allocator subscription |
| `test_update_inuse.py` | Test status updates |
| `test_connect_crd.py` | Test CRD command execution |
| `test_imports.py` | Test module imports |

### Terraform Tests

Located in `lablink-allocator/lablink-allocator-service/terraform/tests/`:

| Test File | Purpose |
|-----------|---------|
| `test_plan.py` | Test Terraform plan validation |

## Feature Testing

LabLink has two key features that require integration testing:

### Feature 1: Update In-Use Status

**Purpose**: Client VMs report their status to the allocator.

**Test Setup**:

1. Deploy LabLink allocator
2. Create client VMs via allocator
3. Verify VMs register with allocator
4. Check status updates in allocator database

**Manual Test**:

```bash
# Deploy allocator
cd lablink-allocator
terraform apply -var="resource_suffix=test"

# Get allocator IP
ALLOCATOR_IP=$(terraform output -raw ec2_public_ip)

# Create client VMs via web interface
open http://$ALLOCATOR_IP:80

# Check VM status
ssh -i ~/lablink-key.pem ubuntu@$ALLOCATOR_IP
sudo docker exec <container-id> psql -U lablink -d lablink_db -c "SELECT hostname, status, updated_at FROM vms;"

# Verify status changes over time
watch -n 5 'sudo docker exec <container-id> psql -U lablink -d lablink_db -c "SELECT hostname, status, updated_at FROM vms;"'
```

**Automated Test**:

See `.github/workflows/client-vm-infrastructure-test.yml`

### Feature 2: GPU Health Check

**Purpose**: Client VMs automatically check GPU health every 20 seconds and report to allocator.

**Test Setup**:

1. Create client VM with GPU instance type (e.g., `g4dn.xlarge`)
2. Monitor GPU health checks in client logs
3. Verify status updates in allocator

**Manual Test**:

```bash
# SSH into client VM
ssh -i ~/lablink-key.pem ubuntu@<client-vm-ip>

# Check GPU availability
nvidia-smi

# View client service logs
sudo docker logs -f <client-container-id>

# Look for GPU health check messages:
# "GPU health: OK" or "GPU health: FAILED"

# Check allocator database
ssh -i ~/lablink-key.pem ubuntu@$ALLOCATOR_IP
sudo docker exec <container-id> psql -U lablink -d lablink_db -c "SELECT hostname, status FROM vms WHERE hostname='<client-hostname>';"
```

**Expected Behavior**:

- Client checks GPU every 20 seconds
- If GPU fails, status changes to "failed"
- Allocator UI shows failed status

## End-to-End Testing

### Full Workflow Test

Test complete VM allocation workflow:

```bash
# 1. Deploy allocator
cd lablink-allocator
terraform apply -var="resource_suffix=e2e-test"
ALLOCATOR_IP=$(terraform output -raw ec2_public_ip)

# 2. Request VM via API
curl -X POST http://$ALLOCATOR_IP:80/request_vm \
  -d "email=test@example.com" \
  -d "crd_command=echo 'test'"

# 3. Verify VM assigned
ssh -i ~/lablink-key.pem ubuntu@$ALLOCATOR_IP \
  'sudo docker exec $(sudo docker ps -q) psql -U lablink -d lablink_db -c "SELECT * FROM vms WHERE email=\"test@example.com\";"'

# 4. Create client VMs
curl -X POST http://$ALLOCATOR_IP:80/admin/create \
  -u admin:IwanttoSLEAP \
  -d "instance_count=2"

# 5. Wait for VMs to be created
sleep 300

# 6. Verify VMs exist
aws ec2 describe-instances --filters "Name=tag:CreatedBy,Values=LabLink" \
  --query 'Reservations[*].Instances[*].[InstanceId,State.Name,PublicIpAddress]' \
  --output table

# 7. Check VMs registered with allocator
ssh -i ~/lablink-key.pem ubuntu@$ALLOCATOR_IP \
  'sudo docker exec $(sudo docker ps -q) psql -U lablink -d lablink_db -c "SELECT hostname, status FROM vms;"'

# 8. Cleanup
terraform destroy -var="resource_suffix=e2e-test" -auto-approve
```

### Infrastructure Test (CI)

**Workflow**: `.github/workflows/client-vm-infrastructure-test.yml`

This workflow performs end-to-end testing of client VM creation:

1. Deploys allocator to test environment
2. Triggers client VM creation
3. Waits for VM to become ready
4. Verifies VM registration
5. Checks health status
6. Cleans up resources

**Run Manually**:

1. Navigate to **Actions** tab
2. Select "Client VM Infrastructure Test"
3. Click "Run workflow"
4. Monitor progress

## Mocking for Tests

### Mock AWS Services

Use `moto` for mocking AWS:

```python
import boto3
from moto import mock_ec2, mock_s3

@mock_ec2
def test_create_instance():
    ec2 = boto3.client('ec2', region_name='us-west-2')

    # This creates a mock instance
    response = ec2.run_instances(ImageId='ami-12345', MinCount=1, MaxCount=1)

    assert len(response['Instances']) == 1
```

### Mock Database

Use `pytest` fixtures for database mocking:

```python
import pytest
from unittest.mock import MagicMock

@pytest.fixture
def mock_db():
    """Mock database connection."""
    db = MagicMock()
    db.execute.return_value = [{'hostname': 'i-12345', 'status': 'available'}]
    return db

def test_get_available_vm(mock_db):
    result = get_available_vm(mock_db)
    assert result['hostname'] == 'i-12345'
```

### Mock External APIs

Mock HTTP requests with `responses`:

```python
import responses
import requests

@responses.activate
def test_allocator_api():
    responses.add(
        responses.POST,
        'http://allocator:80/request_vm',
        json={'hostname': 'i-12345', 'status': 'assigned'},
        status=200
    )

    resp = requests.post('http://allocator:80/request_vm', data={'email': 'test@example.com'})
    assert resp.json()['hostname'] == 'i-12345'
```

## Performance Testing

### Load Testing

Test allocator under load with `locust`:

**`locustfile.py`**:
```python
from locust import HttpUser, task, between

class LablinkUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def request_vm(self):
        self.client.post("/request_vm", data={
            "email": "load-test@example.com",
            "crd_command": "echo test"
        })

    @task(2)
    def view_instances(self):
        self.client.get("/admin/instances", auth=('admin', 'IwanttoSLEAP'))
```

**Run load test**:
```bash
pip install locust
locust -f locustfile.py --host http://<allocator-ip>:80
```

Open [http://localhost:8089](http://localhost:8089) to configure and start load test.

## Test Best Practices

1. **Run tests before committing**:
   ```bash
   pytest && git commit
   ```

2. **Write tests for new features**:
   - Add test file in `tests/`
   - Test happy path and error cases
   - Use mocks to avoid external dependencies

3. **Keep tests fast**:
   - Use mocks for external services
   - Avoid time.sleep() when possible
   - Run integration tests separately

4. **Use descriptive test names**:
   ```python
   def test_request_vm_returns_available_vm():
       ...

   def test_request_vm_returns_error_when_no_vms_available():
       ...
   ```

5. **Test edge cases**:
   - Empty inputs
   - Invalid credentials
   - Network failures
   - Resource exhaustion

## Troubleshooting Tests

### Tests Fail Locally But Pass in CI

**Possible causes**:
- Different Python versions
- Missing dependencies
- Environment variables not set

**Solution**:
```bash
# Match CI Python version
uv python install 3.11

# Use same dependencies as CI
uv sync

# Set required environment variables
export DB_PASSWORD=test
export ADMIN_PASSWORD=test
```

### Import Errors

**Error**: `ModuleNotFoundError: No module named 'lablink_allocator_service'`

**Solution**:
```bash
# Set PYTHONPATH
export PYTHONPATH=.
pytest

# Or install package in editable mode
pip install -e .
pytest
```

### Database Connection Errors

**Error**: `psycopg2.OperationalError: could not connect to server`

**Solution**:
- Tests should use mocked database
- Check for hardcoded connection strings
- Use fixtures for database access

## Next Steps

- **[CI/CD Workflows](workflows.md)**: Understand automated testing
- **[Troubleshooting](troubleshooting.md)**: Debug test failures
- **[Contributing](https://github.com/talmolab/lablink/blob/main/CONTRIBUTING.md)**: Add new tests

## Quick Reference

```bash
# Run all tests
PYTHONPATH=. pytest

# Run with coverage
PYTHONPATH=. pytest --cov

# Run specific test
PYTHONPATH=. pytest tests/test_api_calls.py::test_request_vm

# Run linting
ruff check .

# Format code
ruff format .

# Watch for changes and re-run tests
PYTHONPATH=. pytest-watch
```