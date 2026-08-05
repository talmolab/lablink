# LabLink Client

Client service for LabLink VM management.

## Installation

```bash
pip install lablink-client-service
```

## Usage

The package installs these console scripts, all run by the client container's
entrypoint rather than invoked by hand:

```bash
agent                 # HTTP server on :7070 the allocator calls to rotate the KasmVNC password
check_gpu             # Report GPU presence/health to the allocator
heartbeat             # Periodic liveness + health signals so the allocator can spot silent failures
update_inuse_status   # Report whether the configured software is running
lablink-monitoring    # Session-metrics sampler (only with monitoring.enabled)
```

## Documentation

Full documentation at https://talmolab.github.io/lablink/
