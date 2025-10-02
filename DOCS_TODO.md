# Documentation Style Updates - Progress Report

Based on feedback to match [SLEAP documentation style](https://docs.sleap.ai/latest/installation/).

## ✅ Completed

### Navigation Structure
- ✅ Reorganized navigation to be more concise:
  - "Getting Started" → "Installation"
  - "User Guides" → "Guides"
  - "AWS Setup" → "AWS"
  - "Contributing" → "Development"
- ✅ Consolidated changelog pages under Development section

### Title Capitalization
- ✅ Changed all titles from Title Case to sentence case:
  - ~~"Adapting for Your Software"~~ → "Adapting for your software"
  - ~~"SSH Access"~~ → "SSH access"
  - ~~"Database Management"~~ → "Database"
  - ~~"API Reference"~~ → "API reference"
  - And many more...

### Versioning
- ✅ Mike (version selector) already configured
- ✅ Workflow supports `dev`, `test`, and `prod` versions
- ✅ Version selector enabled in mkdocs.yml

### Infrastructure
- ✅ Left sidebar navigation with tabs
- ✅ Version dropdown ready (will populate when versions are deployed)
- ✅ Material theme with proper colors

## 🔨 Still Needs Work

### Content Tone & Wordiness

Many documentation pages currently have:
- ❌ Too much generic, verbose wording
- ❌ Over-explanation of obvious concepts
- ❌ Marketing-style language instead of technical precision

**Examples that need fixing:**

#### index.md (Home)
Current has flowery introduction. Should be:
- Brief 1-2 sentence description
- Quick links to installation and key features
- No marketing speak

#### installation.md
Currently verbose. Should be:
- Direct installation commands
- Platform-specific tabs (like SLEAP)
- Minimal explanation

#### architecture.md
Currently very wordy. Should be:
- Concise system description
- Clean diagram
- Brief component descriptions

#### configuration.md
Currently has too much prose. Should be:
- Configuration file examples
- Table of options with brief descriptions
- Link to API reference for details

### Specific Pages to Rewrite

Priority order (most important first):

1. **index.md** - Too marketing-focused, needs to be technical and brief
2. **installation.md** - Needs platform-specific tabs, shorter explanations
3. **quickstart.md** - Should be step-by-step commands with minimal text
4. **architecture.md** - Too wordy, needs concise technical description
5. **configuration.md** - Should focus on examples, not explanations
6. **adapting.md** - Too verbose, needs concrete examples
7. **deployment.md** - Over-explained, needs direct instructions
8. **contributing.md** - Already good but could be more concise
9. **All other guides** - Review for wordiness

### Style Guidelines for Rewriting

Based on SLEAP docs analysis:

**Do:**
- Use sentence case for all titles
- Keep explanations brief and technical
- Use code examples heavily
- Use tabs for platform-specific content
- Use tables for options/parameters
- Link to API reference instead of explaining in prose

**Don't:**
- Use marketing language ("powerful", "robust", "cutting-edge")
- Over-explain obvious things
- Use title case (~~This Is Wrong~~)
- Write long paragraphs when a list or table would work
- Repeat information that's in other sections

**Tone Examples:**

❌ **Too wordy:**
> LabLink provides a powerful and flexible system for dynamically allocating and managing cloud-based virtual machines. The system is designed to be highly scalable and can handle a large number of concurrent users while maintaining excellent performance and reliability.

✅ **Succinct:**
> LabLink allocates VMs for computational research. The system handles concurrent users and scales automatically.

❌ **Too generic:**
> Getting started with LabLink is easy! First, you'll need to ensure you have all the necessary prerequisites installed on your system.

✅ **Direct:**
> Prerequisites:
> - Python 3.9+
> - Docker
> - AWS account

### Version Setup

To enable `dev` version in the dropdown:

```bash
# Deploy current docs as dev version
uv run mike deploy dev
uv run mike set-default latest

# Deploy from different branches
# main → latest
# test → test
# dev → dev
```

The workflow already handles this automatically when pushing to the `dev` branch.

## 📋 Recommended Action Plan

1. **Phase 1: Critical pages** (do first)
   - Rewrite index.md to be brief and technical
   - Rewrite installation.md with tabs and minimal prose
   - Rewrite quickstart.md as step-by-step commands

2. **Phase 2: Guide pages** (do second)
   - Streamline architecture.md
   - Make configuration.md example-focused
   - Tighten up deployment.md

3. **Phase 3: Polish** (do last)
   - Review all remaining pages for wordiness
   - Ensure consistent tone throughout
   - Add more code examples, fewer explanations

## 🔍 Review Checklist

When reviewing each page, ask:
- [ ] Is every word necessary?
- [ ] Could this paragraph be a list or table?
- [ ] Are we explaining instead of showing?
- [ ] Is the title in sentence case?
- [ ] Would a SLEAP docs reader find this too wordy?

---

**Next Steps:** Would you like me to start rewriting the critical pages (index, installation, quickstart) to match the SLEAP style?
