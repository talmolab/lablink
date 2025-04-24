# lablink-client-service

## Description
This folder contains the Python Package installed in the VM instance. The service is designed to run on a Ubuntu system with NVIDIA GPU support, specifically for use with Chrome Remote Desktop. This is the client side (VM instance) of the LabLink infrastructure. The `subscribe.py` will run as a startup script in the VM.

## Depdenencies
While the VMs will just install these dependencies globally, developers should use a venv. For developers:

1. Open terminal in project root directory
2. Create a virtual environment

```bash
python3 -m venv venv
```

3. Activate the virtual environment

```bash
source venv/bin/activate
```

4. Install the dependencies

```bash
pip install -e ".[dev]"
```

5. Deactivate the virtual environment when done

```bash
deactivate
```

6. To remove the virtual environment, delete the `venv` directory

## Usage

Run the `subscribe.py` script to start the service. This script will subscribe to the LabLink server and listen for incoming messages.

```bash
python -m lablink_client_service.subscribe
```

> This script will run with the default configuration. To change the configuration, you can modify the `config.yaml` file in the `lablink_client_service` directory. The script will automatically load the configuration from this file.

## Configuration
The configuration can be overridden by passing a different config file path as an argument to the script. For example:

```bash
python -m lablink_client_service.subscribe db.dbname=<db-name> db.host=<db-host> db.port=<db-port> db.user=<db-user> db.password=<db-password> db.table_name=<db-table-name>
```

- `db.dbname`: The name of the PostgreSQL database to connect to.
- `db.host`: The host of the database.
- `db.port`: The port of the database.
- `db.user`: The user to connect to the database.
- `db.password`: The password to connect to the database.
- `db.table_name`: The name of the table to use in the database.

You can also fix the configuration by modifying the `config.yaml` file in the `lablink_client_service` directory. The script will automatically load the configuration from this file.