#!/bin/bash

export POSTGRES_HOST_AUTH_METHOD=trust

PG_HBA_CONF="/etc/postgresql/15/main/pg_hba.conf"
echo "Adding host entry to pg_hba.conf..."
echo "host    all             all             0.0.0.0/0            md5" >> $PG_HBA_CONF

pg_ctlcluster 15 main restart

# Wait for PostgreSQL to be ready
until pg_isready -U postgres; do
    echo "Waiting for PostgreSQL to start..."
    sleep 2
done

# Run the init.sql script as the postgres superuser
echo "Running init.sql..."
su postgres -c "psql -d postgres -f /app/init.sql"

# Check if the psql command was successful
if [ $? -eq 0 ]; then
    echo "init.sql executed successfully."
else
    echo "Error executing init.sql."
    exit 1  # Exit if there was an error
fi

# Wait for the new user and database to be ready
until pg_isready -U lablink -d lablink_db; do
    echo "Waiting for lablink_db to be ready..."
    sleep 2
done

# Run database migrations (if applicable)
flask db upgrade  # Uncomment if migrations are required

# Start the Flask application
echo "Starting Flask app..."
exec python main.py
echo "Amitha here"
