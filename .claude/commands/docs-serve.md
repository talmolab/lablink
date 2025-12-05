# Serve Documentation Locally

Serve the MkDocs documentation locally for preview during development.

## Quick Command

```bash
# Using uv (recommended)
uv run --extra docs mkdocs serve
```

Opens browser to http://localhost:8000

## Alternative Methods

### With uv Virtual Environment

```bash
# Create dedicated docs environment
uv venv .venv-docs
source .venv-docs/bin/activate  # Unix/Mac
# .venv-docs\Scripts\activate  # Windows

# Install docs dependencies
uv sync --extra docs

# Serve docs
mkdocs serve
```

### With pip

```bash
# Install docs dependencies
pip install -e ".[docs]"

# Serve docs
mkdocs serve
```

## What Gets Served

The documentation includes:
- **User guides**: Getting started, configuration, deployment
- **API reference**: Auto-generated from docstrings (mkdocstrings)
- **Development docs**: Contributing, testing, workflows
- **OpenSpec docs**: Change proposals and specifications
- **Changelog**: Auto-generated from git history

## Server Options

```bash
# Serve on specific port
mkdocs serve --dev-addr localhost:8080

# Serve on all interfaces (access from network)
mkdocs serve --dev-addr 0.0.0.0:8000

# Enable strict mode (fail on warnings)
mkdocs serve --strict

# Disable live reload
mkdocs serve --no-livereload
```

## Live Reload

MkDocs automatically reloads when you edit files:
- Markdown files in `docs/`
- `mkdocs.yml` configuration
- Theme files

Just save your changes and the browser refreshes automatically.

## Preview Workflow

1. **Start server**:
   ```bash
   uv run --extra docs mkdocs serve
   ```

2. **Edit documentation**:
   - Modify files in `docs/`
   - Add new pages to `mkdocs.yml`
   - Update docstrings in source code

3. **Preview changes**:
   - Browser auto-refreshes
   - Check formatting, links, code blocks

4. **Commit when satisfied**:
   ```bash
   git add docs/ mkdocs.yml
   git commit -m "docs: Update documentation"
   ```

## Troubleshooting

### Module Not Found
**Symptom**: `ModuleNotFoundError: No module named 'mkdocs'`

**Solutions**:
```bash
# Install docs dependencies
uv sync --extra docs
# or
pip install -e ".[docs]"
```

### Port Already in Use
**Symptom**: `OSError: [Errno 48] Address already in use`

**Solutions**:
```bash
# Use different port
mkdocs serve --dev-addr localhost:8001

# Or kill process using port 8000
# Unix/Mac:
lsof -ti:8000 | xargs kill -9
# Windows PowerShell:
Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess | Stop-Process
```

### Warnings About Broken Links
**Symptom**: Warnings about broken internal links

**Solutions**:
1. Check file paths are correct (case-sensitive)
2. Update links to match actual file locations
3. Use relative paths: `[text](../other-page.md)`

### Changes Not Reflected
**Symptom**: Edits don't show in browser

**Solutions**:
1. Check server output for errors
2. Hard refresh browser: Ctrl+F5 (Windows) or Cmd+Shift+R (Mac)
3. Restart mkdocs serve
4. Clear browser cache

## Documentation Structure

```
docs/
├── index.md              # Home page
├── getting-started.md    # Installation and quickstart
├── configuration.md      # Configuration guide
├── deployment.md         # Deployment instructions
├── api-reference.md      # API documentation
├── development.md        # Development guide
├── workflows.md          # CI/CD workflows
├── troubleshooting.md    # Common issues
├── changelog.md          # Generated from git history
├── scripts/              # Doc generation scripts
│   └── gen_changelog.py  # Changelog generator
└── assets/               # Images, diagrams
```

## Adding New Pages

1. **Create markdown file**:
   ```bash
   touch docs/new-page.md
   ```

2. **Add to navigation** in `mkdocs.yml`:
   ```yaml
   nav:
     - Home: index.md
     - New Page: new-page.md
   ```

3. **Preview**:
   - Save files
   - Browser auto-refreshes
   - New page appears in navigation

## CI Integration

Documentation is built and deployed automatically in `.github/workflows/docs.yml`:
- **Trigger**: Pushes to main, PRs affecting docs/
- **Deployment**: GitHub Pages at https://talmolab.github.io/lablink/

## Related Commands

- `/docs-build` - Build documentation for deployment verification