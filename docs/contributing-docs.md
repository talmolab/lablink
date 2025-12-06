# Contributing to Documentation

This guide covers how to contribute to LabLink documentation.

## Documentation System

LabLink uses **MkDocs** with the **Material** theme for documentation.

**Key Features**:
- Markdown-based documentation
- Automatic API reference generation from Python docstrings
- Automatic changelog generation from git history
- Version management (multiple doc versions)
- Search functionality
- Dark/light mode

## Quick Start

### Setup

**Option 1: Using uv (Recommended)**

```bash
# Clone repository
git clone https://github.com/talmolab/lablink.git
cd lablink

# Quick test (creates temporary environment automatically)
uv run --extra docs mkdocs serve

# Or create persistent virtual environment
uv venv .venv-docs
# Windows
.venv-docs\Scripts\activate
# macOS/Linux
source .venv-docs/bin/activate

# Install dependencies
uv sync --extra docs
```

**Option 2: Using pip**

```bash
# Clone repository
git clone https://github.com/talmolab/lablink.git
cd lablink

# Create virtual environment
python -m venv .venv-docs
# Windows
.venv-docs\Scripts\activate
# macOS/Linux
source .venv-docs/bin/activate

# Install documentation dependencies (from pyproject.toml)
pip install -e ".[docs]"
```

### Build and Preview

```bash
# Serve documentation locally
mkdocs serve

# Open http://localhost:8000 in browser
```

Changes to `.md` files will auto-reload in the browser.

### Build Static Site

```bash
# Build documentation
mkdocs build

# Output in site/ directory
```

## Documentation Structure

```
lablink/
├── mkdocs.yml              # MkDocs configuration
├── pyproject.toml          # Python dependencies (docs extra)
├── docs/
│   ├── index.md           # Homepage
│   ├── prerequisites.md   # Getting Started section
│   ├── quickstart.md
│   ├── installation.md
│   ├── architecture.md    # User Guides section
│   ├── configuration.md
│   ├── adapting.md
│   ├── deployment.md
│   ├── workflows.md
│   ├── ssh-access.md
│   ├── database.md
│   ├── testing.md
│   ├── aws-setup.md       # AWS Setup section
│   ├── security.md
│   ├── cost-estimation.md
│   ├── troubleshooting.md # Reference section
│   ├── faq.md
│   ├── contributing-docs.md
│   ├── scripts/
│   │   ├── gen_ref_pages.py    # Auto-generates API docs
│   │   └── gen_changelog.py    # Auto-generates changelog
│   └── assets/            # Images, diagrams, etc.
└── .github/workflows/
    └── docs.yml           # Documentation CI/CD
```

## Writing Documentation

### Markdown Basics

```markdown
# Page Title (H1)

## Section (H2)

### Subsection (H3)

**Bold text**
*Italic text*
`inline code`

[Link text](https://example.com)
[Internal link](other-page.md)

- Bullet list
- Item 2

1. Numbered list
2. Item 2
```

### Code Blocks

Use fenced code blocks with language specification:

````markdown
```python
def hello_world():
    print("Hello, World!")
```

```bash
terraform apply -var="resource_suffix=dev"
```

```yaml
db:
  host: localhost
  port: 5432
```
````

### Admonitions

Use admonitions for notes, warnings, tips:

```markdown
!!! note
    This is a note.

!!! warning
    This is a warning.

!!! tip
    This is a helpful tip.

!!! danger
    This is critical information.
```

**Renders as**:

!!! note
    This is a note.

!!! warning
    This is a warning.

### Tabs

For multi-option content:

```markdown
=== "macOS"
    ```bash
    brew install terraform
    ```

=== "Linux"
    ```bash
    wget https://releases.hashicorp.com/terraform/...
    ```

=== "Windows"
    Download from terraform.io
```

**Renders as**:

=== "macOS"
    ```bash
    brew install terraform
    ```

=== "Linux"
    ```bash
    wget https://releases.hashicorp.com/terraform/...
    ```

=== "Windows"
    Download from terraform.io

### Tables

```markdown
| Column 1 | Column 2 | Column 3 |
|----------|----------|----------|
| Value 1  | Value 2  | Value 3  |
| Value 4  | Value 5  | Value 6  |
```

### Internal Links

```markdown
See [Configuration](configuration.md) for details.

Link to specific section: [Configuration → Database](configuration.md#database-options-db)
```

### Images

```markdown
![Alt text](assets/diagram.png)

# With caption
<figure markdown>
  ![Alt text](assets/diagram.png)
  <figcaption>Caption text</figcaption>
</figure>
```

## Documentation Guidelines

### Style Guide

1. **Be concise**: Short sentences, clear language
2. **Use active voice**: "Run the command" not "The command should be run"
3. **Include examples**: Show don't just tell
4. **Test commands**: Verify all bash commands work
5. **Update dates**: Use current years in examples
6. **Cross-reference**: Link to related pages
7. **Use consistent terminology**: "allocator" not "allocator server" or "allocation service"

### Page Structure

Every documentation page should have:

