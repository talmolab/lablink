"""Generate the changelog from git tags and releases."""

import subprocess
from pathlib import Path
import mkdocs_gen_files

def get_git_tags():
    """Get git tags sorted by date."""
    try:
        result = subprocess.run(
            ["git", "tag", "-l", "--sort=-creatordate"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except subprocess.CalledProcessError:
        return []

def get_commits_since_tag(tag):
    """Get commits since a specific tag."""
    try:
        result = subprocess.run(
            ["git", "log", f"{tag}..HEAD", "--oneline", "--no-merges"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except subprocess.CalledProcessError:
        return []

def get_commits_between_tags(tag1, tag2):
    """Get commits between two tags."""
    try:
        result = subprocess.run(
            ["git", "log", f"{tag2}..{tag1}", "--oneline", "--no-merges"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except subprocess.CalledProcessError:
        return []

# Generate changelog
with mkdocs_gen_files.open("changelog.md", "w") as changelog:
    changelog.write("# Changelog\n\n")
    changelog.write("All notable changes to this project will be documented in this page.\n\n")

    tags = get_git_tags()

    if not tags or tags == ['']:
        changelog.write("## Unreleased\n\n")
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "--no-merges", "-20"],
                capture_output=True,
                text=True,
                check=True
            )
            commits = result.stdout.strip().split("\n") if result.stdout.strip() else []
            if commits and commits != ['']:
                for commit in commits:
                    if commit:
                        changelog.write(f"- {commit}\n")
            else:
                changelog.write("No commits yet.\n")
        except subprocess.CalledProcessError:
            changelog.write("Unable to retrieve commit history.\n")
    else:
        # Unreleased changes
        unreleased = get_commits_since_tag(tags[0])
        if unreleased and unreleased != ['']:
            changelog.write("## Unreleased\n\n")
            for commit in unreleased:
                if commit:
                    changelog.write(f"- {commit}\n")
            changelog.write("\n")

        # Released versions
        for i, tag in enumerate(tags):
            if not tag:
                continue
            changelog.write(f"## [{tag}](https://github.com/talmolab/lablink/releases/tag/{tag})\n\n")

            if i < len(tags) - 1:
                commits = get_commits_between_tags(tag, tags[i + 1])
            else:
                # First tag, get all commits up to this tag
                try:
                    result = subprocess.run(
                        ["git", "log", tag, "--oneline", "--no-merges"],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    commits = result.stdout.strip().split("\n")[:10] if result.stdout.strip() else []
                except subprocess.CalledProcessError:
                    commits = []

            if commits and commits != ['']:
                for commit in commits:
                    if commit:
                        changelog.write(f"- {commit}\n")
            else:
                changelog.write("Initial release.\n")

            changelog.write("\n")

    changelog.write("\n---\n\n")
    changelog.write("For more details, see the [GitHub Releases page](https://github.com/talmolab/lablink/releases).\n")