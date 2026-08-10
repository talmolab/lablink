# Review GitHub Pull Request

```bash
gh pr view <PR> --comments
gh api repos/talmolab/lablink/pulls/<PR>/comments \
  --jq '.[] | {path, line, body}'
gh api repos/talmolab/lablink/pulls/<PR>/reviews --jq '.[].body'
gh pr diff <PR>
```

Read the existing comments before adding any — most PRs here already carry review
history, and repeating a resolved point is noise.

`/review` and `/code-review` are the built-in review skills; this file is just the
`gh` plumbing for inspecting a PR by hand.