1. **Title** (H1): Page name
2. **Introduction**: Brief overview (1-2 sentences)
3. **Main content**: Organized with H2/H3 sections
4. **Examples**: Code samples and use cases
5. **Related links**: "Next Steps" or "See Also" section

**Example Template**:

```markdown
# Page Title

Brief introduction explaining what this page covers.

## Main Section

Content here.

### Subsection

More detailed content.

## Examples

Practical examples.

## Troubleshooting

Common issues.

## Next Steps

- [Related Page 1](page1.md)
- [Related Page 2](page2.md)
```

### Code Examples

**Good**:
```bash
# Comment explaining what this does
terraform apply -var="resource_suffix=dev"
```

**Bad**:
```bash
terraform apply
```

Always:
- Include comments
- Show complete commands
- Provide context
- Test before documenting

### Command Documentation

When documenting commands:

1. **Show the command**
2. **Explain what it does**
3. **Show expected output** (if helpful)
4. **Mention common errors**

**Example**:

```markdown
### Connect to Allocator

SSH into the allocator instance:

\`\`\`bash
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>
\`\`\`

**Expected output**:
\`\`\`
Welcome to Ubuntu 20.04.6 LTS
...
ubuntu@ip-xxx-xx-xx-xx:~$
\`\`\`

**Common errors**: See [Troubleshooting → SSH Issues](troubleshooting.md#ssh-access-issues)
```

## API Documentation

### Python Docstrings

API documentation is auto-generated from docstrings. Use Google-style docstrings:

```python
def request_vm(email: str, crd_command: str) -> dict:
    """Request a VM from the allocator.

    Args:
        email: User email address
        crd_command: Command to execute on the VM

    Returns:
        Dictionary containing VM assignment details:
        - hostname: VM hostname
        - status: VM status
        - assigned_at: Assignment timestamp

    Raises:
        ValueError: If email is invalid
        RuntimeError: If no VMs available

    Example:
        >>> result = request_vm("user@example.com", "python train.py")
        >>> print(result['hostname'])
        i-0abc123def456
    """
    # Implementation
```

### Documenting New Modules

When adding new Python modules:

1. **Add docstrings** to all public functions/classes
2. **Run docs build** to see generated API docs:
   ```bash
   mkdocs serve
   # Navigate to Reference → API Reference
   ```
3. **Verify** documentation is clear and complete

## Configuration Reference

When documenting configuration options:

1. **Use tables** for option lists
2. **Include**:
   - Option name
   - Type
   - Default value
   - Description
3. **Provide examples**

**Example**:

```markdown
### Database Options (`db`)

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `dbname` | string | `lablink_db` | Database name |
| `user` | string | `lablink` | Database username |
| `password` | string | `lablink` | Database password |

**Example**:
\`\`\`yaml
db:
  dbname: "lablink_db"
  user: "lablink"
  password: "secure_password"
\`\`\`
```

## Updating Navigation

Navigation is defined in `mkdocs.yml`:

```yaml
nav:
  - Home: index.md
  - Getting Started:
      - Prerequisites: prerequisites.md
      - Installation: installation.md
  - User Guides:
      - Configuration: configuration.md
      - Deployment: deployment.md
```

When adding a new page:

1. Create the `.md` file in `docs/`
2. Add entry to `nav` in `mkdocs.yml`
3. Build docs to verify

## Adding Assets

### Images

1. Place images in `docs/assets/`
2. Use descriptive names: `architecture-diagram.png`
3. Reference in markdown:
   ```markdown
   ![Architecture Diagram](assets/architecture-diagram.png)
   ```

### Diagrams

**Preferred: Use Mermaid diagrams** for all documentation visuals. Mermaid is text-based, version-controlled, and fully supported by MkDocs Material.

#### When to Use Mermaid

- **Flowcharts**: Decision trees, process flows, CI/CD pipelines
- **Sequence Diagrams**: Component interactions, API flows, service communication
- **State Diagrams**: VM lifecycle, status transitions
- **ER Diagrams**: Database schemas, table relationships
- **Graphs**: System architecture, deployment diagrams

#### Mermaid Examples

**Flowchart (Decision Tree)**:

```markdown
\`\`\`mermaid
flowchart TD
    Start[User Request] --> Check{VM Available?}
    Check -->|Yes| Assign[Assign VM]
    Check -->|No| Error[Return Error]
    Assign --> Notify[Notify Client]
    Notify --> End[Return Hostname]
\`\`\`
```

**Sequence Diagram (Component Interaction)**:

```markdown
\`\`\`mermaid
sequenceDiagram
    participant User
    participant Flask as Flask App
    participant DB as PostgreSQL

    User->>Flask: POST /request_vm
    Flask->>DB: SELECT available VM
    DB-->>Flask: Return VM details
    Flask-->>User: Return hostname
\`\`\`
```

**State Diagram (Lifecycle)**:

```markdown
\`\`\`mermaid
stateDiagram-v2
    [*] --> available: VM Created
    available --> in_use: VM Assigned
    in_use --> available: VM Released
    in_use --> failed: Health Check Failed
\`\`\`
```

