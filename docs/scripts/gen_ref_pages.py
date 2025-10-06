"""Generate the code reference pages and navigation."""

from pathlib import Path
import mkdocs_gen_files
import sys

root = Path(__file__).parent.parent.parent

# Define the Python packages to document
packages = {
    "allocator": {
        "path": root / "packages" / "allocator" / "src",
        "module_name": "lablink_allocator",
    },
    "client": {
        "path": root / "packages" / "client" / "src",
        "module_name": "lablink_client",
    },
}

# Check if packages are installed (for full API generation)
try:
    import lablink_allocator  # noqa: F401
    import lablink_client  # noqa: F401
    packages_installed = True
except ImportError:
    packages_installed = False
    print("⚠️  LabLink packages not installed - skipping API reference generation", file=sys.stderr)
    print("   For full docs with API reference, install packages:", file=sys.stderr)
    print("   uv pip install -e packages/allocator", file=sys.stderr)
    print("   uv pip install -e packages/client", file=sys.stderr)

if packages_installed:
    for pkg_name, pkg_info in packages.items():
        package_root = pkg_info["path"]

        if not package_root.exists():
            continue

        # Create separate navigation for each package
        nav = mkdocs_gen_files.Nav()

        for path in sorted(package_root.rglob("*.py")):
            # Skip test files and generated files
            if "test" in path.parts or "conftest" in path.name:
                continue

            module_path = path.relative_to(package_root).with_suffix("")
            doc_path = path.relative_to(package_root).with_suffix(".md")
            # Organize under package-specific subdirectory
            full_doc_path = Path("reference", pkg_name, doc_path)

            parts = tuple(module_path.parts)

            if parts[-1] == "__init__":
                parts = parts[:-1]
                if not parts:
                    continue
                doc_path = doc_path.with_name("index.md")
                full_doc_path = full_doc_path.with_name("index.md")
            elif parts[-1] == "__main__":
                continue

            nav[parts] = doc_path.as_posix()

            with mkdocs_gen_files.open(full_doc_path, "w") as fd:
                ident = ".".join(parts)
                fd.write(f"# {ident}\n\n")
                fd.write(f"::: {ident}\n")
                fd.write(f"    options:\n")
                fd.write(f"      show_if_no_docstring: true\n")

            mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(root))

        # Write navigation file for this package
        with mkdocs_gen_files.open(f"reference/{pkg_name}/SUMMARY.md", "w") as nav_file:
            nav_file.writelines(nav.build_literate_nav())

    # Create main reference index
    with mkdocs_gen_files.open("reference/index.md", "w") as index:
        index.write("# API Reference\n\n")
        index.write("Auto-generated API documentation from Python docstrings.\n\n")
        index.write("## Allocator Service\n\n")
        index.write("API documentation for the LabLink allocator service.\n\n")
        index.write("[Browse Allocator API →](allocator/SUMMARY.md)\n\n")
        index.write("## Client Service\n\n")
        index.write("API documentation for the LabLink client service.\n\n")
        index.write("[Browse Client API →](client/SUMMARY.md)\n\n")
else:
    # Create placeholder when packages aren't installed
    with mkdocs_gen_files.open("reference/index.md", "w") as index:
        index.write("# API Reference\n\n")
        index.write("API reference generation requires LabLink packages to be installed.\n\n")
        index.write("To generate full API documentation:\n\n")
        index.write("```bash\n")
        index.write("uv pip install -e packages/allocator\n")
        index.write("uv pip install -e packages/client\n")
        index.write("mkdocs build\n")
        index.write("```\n")