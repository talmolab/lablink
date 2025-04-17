FROM python:3.11-slim

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV DATABASE_URL=postgresql://lablink:lablink@localhost:5432/lablink_db


# Install dependencies
RUN apt-get update && apt-get install -y \
    postgresql postgresql-contrib \
    libpq-dev && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y curl unzip && \
    curl -fsSL https://releases.hashicorp.com/terraform/1.4.6/terraform_1.4.6_linux_amd64.zip -o /tmp/terraform.zip && \
    unzip /tmp/terraform.zip -d /usr/local/bin && \
    rm /tmp/terraform.zip




# Set working directory
WORKDIR /app

# Copy application files
COPY lablink-allocator/lablink-allocator-service /app

COPY lablink-allocator/requirements.txt /app/

COPY lablink-allocator/lablink-allocator-service/pg_hba.conf /etc/postgresql/15/main/pg_hba.conf

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY lablink-allocator/generate-init-sql.py /app
COPY db_config.py /app
RUN python generate-init-sql.py

# Expose ports for Flask and PostgreSQL
EXPOSE 5000 5432

# Copy and set permissions for startup script
COPY lablink-allocator/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Set the entrypoint script
CMD ["/bin/bash", "-c", "/app/start.sh"]

