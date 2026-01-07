from lablink_allocator_service.get_config import get_config


def main():
    """Generate PostgreSQL initialization SQL script."""
    config = get_config()

    # Load database configuration from config.yaml
    DB_NAME = config.db.dbname
    DB_USER = config.db.user
    DB_PASSWORD = config.db.password
    VM_TABLE = config.db.table_name
    MESSAGE_CHANNEL = config.db.message_channel

    template = f"""
ALTER SYSTEM SET listen_addresses = '*';

SET client_min_messages TO WARNING;
DROP USER IF EXISTS {DB_USER};
CREATE USER {DB_USER} WITH ENCRYPTED PASSWORD '{DB_PASSWORD}';
ALTER USER {DB_USER} WITH LOGIN;
CREATE DATABASE {DB_NAME} OWNER {DB_USER};
GRANT ALL PRIVILEGES ON DATABASE {DB_NAME} TO {DB_USER};

\\c {DB_NAME};

SET ROLE {DB_USER};

CREATE TABLE IF NOT EXISTS scheduled_destructions (
    id SERIAL PRIMARY KEY,
    schedule_name VARCHAR(255) NOT NULL UNIQUE,
    destruction_time TIMESTAMP NOT NULL,
    recurrence_rule VARCHAR(255),
    created_by VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'scheduled',
    execution_count INTEGER DEFAULT 0,
    last_execution_time TIMESTAMP,
    last_execution_result TEXT,
    notification_enabled BOOLEAN DEFAULT TRUE,
    notification_hours_before INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_destruction_time ON scheduled_destructions(destruction_time);
CREATE INDEX idx_status ON scheduled_destructions(status);

CREATE OR REPLACE FUNCTION update_scheduled_destructions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER scheduled_destructions_updated_at
    BEFORE UPDATE ON scheduled_destructions
    FOR EACH ROW
    EXECUTE FUNCTION update_scheduled_destructions_updated_at();

CREATE TABLE IF NOT EXISTS {VM_TABLE} (
    HostName VARCHAR(1024) PRIMARY KEY,
    Pin VARCHAR(1024),
    CrdCommand VARCHAR(1024),
    UserEmail VARCHAR(1024),
    InUse BOOLEAN NOT NULL DEFAULT FALSE,
    Healthy VARCHAR(1024),
    Status   VARCHAR(1024),
    Logs TEXT,
    TerraformApplyStartTime TIMESTAMP,
    TerraformApplyEndTime TIMESTAMP,
    TerraformApplyDurationSeconds FLOAT,
    CloudInitStartTime TIMESTAMP,
    CloudInitEndTime TIMESTAMP,
    CloudInitDurationSeconds FLOAT,
    ContainerStartTime TIMESTAMP,
    ContainerEndTime TIMESTAMP,
    ContainerStartupDurationSeconds FLOAT,
    TotalStartupDurationSeconds FLOAT,
    CreatedAt TIMESTAMP DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION notify_crd_command_update()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify(
        '{MESSAGE_CHANNEL}',
        json_build_object(
            'HostName', NEW.HostName,
            'CrdCommand', NEW.CrdCommand,
            'Pin', NEW.Pin
        )::text
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_crd_command_insert_or_update
AFTER INSERT OR UPDATE OF CrdCommand ON {VM_TABLE}
FOR EACH ROW
EXECUTE FUNCTION notify_crd_command_update();

"""

    with open("/app/init.sql", "w") as f:
        f.write(template)


if __name__ == "__main__":
    main()
