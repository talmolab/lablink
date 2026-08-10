# Auto-Fix Linting Issues

```bash
ruff check --fix packages/allocator packages/client packages/cli
```

Deliberately no `ruff format`: it isn't CI-enforced here and would reformat lines
your change never touched. Preview with `--diff` instead of `--fix` to inspect
first.
