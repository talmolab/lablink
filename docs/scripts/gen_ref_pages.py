"""Generate the code reference pages and navigation."""

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import mkdocs_gen_files


@dataclass
class PackageInfo:
    """One Python package to auto-document.

    - ``path``: package source root to walk for .py files.
    - ``import_name``: module used to check whether the package is installed.
    """

    path: Path
    import_name: str


root = Path(__file__).parent.parent.parent

packages: dict[str, PackageInfo] = {
    "allocator": PackageInfo(
        path=root / "packages" / "allocator" / "src",
        import_name="lablink_allocator_service",
    ),
    "client": PackageInfo(
        path=root / "packages" / "client" / "src",
        import_name="lablink_client_service",
    ),
}

# Check installation per-package so a missing one doesn't block the others.
installed = {
    name: importlib.util.find_spec(info.import_name) is not None
    for name, info in packages.items()
}
any_installed = any(installed.values())

if not any_installed:
    print(
        "⚠️  LabLink packages not installed - skipping API reference generation",
        file=sys.stderr,
    )
    print("   For full docs with API reference, install packages:", file=sys.stderr)
    print("   uv pip install -e packages/allocator", file=sys.stderr)
    print("   uv pip install -e packages/client", file=sys.stderr)

for pkg_name, pkg_info in packages.items():
    if not installed[pkg_name]:
        continue

    package_root = pkg_info.path
    if not package_root.exists():
        continue

    nav = mkdocs_gen_files.Nav()

    for path in sorted(package_root.rglob("*.py")):
        # Skip test files and generated files.
        if "test" in path.parts or "conftest" in path.name:
            continue

        module_path = path.relative_to(package_root).with_suffix("")
        doc_path = path.relative_to(package_root).with_suffix(".md")
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
            fd.write("    options:\n")
            fd.write("      show_if_no_docstring: true\n")

        mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(root))

    with mkdocs_gen_files.open(f"reference/{pkg_name}/SUMMARY.md", "w") as nav_file:
        nav_file.writelines(nav.build_literate_nav())


# Build the main reference landing page.
with mkdocs_gen_files.open("reference/index.md", "w") as index:
    index.write("# Reference\n\n")

    index.write("## API Reference\n\n")
    index.write("Auto-generated API documentation from Python docstrings.\n\n")

    if installed["allocator"]:
        index.write("### Allocator Service\n\n")
        index.write("API documentation for the LabLink allocator service.\n\n")
        index.write("[Browse Allocator API →](allocator/SUMMARY.md)\n\n")

    if installed["client"]:
        index.write("### Client Service\n\n")
        index.write("API documentation for the LabLink client service.\n\n")
        index.write("[Browse Client API →](client/SUMMARY.md)\n\n")

    if not any_installed:
        index.write(
            "API reference generation requires LabLink packages to be installed.\n\n"
        )
        index.write("To generate full API documentation:\n\n")
        index.write("```bash\n")
        index.write("uv pip install -e packages/allocator\n")
        index.write("uv pip install -e packages/client\n")
        index.write("mkdocs build\n")
        index.write("```\n\n")

    index.write("## CLI Reference\n\n")
    index.write("Command-line reference for the `lablink` CLI.\n\n")
    index.write("[Browse CLI Reference →](cli.md)\n\n")
