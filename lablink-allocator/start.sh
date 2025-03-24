#!/bin/bash

# Start PostgreSQL service
service postgresql start

#Wait for PostgreSQL to be ready
until pg_isready -U lablink -d lablink_db; do
    echo "Waiting for PostgreSQL to start..."
    sleep 2
done

# Run database migrations (if applicable)
flask db upgrade

# # Start the Flask application
# exec python main.py
