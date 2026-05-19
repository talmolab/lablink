from lablink_allocator_service.get_config import get_config


def build_init_sql() -> str:
    """Build the PostgreSQL initialization SQL script as a string."""
    config = get_config()
    DB_NAME = config.db.dbname
    DB_USER = config.db.user
    DB_PASSWORD = config.db.password
    VM_TABLE = config.db.table_name
    # MESSAGE_CHANNEL was the CRD notify channel; no longer needed.

    return f"""
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
    UserEmail VARCHAR(1024),
    InUse BOOLEAN NOT NULL DEFAULT FALSE,
    Healthy VARCHAR(1024),
    Status   VARCHAR(1024),
    CloudInitLogs TEXT,
    DockerLogs TEXT,
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
    CreatedAt TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP,
    boot_id VARCHAR(64),
    disk_free_pct SMALLINT,
    SessionId UUID,
    BrowserToken TEXT,
    VncPassword TEXT,
    Upstream TEXT,
    SessionStartedAt TIMESTAMPTZ,
    machine_identity   TEXT,
    provider           TEXT NOT NULL DEFAULT 'aws',
    endpoint_url       TEXT,
    provider_metadata  JSONB NOT NULL DEFAULT '{{}}',
    client_secret_hash TEXT,
    gpu_present        BOOLEAN,
    gpu_model          TEXT,
    last_release_time  TIMESTAMP
);

CREATE UNIQUE INDEX {VM_TABLE}_browser_token_idx
    ON {VM_TABLE}(BrowserToken) WHERE BrowserToken IS NOT NULL;
CREATE UNIQUE INDEX {VM_TABLE}_session_id_idx
    ON {VM_TABLE}(SessionId) WHERE SessionId IS NOT NULL;
CREATE UNIQUE INDEX {VM_TABLE}_machine_identity_idx
    ON {VM_TABLE}(machine_identity) WHERE machine_identity IS NOT NULL;
CREATE INDEX {VM_TABLE}_provider_idx ON {VM_TABLE}(provider);
CREATE INDEX {VM_TABLE}_assignable_idx
    ON {VM_TABLE}(status, useremail, last_release_time)
    WHERE useremail IS NULL AND status = 'running';

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def main():
    """Write init.sql to the path Postgres' bootstrap step reads."""
    with open("/app/init.sql", "w") as f:
        f.write(build_init_sql())


if __name__ == "__main__":
    main()
