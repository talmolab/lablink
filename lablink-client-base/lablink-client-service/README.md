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
pip install -r requirements.txt
```

5. Deactivate the virtual environment when done

```bash
deactivate
```

6. To remove the virtual environment, delete the `venv` directory