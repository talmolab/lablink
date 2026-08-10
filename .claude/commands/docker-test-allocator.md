# Test Allocator Docker Container

```bash
# Console scripts resolve
docker run --rm lablink-allocator:dev bash -c \
  "which lablink-allocator generate-init-sql lablink-validate-config"

# Package imports
docker run --rm lablink-allocator:dev python -c \
  "from lablink_allocator_service import main, get_config; print('Imports OK')"

# Venv is the one on PATH
docker run --rm lablink-allocator:dev bash -c 'echo $VIRTUAL_ENV; which python'
```

The venv is at an explicit path (`/app/.venv`), so `which python` pointing at
system Python means the image is broken.

Tear down leftover containers from manual testing before trusting a local pass — a
real container left running can make an unmocked docker-exec test pass locally
while it fails in CI's clean environment.
