CREATE USER lablink WITH PASSWORD 'lablink';
CREATE DATABASE lablink_db OWNER lablink;
GRANT ALL PRIVILEGES ON DATABASE lablink_db TO lablink;
