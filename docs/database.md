# Database Management

This guide covers the PostgreSQL database used by LabLink, including schema, management tasks, and troubleshooting.

## Database Overview

LabLink uses **PostgreSQL** for:

- Tracking VM states (available, in-use, failed)
- Storing user assignments
- Real-time notifications (LISTEN/NOTIFY)
- Audit logging

**Version**: PostgreSQL 13+
**Location**: Runs in allocator Docker container
**Access**: Port 5432 (internal)

## Database Schema

### Tables

#### `vms` Table

Primary table tracking all VM instances.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | Unique VM identifier |
| `hostname` | VARCHAR(255) | NOT NULL, UNIQUE | VM hostname/instance ID |
| `email` | VARCHAR(255) | | User email address |
| `status` | VARCHAR(50) | NOT NULL | VM status (available/in-use/failed) |
| `crd_command` | TEXT | | Command to execute on VM |
| `created_at` | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMP | DEFAULT NOW() | Last update timestamp |

**Status Values**:
- `available`: VM ready for assignment
- `in-use`: VM currently assigned to user
- `failed`: VM encountered error

**Example Row**:
```sql
id  | hostname          | email            | status    | crd_command      | created_at          | updated_at
----+-------------------+------------------+-----------+------------------+---------------------+---------------------
1   | i-0abc123def456   | user@example.com | in-use    | python train.py  | 2025-01-15 10:30:00 | 2025-01-15 10:35:00
```

### Triggers

#### `notify_vm_update`

Sends PostgreSQL NOTIFY when VM table changes.

**Purpose**: Real-time updates to client VMs

**Definition**:
```sql
CREATE OR REPLACE FUNCTION notify_vm_changes()
RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('vm_updates', row_to_json(NEW)::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER vm_update_trigger
AFTER INSERT OR UPDATE ON vms
FOR EACH ROW
EXECUTE FUNCTION notify_vm_changes();
```

**How it works**:
1. Row inserted/updated in `vms` table
2. Trigger fires
3. JSON payload sent to `vm_updates` channel
4. Listening clients receive notification
5. Clients query for their specific assignment

## Accessing the Database

### Via SSH and psql

```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>

# Get container ID
CONTAINER_ID=$(sudo docker ps --filter "ancestor=ghcr.io/talmolab/lablink-allocator-image" --format "{{.ID}}")

# Access PostgreSQL
sudo docker exec -it $CONTAINER_ID psql -U lablink -d lablink_db
```

### Connection Parameters

From config (`lablink-allocator/lablink-allocator-service/conf/config.yaml`):

```yaml
db:
  dbname: "lablink_db"
  user: "lablink"
  password: "lablink"  # Change in production!
  host: "localhost"
  port: 5432
```

### From Python (Inside Container)

```python
import psycopg2

conn = psycopg2.connect(
    dbname="lablink_db",
    user="lablink",
    password="lablink",
    host="localhost",
    port=5432
)

cursor = conn.cursor()
cursor.execute("SELECT * FROM vms;")
rows = cursor.fetchall()

for row in rows:
    print(row)

conn.close()
```

## Common Database Operations

### View All VMs

```sql
SELECT * FROM vms;
```

### View Available VMs

```sql
SELECT hostname, status, created_at
FROM vms
WHERE status = 'available'
ORDER BY created_at;
```

### View In-Use VMs

```sql
SELECT hostname, email, status, crd_command, updated_at
FROM vms
WHERE status = 'in-use'
ORDER BY updated_at DESC;
```

### Count VMs by Status

```sql
SELECT status, COUNT(*) as count
FROM vms
GROUP BY status;
```

Expected output:
```
 status    | count
-----------+-------
 available |     5
 in-use    |     3
 failed    |     1
```

### Find VM by Email

```sql
SELECT hostname, status, crd_command
FROM vms
WHERE email = 'user@example.com';
```

### Update VM Status

```sql
-- Mark VM as available
UPDATE vms
SET status = 'available', email = NULL, crd_command = NULL, updated_at = NOW()
WHERE hostname = 'i-0abc123def456';

-- Mark VM as failed
UPDATE vms
SET status = 'failed', updated_at = NOW()
WHERE hostname = 'i-0abc123def456';
```

### Delete VM Record

```sql
DELETE FROM vms WHERE hostname = 'i-0abc123def456';
```

!!! warning
    Only delete after VM instance is terminated in AWS.

### Clear All VMs

```sql
-- Use with caution!
TRUNCATE TABLE vms;
```

