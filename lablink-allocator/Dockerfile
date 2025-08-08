FROM python:3.11-slim

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV DATABASE_URL=postgresql://lablink:lablink@localhost:5432/lablink_db


# Install dependencies
RUN apt-get update && apt-get install -y \
    postgresql postgresql-contrib \
    rsync \
    openssh-client \
    libpq-dev && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y curl unzip && \
    curl -fsSL https://releases.hashicorp.com/terraform/1.4.6/terraform_1.4.6_linux_amd64.zip -o /tmp/terraform.zip && \
    unzip /tmp/terraform.zip -d /usr/local/bin && \
    rm /tmp/terraform.zip




# Set working directory
WORKDIR /app

# Copy application files and requirements
COPY lablink-allocator/lablink-allocator-service /app

COPY lablink-allocator/lablink-allocator-service/pg_hba.conf /etc/postgresql/15/main/pg_hba.conf

COPY lablink-allocator/lablink-allocator-service/requirements.txt requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONPATH=/usr/local/lib/python3.11/site-packages:$PYTHONPATH

COPY lablink-allocator/lablink-allocator-service/generate-init-sql.py /app
RUN python generate-init-sql.py

# Expose ports for Flask
EXPOSE 5000

# Copy and set permissions for startup script
COPY lablink-allocator/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Set the entrypoint script to start the Flask application
CMD ["/bin/bash", "-c", "/app/start.sh"]

