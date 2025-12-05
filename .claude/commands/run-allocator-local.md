# Run Allocator Locally

Run the allocator Flask application locally for development and testing.

## Quick Start

```bash
cd packages/allocator
PYTHONPATH=. uv run lablink-allocator
```

Opens allocator web interface at http://localhost:5000

## With Environment Variables

```bash
cd packages/allocator

# Set Flask environment
export FLASK_ENV=development  # Unix/Mac
set FLASK_ENV=development     # Windows CMD
$env:FLASK_ENV="development"  # Windows PowerShell

# Run allocator
PYTHONPATH=. uv run lablink-allocator
```

## Development Mode (Auto-Reload)

```bash
cd packages/allocator

# Enable auto-reload on code changes
export FLASK_ENV=development
export FLASK_DEBUG=1

# Run with flask command
PYTHONPATH=. uv run flask --app src/lablink_allocator/main.py run --debug
```

Flask will automatically reload when you edit Python files.

## Custom Port

```bash
cd packages/allocator

# Run on different port
PYTHONPATH=. uv run flask --app src/lablink_allocator/main.py run --port 8080
```

## With Docker PostgreSQL

For full local testing with database:

```bash
# 1. Start PostgreSQL container
docker run -d \
  --name lablink-postgres \
  -e POSTGRES_DB=lablink \
  -e POSTGRES_USER=lablink \
  -e POSTGRES_PASSWORD=lablink \
  -p 5432:5432 \
  postgres:13

# 2. Initialize database schema
cd packages/allocator
PYTHONPATH=. uv run generate-init-sql > /tmp/init.sql
docker exec -i lablink-postgres psql -U lablink -d lablink < /tmp/init.sql

# 3. Run allocator
PYTHONPATH=. uv run lablink-allocator
```

## Configuration

### Default Configuration

Allocator uses bundled config at `packages/allocator/src/lablink_allocator/conf/config.yaml`:

```yaml
db:
  host: localhost
  port: 5432
  dbname: lablink
  user: lablink
  password: lablink

app:
  admin_password: IwanttoSLEAP
  region: us-east-1

machine:
  instance_type: t3.micro
  ami_id: ami-0c55b159cbfafe1f0
  docker_image: lablink-client:latest
  docker_repo: ghcr.io/talmolab

bucket_name: lablink-terraform-state
```

### Custom Configuration

```bash
# Create custom config
cat > /tmp/dev-config.yaml << 'EOF'
db:
  host: localhost
  port: 5432
  dbname: lablink_dev
  user: dev_user
  password: dev_password

app:
  admin_password: dev_admin
  region: us-west-2

machine:
  instance_type: t3.small
  ami_id: ami-12345
  docker_image: lablink-client:dev
  docker_repo: local

bucket_name: dev-bucket
EOF

# Use custom config
CONFIG_DIR=/tmp CONFIG_NAME=dev-config PYTHONPATH=. uv run lablink-allocator
```

## Access Allocator

### Home Page
http://localhost:5000

### Admin Panel
http://localhost:5000/admin
- **Username**: admin
- **Password**: IwanttoSLEAP (default, change in config)

### API Endpoints

```bash
# Request VM (POST)
curl -X POST http://localhost:5000/request_vm \
  -d "email=user@example.com" \
  -d "crd_command=docker run my-image"

# VM startup notification (POST)
curl -X POST http://localhost:5000/vm_startup \
  -d "hostname=test-vm-001"

# Admin endpoints require authentication
curl -u admin:IwanttoSLEAP http://localhost:5000/admin/instances
```

## Troubleshooting

### Database Connection Error
**Symptom**: `psycopg2.OperationalError: could not connect to server`

**Solutions**:
1. Start PostgreSQL: `docker run ... postgres:13`
2. Verify connection: `docker exec lablink-postgres psql -U lablink -c "SELECT 1"`
3. Check config matches container settings

### Port Already in Use
**Symptom**: `OSError: [Errno 48] Address already in use`

**Solutions**:
```bash
# Use different port
PYTHONPATH=. uv run flask --app src/lablink_allocator/main.py run --port 8080

# Or kill process using port 5000
# Unix/Mac:
lsof -ti:5000 | xargs kill -9
# Windows PowerShell:
Get-Process -Id (Get-NetTCPConnection -LocalPort 5000).OwningProcess | Stop-Process
```

### Import Errors
**Symptom**: `ModuleNotFoundError: No module named 'lablink_allocator'`

**Solutions**:
```bash
# Ensure PYTHONPATH is set
export PYTHONPATH=.  # Unix/Mac
set PYTHONPATH=.     # Windows CMD
$env:PYTHONPATH="."  # Windows PowerShell

# Verify you're in correct directory
pwd  # Should be packages/allocator
```

### Terraform Operations Fail
**Symptom**: Errors when creating/destroying VMs

**Note**: Local allocator can't actually create AWS resources without:
1. AWS credentials configured
2. S3 bucket for Terraform state
3. Proper IAM permissions

For full infrastructure testing, use test environment or manual Terraform.

## Development Workflow

### 1. Make Code Changes

Edit files in `packages/allocator/src/lablink_allocator/`

### 2. Test Changes

```bash
# Run tests
PYTHONPATH=. pytest

# Run specific test
PYTHONPATH=. pytest tests/test_api_calls.py
```

### 3. Run Locally

```bash
# With auto-reload
export FLASK_ENV=development
export FLASK_DEBUG=1
PYTHONPATH=. uv run flask --app src/lablink_allocator/main.py run --debug
```

### 4. Test in Browser

Open http://localhost:5000 and test:
- Home page loads
- VM request form works
- Admin panel accessible
- API endpoints respond correctly

### 5. Check Logs

Watch terminal output for:
- Request logs
- Error messages
- Database queries
- Terraform operations

## Hot Reload Example

With debug mode enabled, Flask auto-reloads when you save files:

```bash
# Start with debug mode
export FLASK_ENV=development
export FLASK_DEBUG=1
PYTHONPATH=. uv run flask --app src/lablink_allocator/main.py run --debug

# Edit src/lablink_allocator/main.py
# Save the file
# Flask automatically reloads
# Refresh browser to see changes
```

## Related Commands

- `/test-allocator` - Run allocator unit tests
- `/docker-build-allocator` - Build allocator Docker image
- `/dev-setup` - Set up development environment