**ER Diagram (Database Schema)**:

```markdown
\`\`\`mermaid
erDiagram
    VMS {
        int id PK
        string hostname UK
        string status
    }
\`\`\`
```

#### Mermaid Styling Guidelines

- Use consistent colors for similar components across diagrams
- Keep diagrams focused (max 10-15 nodes)
- Use clear, concise labels with action verbs
- Include HTTP methods for API calls (POST, GET, etc.)
- Test rendering in both light and dark modes

#### Resources

- [Mermaid Documentation](https://mermaid.js.org/)
- [Mermaid Live Editor](https://mermaid.live/) - Test diagrams before adding to docs
- [MkDocs Material Diagrams](https://squidfunk.github.io/mkdocs-material/reference/diagrams/)

#### Alternative: ASCII Art

For very simple diagrams where Mermaid would be overkill, ASCII art is acceptable:

```text
User → Allocator → Client VM
```

## Versioning Documentation

Documentation is versioned using `mike`:

### Version Names

- `latest`: Latest stable release
- `v1.0.0`, `v1.1.0`, etc.: Specific versions
- `dev`: Development/unreleased changes

### Deploy New Version

```bash
# Deploy version 1.0.0 as latest
mike deploy 1.0.0 latest --update-aliases
mike set-default latest

# Deploy dev version
mike deploy dev

# List versions
mike list

# Delete version
mike delete v0.9.0
```

### Version Workflow

1. **On main branch push**: Deploy as `dev`
2. **On release**: Deploy as version number + `latest`

## CI/CD Workflow

Documentation is built and deployed via GitHub Actions (`.github/workflows/docs.yml`).

**Triggers**:
- Push to `main` → Deploy `dev` docs
- Release published → Deploy versioned docs
- Pull request → Build only (no deploy)

**Process**:
1. Checkout code
2. Setup Python
3. Install dependencies
4. Run `mike deploy` (or `mkdocs build`)
5. Push to `gh-pages` branch

## Testing Documentation

### Before Committing

1. **Build locally**:
   ```bash
   mkdocs build --strict
   ```
   `--strict` treats warnings as errors

2. **Serve locally**:
   ```bash
   mkdocs serve
   ```
   Review changes in browser

3. **Check links**:
   - Click through all internal links
   - Verify external links work

4. **Test code examples**:
   - Copy-paste commands and verify they work
   - Test on clean environment if possible

### Validation Checklist

- [ ] All links work (internal and external)
- [ ] Code blocks have language specified
- [ ] Commands tested and work
- [ ] Images display correctly
- [ ] Tables render properly
- [ ] No typos or grammar errors
- [ ] Follows style guide
- [ ] Cross-references added where relevant

## Common Issues

### Link Not Working

**Problem**: Link shows 404

**Solution**:
- Use relative paths: `[Text](other-page.md)` not `[Text](/other-page.md)`
- For sections: `[Text](page.md#section-heading)`
- Check file exists in `docs/` directory

### Code Block Not Highlighting

**Problem**: Code block appears as plain text

**Solution**:
- Specify language: ` ```python ` not just ` ``` `
- Check language name is correct: `bash` not `shell`, `yaml` not `yml`

### Admonition Not Rendering

**Problem**: Admonition shows as plain text

**Solution**:
```markdown
# Correct
!!! note
    Content indented with 4 spaces

# Wrong
!!! note
Content not indented
```

### Table Not Aligning

**Problem**: Table cells misaligned

**Solution**:
- Ensure same number of columns in header and rows
- Align pipes vertically (not required but helps)
- Use markdown table formatter

## Contributing Workflow

1. **Fork repository** (if not a maintainer)

2. **Create branch**:
   ```bash
   git checkout -b docs/improve-configuration-page
   ```

3. **Make changes**:
   - Edit markdown files
   - Add/update examples
   - Test locally with `mkdocs serve`

4. **Commit**:
   ```bash
   git add docs/
   git commit -m "docs: improve configuration examples"
   ```

5. **Push**:
   ```bash
   git push origin docs/improve-configuration-page
   ```

6. **Open Pull Request**:
   - Clear title describing changes
   - Description explaining what and why
   - Screenshots if visual changes

7. **Address feedback**:
   - Respond to review comments
   - Make requested changes
   - Push updates

8. **Merge**:
   - Once approved, PR will be merged
   - Documentation will auto-deploy

## Getting Help

- **Questions**: Open GitHub issue with `documentation` label
- **Suggestions**: Open GitHub discussion
- **Bugs in docs**: Open GitHub issue

## Resources

- [MkDocs Documentation](https://www.mkdocs.org/)
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
- [Python Markdown](https://python-markdown.github.io/)
- [mkdocstrings](https://mkdocstrings.github.io/)

## Quick Reference

```bash
# Install dependencies (uv)
uv sync --extra docs

# Install dependencies (pip)
pip install -e ".[docs]"

# Serve locally
mkdocs serve

# Build documentation
mkdocs build --strict

# Deploy version
mike deploy 1.0.0 latest

# View deployed versions
mike list
```