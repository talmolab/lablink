DROP USER IF EXISTS lablink;
CREATE USER lablink WITH ENCRYPTED PASSWORD 'lablink';
ALTER USER lablink WITH LOGIN;
CREATE DATABASE lablink_db OWNER lablink;
GRANT ALL PRIVILEGES ON DATABASE lablink_db TO lablink;

\c lablink_db;

CREATE TABLE IF NOT EXISTS vm_requests (
    HostName VARCHAR(1024) PRIMARY KEY,
    Pin VARCHAR(1024) NOT NULL,
    CrdCommand VARCHAR(1024) NOT NULL,
    UserEmail VARCHAR(1024) NOT NULL,
    InUse BOOLEAN DEFAULT FALSE
);

-- Function to send notification on CrdCommand update
CREATE OR REPLACE FUNCTION notify_crd_command_update()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify(
        'vm_updates',
        json_build_object(
            'HostName', NEW.HostName,
            'CrdCommand', NEW.CrdCommand
        )::text
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;