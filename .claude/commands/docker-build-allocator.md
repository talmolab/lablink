# Build Allocator Docker Images

```bash
cd packages/allocator && docker build --platform linux/amd64 \
  -t lablink-allocator:dev -f Dockerfile.dev .
```

Two things are not optional:

- **Context must be the package dir, not the repo root.** `Dockerfile.dev`'s COPY
  paths (`start.sh`, `lablink-nginx.conf`, `pg_hba.conf`) are relative to
  `packages/allocator/`, so building from the root fails with
  `"/start.sh": not found`.
- **`--platform linux/amd64`** — the image pulls an amd64-only `kasmvncserver`
  .deb, which aborts a native arm64 build with apt exit code 100.

Production image installs the published PyPI package instead of local code:

```bash
cd packages/allocator && docker build --platform linux/amd64 \
  -t lablink-allocator:prod -f Dockerfile .
```

Only `Dockerfile.dev` runs your branch code.
