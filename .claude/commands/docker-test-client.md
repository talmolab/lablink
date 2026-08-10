# Test Client Docker Container

```bash
# Console scripts resolve
docker run --rm lablink-client:dev bash -c \
  "which agent check_gpu heartbeat update_inuse_status lablink-monitoring"

# Package imports
docker run --rm lablink-client:dev python -c \
  "from lablink_client_service import check_gpu, heartbeat; print('Imports OK')"

# Venv is the one on PATH
docker run --rm lablink-client:dev bash -c 'echo $VIRTUAL_ENV; which python'
```

The venv is at `/home/client/.venv`. GPU checks need `--gpus all` and a real
NVIDIA runtime; without one `check_gpu` correctly reports no GPU.
