# Build Documentation

Build the MkDocs documentation for deployment verification.

## Quick Command

```bash
# Using uv (recommended)
uv run --extra docs mkdocs build
```

Builds static site to `site/` directory.

## With Virtual Environment

```bash
# Activate docs environment
source .venv-docs/bin/activate  # Unix/Mac
# .venv-docs\Scripts\activate  # Windows

# Build docs
mkdocs build
```

## What Gets Built

The build process:
1. Renders all markdown files to HTML
2. Generates navigation structure
3. Applies Material theme
4. Creates search index
5. Copies static assets
6. Outputs to `site/` directory

## Build Options

```bash
# Clean build (remove old site/ first)
mkdocs build --clean

# Strict mode (fail on warnings)
mkdocs build --strict

# Build to custom directory
mkdocs build --site-dir custom-output

# Verbose output
mkdocs build --verbose
```

## Verify Build

### Check Output Directory

```bash
# List generated files
ls -R site/

# Check index exists
test -f site/index.html && echo "Build successful"
```

### Preview Built Site

```bash
# Serve built site (no live reload)
cd site
python -m http.server 8000

# Or with npx
npx serve site
```

Open http://localhost:8000

### Validate Links

```bash
# Build in strict mode to catch broken links
mkdocs build --strict
```

## Build for Deployment

### GitHub Pages

```bash
# Build and deploy to gh-pages branch
mkdocs gh-deploy

# With custom commit message
mkdocs gh-deploy --message "docs: Update documentation"

# Force push (use with caution)
mkdocs gh-deploy --force
```

**Note**: The CI workflow handles deployment automatically. Manual `gh-deploy` rarely needed.

## Pre-Deployment Checklist

Before deploying:

```bash
# 1. Build in strict mode
mkdocs build --strict --clean

# 2. Check for warnings
# Review build output for issues

# 3. Preview locally
mkdocs serve

# 4. Verify all pages load
# Click through navigation

# 5. Test search functionality
# Try searching for key terms

# 6. Check mobile responsiveness
# Resize browser window
```

## Troubleshooting

### Build Fails with Errors
**Symptom**: Build exits with error messages

**Common Issues**:
1. **Broken links**: Fix paths in markdown files
2. **Missing files**: Ensure referenced files exist
3. **Invalid YAML**: Check `mkdocs.yml` syntax
4. **Plugin errors**: Verify plugin configuration

### Warnings During Build
**Symptom**: Build succeeds but shows warnings

**Solutions**:
```bash
# Build in strict mode to treat warnings as errors
mkdocs build --strict

# Review and fix each warning
# Common: broken links, missing images, invalid anchors
```

### Site Directory Not Created
**Symptom**: `site/` directory doesn't exist after build

**Solutions**:
1. Check for build errors in output
2. Verify `mkdocs.yml` exists and is valid
3. Ensure `docs/` directory has content
4. Run with verbose flag: `mkdocs build --verbose`

### Large Site Size
**Symptom**: `site/` directory is very large

**Check**:
```bash
# Check site size
du -sh site/

# Find large files
find site/ -type f -size +1M -exec ls -lh {} \;
```

**Solutions**:
1. Optimize images in `docs/assets/`
2. Remove unnecessary files from docs
3. Check for duplicate assets

## Build Output Structure

```
site/
├── index.html              # Home page
├── getting-started/        # Getting started guide
├── configuration/          # Configuration docs
├── api-reference/          # API documentation
├── assets/                 # CSS, JS, images
├── search/                 # Search index
└── sitemap.xml            # SEO sitemap
```

## CI Integration

Documentation builds automatically in `.github/workflows/docs.yml`:
- **On PR**: Build to verify no errors
- **On push to main**: Build and deploy to GitHub Pages

## Manual Deployment

If you need to manually deploy:

```bash
# 1. Build in strict mode
mkdocs build --strict --clean

# 2. Deploy to GitHub Pages
mkdocs gh-deploy --message "docs: Manual deployment"

# 3. Verify deployment
# Visit https://talmolab.github.io/lablink/
```

## Related Commands

- `/docs-serve` - Serve documentation locally with live reload