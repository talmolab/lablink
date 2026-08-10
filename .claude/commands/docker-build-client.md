# Build Client Docker Images

```bash
cd packages/client && docker build --platform linux/amd64 \
  -t lablink-client:dev -f Dockerfile.dev .
```

Context must be the package dir (COPY paths are relative to it), and the CUDA base
image is amd64-only.

Production image installs from PyPI rather than local code:

```bash
cd packages/client && docker build --platform linux/amd64 \
  -t lablink-client:prod -f Dockerfile .
```
