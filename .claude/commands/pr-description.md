# Generate Pull Request Description

```bash
git log --oneline main..HEAD
git diff --stat main...HEAD
```

Note the three dots in `main...HEAD` for the diff: it compares against the merge
base, so commits that landed on `main` after you branched don't show up as yours.

Check for a template in `.github/PULL_REQUEST_TEMPLATE/` or
`.github/pull_request_template.md` and follow it if present.
