# Run Linting Checks

```bash
ruff check packages/allocator packages/client packages/cli
```

CI runs `ruff check src tests` per package, so lint errors in test files
(E402 especially) fail the build.

`ruff format` is **not** enforced by CI — don't run it on scoped changes, it
reformats unrelated lines.
