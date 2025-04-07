FROM python:3.11-slim

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV DATABASE_URL=postgresql://lablink:lablink@localhost:5432/lablink_db


# Install dependencies
RUN apt-get update && apt-get install -y \
    postgresql postgresql-contrib \
    libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application files
COPY lablink-allocator-service /app

COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONPATH=/usr/local/lib/python3.11/site-packages:$PYTHONPATH

# Copy the database initialization script
COPY init.sql /app/init.sql

# Expose ports for Flask and PostgreSQL
EXPOSE 5000 5432

# Copy and set permissions for startup script
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Set the entrypoint script
CMD ["/bin/bash", "-c", "/app/start.sh"]

