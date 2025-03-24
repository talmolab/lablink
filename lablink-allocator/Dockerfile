FROM python:3.11-slim

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV POSTGRES_USER=lablink
ENV POSTGRES_PASSWORD=lablink
ENV POSTGRES_DB=lablink_db

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

# Copy the database initialization script
COPY init.sql /docker-entrypoint-initdb.d/init.sql

# Expose ports for Flask and PostgreSQL
EXPOSE 5000 5432

# Copy and set permissions for startup script
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Set the entrypoint script
CMD ["/start.sh"]
