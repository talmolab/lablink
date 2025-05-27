# lablink-client-service

## Description
This folder contains the Python Package installed in the VM instance. The service is designed to run on a Ubuntu system with NVIDIA GPU support, specifically for use with Chrome Remote Desktop. This is the client side (VM instance) of the LabLink infrastructure. The `subscribe.py` will run as a startup script in the VM.

## Installation
Install Lablink Client Service from [PyPI](https://pypi.org/project/lablink-client-service/). 

```bash
pip install lablink-client-service
```

If installed properly, you should be able to run the following command:

```bash
subscribe
```

## Usage in the Client VM
Run the following command with necessary configuration based on the allocator's host and port manually in the VM instance terminal:

```bash
subscribe allocator.host=<allocator_host> allocator.port=<allocator.port>
```

This command will subscribe to the message from the allocator web application. 

## Configuration
The configuration can be overridden by passing a different config file path as an argument to the script. For example:

```bash
python -m lablink_client_service.subscribe allocator.host=<your_allocator_host> allocator.port=<your_allocator_port>
```

- `allocator.host`: The hostname of the allocator server.
- `allocator.port`: The port of the allocator server.

You can also fix the configuration by modifying the `config.yaml` file in the `lablink_client_service` directory. The script will automatically load the configuration from this file.

## Development Setup
For developers modifying this package, follow this guide. While the VMs will just install these dependencies globally, developers should use a venv. For developers:

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

## Usage in Local Machine

Run the `subscribe.py` script to start the service. This script will subscribe to the LabLink server and listen for incoming messages.

```bash
python -m lablink_client_service.subscribe
```

> This script will run with the default configuration. To change the configuration, you can modify the `config.yaml` file in the `lablink_client_service` directory. The script will automatically load the configuration from this file.