## Monitoring LISTEN/NOTIFY

### Listen for VM Updates

```sql
-- In psql session
LISTEN vm_updates;

-- In another session, make a change:
UPDATE vms SET status = 'in-use' WHERE id = 1;

-- First session receives:
Asynchronous notification "vm_updates" received from server process with PID 12345.
```

### Listen from Python

```python
import psycopg2
import select

conn = psycopg2.connect(
    dbname="lablink_db",
    user="lablink",
    password="lablink",
    host="localhost"
)

conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
cursor = conn.cursor()
cursor.execute("LISTEN vm_updates;")

print("Waiting for notifications...")

while True:
    if select.select([conn], [], [], 5) == ([], [], []):
        print("Timeout")
    else:
        conn.poll()
        while conn.notifies:
            notify = conn.notifies.pop(0)
            print(f"Notification: {notify.payload}")
```

## Database Backup

### Manual Backup

```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>

# Backup database
sudo docker exec <container-id> pg_dump -U lablink lablink_db > lablink_backup.sql

# Download backup
scp -i ~/lablink-key.pem ubuntu@<allocator-ip>:~/lablink_backup.sql ./
```

### Automated Backup Script

**`backup.sh`**:
```bash
#!/bin/bash

CONTAINER_ID=$(sudo docker ps --filter "ancestor=ghcr.io/talmolab/lablink-allocator-image" --format "{{.ID}}")
BACKUP_DIR="/home/ubuntu/backups"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

sudo docker exec $CONTAINER_ID pg_dump -U lablink lablink_db > $BACKUP_DIR/lablink_$DATE.sql

# Upload to S3
aws s3 cp $BACKUP_DIR/lablink_$DATE.sql s3://lablink-backups/

# Keep only last 7 days locally
find $BACKUP_DIR -name "lablink_*.sql" -mtime +7 -delete

echo "Backup complete: lablink_$DATE.sql"
```

**Setup cron job**:
```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * /home/ubuntu/backup.sh >> /var/log/lablink-backup.log 2>&1
```

### Restore from Backup

```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>

# Copy backup to instance
scp -i ~/lablink-key.pem lablink_backup.sql ubuntu@<allocator-ip>:~/

# Restore database
sudo docker exec -i <container-id> psql -U lablink lablink_db < lablink_backup.sql
```

## Database Maintenance

### Vacuum Database

Remove dead tuples and reclaim space:

```sql
-- Analyze and vacuum
VACUUM ANALYZE vms;

-- Full vacuum (more aggressive, requires exclusive lock)
VACUUM FULL vms;
```

### Reindex

Rebuild indexes for performance:

```sql
REINDEX TABLE vms;
```

### Check Database Size

```sql
SELECT pg_size_pretty(pg_database_size('lablink_db'));
```

### Check Table Size

```sql
SELECT
  schemaname,
  tablename,
  pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

### View Active Connections

```sql
SELECT
  pid,
  usename,
  application_name,
  client_addr,
  state,
  query
FROM pg_stat_activity
WHERE datname = 'lablink_db';
```

### Kill Idle Connections

```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'lablink_db'
  AND state = 'idle'
  AND state_change < NOW() - INTERVAL '10 minutes';
```

## Migrating to RDS (Production)

For production, consider Amazon RDS for managed PostgreSQL.

### Benefits

- Automated backups
- Multi-AZ high availability
- Automatic failover
- Automated patching
- Monitoring and metrics
- Point-in-time recovery

### Setup RDS Instance

```hcl
# terraform/rds.tf

resource "aws_db_instance" "lablink" {
  identifier        = "lablink-db-${var.environment}"
  engine            = "postgres"
  engine_version    = "13.7"
  instance_class    = "db.t3.micro"
  allocated_storage = 20

  db_name  = "lablink_db"
  username = "lablink"
  password = var.db_password  # From Secrets Manager

  vpc_security_group_ids = [aws_security_group.rds.id]
  db_subnet_group_name   = aws_db_subnet_group.lablink.name

  backup_retention_period = 7
  backup_window          = "03:00-04:00"
  maintenance_window     = "mon:04:00-mon:05:00"

  storage_encrypted      = true
  skip_final_snapshot   = false
  final_snapshot_identifier = "lablink-final-${var.environment}"

  tags = {
    Name = "lablink-db-${var.environment}"
  }
}

