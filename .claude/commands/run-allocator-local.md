# Run Allocator Locally

```bash
cd packages/allocator && PYTHONPATH=src uv run lablink-allocator
```

Needs a reachable Postgres and a config. `get_config()` reads `CONFIG_DIR`
(default `/config`) and `CONFIG_NAME` (default `config.yaml`), falling back to the
bundled `conf/config.yaml`, so point it at a local copy:

```bash
cd packages/allocator && CONFIG_DIR=$PWD/src/lablink_allocator_service/conf \
  CONFIG_NAME=config PYTHONPATH=src uv run lablink-allocator
```

Running the full stack in Docker is usually less setup — see
`/docker-build-allocator`.
