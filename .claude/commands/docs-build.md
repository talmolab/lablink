# Build Documentation

```bash
uv run --extra docs mkdocs build --strict
```

`--strict` turns warnings (dead internal links, missing nav entries) into
failures, which is what `docs.yml` does in CI. Output lands in `site/`.