output "rds_endpoint" {
  value = aws_db_instance.lablink.endpoint
}
```

### Update Application Configuration

```yaml
db:
  dbname: "lablink_db"
  user: "lablink"
  password: "${DB_PASSWORD}"  # From Secrets Manager
  host: "lablink-db-prod.xxxxx.us-west-2.rds.amazonaws.com"
  port: 5432
```

### Migrate Data

```bash
# Dump from container database
sudo docker exec <container-id> pg_dump -U lablink lablink_db > dump.sql

# Restore to RDS
psql -h lablink-db-prod.xxxxx.us-west-2.rds.amazonaws.com -U lablink -d lablink_db < dump.sql
```

## Troubleshooting

### PostgreSQL Won't Start

**Check logs**:
```bash
sudo docker exec <container-id> tail -f /var/log/postgresql/postgresql-13-main.log
```

**Common issues**:

1. **Port already in use**:
   ```bash
   sudo netstat -tulpn | grep 5432
   # Kill process using port
   ```

2. **Disk full**:
   ```bash
   df -h
   # Clean up space
   ```

3. **Corrupt data files**:
   ```bash
   # Stop container, remove volume, restart
   sudo docker stop <container-id>
   sudo docker rm <container-id>
   # Redeploy with fresh database
   ```

### Cannot Connect to Database

**Check connection from allocator**:
```bash
sudo docker exec <container-id> pg_isready -U lablink
```

**Test connection**:
```bash
sudo docker exec <container-id> psql -U lablink -d lablink_db -c "SELECT 1;"
```

**Check pg_hba.conf**:
```bash
sudo docker exec <container-id> cat /etc/postgresql/13/main/pg_hba.conf
```

Should include:
```
host    all             all             0.0.0.0/0            md5
```

### Database Performance Issues

**Check slow queries**:
```sql
SELECT
  pid,
  now() - pg_stat_activity.query_start AS duration,
  query
FROM pg_stat_activity
WHERE state = 'active'
  AND now() - pg_stat_activity.query_start > interval '5 seconds'
ORDER BY duration DESC;
```

**Enable query logging**:
```bash
# In postgresql.conf
log_min_duration_statement = 1000  # Log queries > 1 second
```

**Add indexes**:
```sql
-- Index on email for faster lookups
CREATE INDEX idx_vms_email ON vms(email);

-- Index on status
CREATE INDEX idx_vms_status ON vms(status);

-- Composite index
CREATE INDEX idx_vms_status_email ON vms(status, email);
```

### Restart PostgreSQL

Known issue requiring manual restart after first boot:

```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>

# Access container
sudo docker exec -it <container-id> bash

# Inside container
/etc/init.d/postgresql restart

# Verify
pg_isready -U lablink
```

## Security Best Practices

1. **Change default password**: See [Security](security.md#database-password)
2. **Use SSL connections**: Configure `sslmode=require`
3. **Restrict pg_hba.conf**: Limit to specific IPs/VPCs
4. **Regular backups**: Automate daily backups
5. **Monitor access logs**: Review connection attempts
6. **Use RDS for production**: Better security and management

## Performance Tuning

### Configuration Recommendations

For allocator with 2GB RAM:

```
# postgresql.conf
shared_buffers = 512MB
effective_cache_size = 1GB
maintenance_work_mem = 128MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 1.1
effective_io_concurrency = 200
work_mem = 5MB
min_wal_size = 1GB
max_wal_size = 4GB
```

### Connection Pooling

For high-concurrency, use pgBouncer:

```yaml
# docker-compose.yml
services:
  pgbouncer:
    image: pgbouncer/pgbouncer
    environment:
      DATABASES_HOST: localhost
      DATABASES_PORT: 5432
      DATABASES_DBNAME: lablink_db
    ports:
      - "6432:6432"
```

## Next Steps

- **[SSH Access](ssh-access.md)**: Connect to database via SSH
- **[Troubleshooting](troubleshooting.md)**: Fix database issues
- **[Security](security.md)**: Secure database access
- **[Architecture](architecture.md)**: Understand database role

## Quick Reference

```sql
-- View all VMs
SELECT * FROM vms;

-- Count by status
SELECT status, COUNT(*) FROM vms GROUP BY status;

-- Find available VMs
SELECT * FROM vms WHERE status = 'available';

-- Update VM status
UPDATE vms SET status = 'available' WHERE hostname = 'i-xxxxx';

-- Backup
pg_dump -U lablink lablink_db > backup.sql

-- Restore
psql -U lablink lablink_db < backup.sql

-- Vacuum
VACUUM ANALYZE vms;
```