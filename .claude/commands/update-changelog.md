# Update CHANGELOG

```bash
# What has landed since the last release
git log --oneline $(git describe --tags --abbrev=0)..HEAD
```

Group entries under the release heading by Added / Changed / Fixed / Removed, in
the style already in `CHANGELOG.md`. Reference PR numbers — the merge commits carry
them.
