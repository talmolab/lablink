"""Generate per-package changelogs from git tags and releases."""

import subprocess
from pathlib import Path
import mkdocs_gen_files
import re


def get_package_tags(prefix):
    """Get tags for a specific package, sorted by date."""
    try:
        result = subprocess.run(
            ["git", "tag", "-l", f"{prefix}*", "--sort=-creatordate"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except subprocess.CalledProcessError:
        return []


def extract_version(tag, prefix):
    """Extract version from tag (e.g., lablink-allocator-service_v0.3.0 -> 0.3.0)."""
    return tag.replace(prefix, "")


def get_commits_between_tags(tag1, tag2, path_filter=None):
    """Get commits between two tags, optionally filtered by path."""
    if tag2:
        cmd = ["git", "log", f"{tag2}..{tag1}", "--oneline", "--no-merges"]
    else:
        # First tag, get all commits up to this tag
        cmd = ["git", "log", tag1, "--oneline", "--no-merges"]

    if path_filter:
        cmd.extend(["--", path_filter])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        commits = result.stdout.strip().split("\n") if result.stdout.strip() else []
        # Limit to first 50 commits for initial releases
        if not tag2:
            commits = commits[:50]
        return commits
    except subprocess.CalledProcessError:
        return []


def categorize_commit(commit_msg):
    """Categorize commit by conventional commit prefix."""
    patterns = {
        "Features": r"^[a-f0-9]+ feat(\(.*?\))?:",
        "Bug Fixes": r"^[a-f0-9]+ fix(\(.*?\))?:",
        "Documentation": r"^[a-f0-9]+ docs(\(.*?\))?:",
        "Performance": r"^[a-f0-9]+ perf(\(.*?\))?:",
        "Refactoring": r"^[a-f0-9]+ refactor(\(.*?\))?:",
        "Tests": r"^[a-f0-9]+ test(\(.*?\))?:",
        "Chores": r"^[a-f0-9]+ chore(\(.*?\))?:",
        "Build": r"^[a-f0-9]+ build(\(.*?\))?:",
        "CI": r"^[a-f0-9]+ ci(\(.*?\))?:",
    }

    for category, pattern in patterns.items():
        if re.match(pattern, commit_msg):
            return category
    return "Other Changes"


def generate_package_changelog(package_name, display_name, tag_prefix, path_filter):
    """Generate changelog for a specific package."""
    tags = get_package_tags(tag_prefix)

    with mkdocs_gen_files.open(f"changelog-{display_name}.md", "w") as changelog:
        changelog.write(f"# {package_name} Changelog\n\n")
        changelog.write(f"All notable changes to **{package_name}** will be documented here.\n\n")
        changelog.write(f"The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).\n\n")

        if not tags or tags == ['']:
            changelog.write("## Unreleased\n\n")
            changelog.write("No releases yet.\n\n")
            # Show recent commits from this package's directory
            recent_commits = get_commits_between_tags("HEAD", "", path_filter)
            if recent_commits and recent_commits != ['']:
                recent_commits = [c for c in recent_commits if c][:20]
                if recent_commits:
                    changelog.write("### Recent commits\n\n")
                    for commit in recent_commits:
                        msg = re.sub(r'^[a-f0-9]+ ', '', commit)
                        changelog.write(f"- {msg}\n")
            return

        # Unreleased changes
        unreleased = get_commits_between_tags("HEAD", tags[0], path_filter)
        if unreleased and unreleased != ['']:
            unreleased = [c for c in unreleased if c]
            if unreleased:
                changelog.write("## Unreleased\n\n")
                categorized = {}
                for commit in unreleased:
                    category = categorize_commit(commit)
                    categorized.setdefault(category, []).append(commit)

                for category in sorted(categorized.keys()):
                    changelog.write(f"### {category}\n\n")
                    for commit in categorized[category]:
                        msg = re.sub(r'^[a-f0-9]+ ', '', commit)
                        changelog.write(f"- {msg}\n")
                    changelog.write("\n")

        # Released versions
        for i, tag in enumerate(tags):
            if not tag:
                continue

            version = extract_version(tag, tag_prefix)
            changelog.write(f"## [{version}](https://github.com/talmolab/lablink/releases/tag/{tag})\n\n")

            # Get commits between this tag and the previous one
            if i < len(tags) - 1:
                commits = get_commits_between_tags(tag, tags[i + 1], path_filter)
            else:
                # First tag - get all commits up to this tag
                commits = get_commits_between_tags(tag, "", path_filter)

            if commits and commits != ['']:
                commits = [c for c in commits if c]
                if commits:
                    categorized = {}
                    for commit in commits:
                        category = categorize_commit(commit)
                        categorized.setdefault(category, []).append(commit)

                    for category in sorted(categorized.keys()):
                        changelog.write(f"### {category}\n\n")
                        for commit in categorized[category]:
                            msg = re.sub(r'^[a-f0-9]+ ', '', commit)
                            changelog.write(f"- {msg}\n")
                        changelog.write("\n")
                else:
                    changelog.write("Initial release.\n\n")
            else:
                changelog.write("Initial release.\n\n")

        changelog.write("\n---\n\n")
        changelog.write(f"For more details, see the [GitHub Releases page](https://github.com/talmolab/lablink/releases?q={package_name}).\n")


# Generate changelogs for each package
generate_package_changelog(
    "lablink-allocator-service",
    "allocator",
    "lablink-allocator-service_v",
    "packages/allocator"
)

generate_package_changelog(
    "lablink-client-service",
    "client",
    "lablink-client-service_v",
    "packages/client"
)

# Generate unified changelog index
with mkdocs_gen_files.open("changelog.md", "w") as changelog:
    changelog.write("# Changelog\n\n")
    changelog.write("LabLink consists of two independently versioned packages:\n\n")
    changelog.write("## Package Changelogs\n\n")
    changelog.write("- **[lablink-allocator-service](changelog-allocator.md)** - VM Allocator Service\n")
    changelog.write("- **[lablink-client-service](changelog-client.md)** - Client Service\n\n")
    changelog.write("---\n\n")
    changelog.write("For release notes and downloads, see the [GitHub Releases page](https://github.com/talmolab/lablink/releases).\n")
