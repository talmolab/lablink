from db_config import DB_NAME, DB_USER, DB_PASSWORD, VM_TABLE, MESSAGE_CHANNEL

template = f"""
ALTER SYSTEM SET listen_addresses = '*';

DROP USER IF EXISTS {DB_USER};
CREATE USER {DB_USER} WITH ENCRYPTED PASSWORD '{DB_PASSWORD}';
ALTER USER {DB_USER} WITH LOGIN;
CREATE DATABASE {DB_NAME} OWNER {DB_USER};
GRANT ALL PRIVILEGES ON DATABASE {DB_NAME} TO {DB_USER};

\\c {DB_NAME};

SET ROLE {DB_USER};

CREATE TABLE IF NOT EXISTS {VM_TABLE} (
    HostName VARCHAR(1024) PRIMARY KEY,
    Pin VARCHAR(1024),
    CrdCommand VARCHAR(1024),
    UserEmail VARCHAR(1024),
    InUse BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE OR REPLACE FUNCTION notify_crd_command_update()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify(
        {MESSAGE_CHANNEL},
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
AFTER INSERT OR UPDATE OF CrdCommand ON vm_requests
FOR EACH ROW
EXECUTE FUNCTION notify_crd_command_update();

INSERT INTO {VM_TABLE} (HostName, Pin, CrdCommand, UserEmail, InUse) 
VALUES
('host1', '', '', '', FALSE),
('host2', '', '', '', FALSE),
('host3', '', '', '', FALSE),
('host4', '', '', '', FALSE);
"""

with open("/app/init.sql", "w") as f:
    f.write(template)
