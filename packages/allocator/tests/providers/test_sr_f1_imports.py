"""SR-F1 full-core import guard — enforces "no AWS SDK imports in the allocator core."

The original AWS-decoupling design (2026-05-01 spec) defined SR-F1 as:
    "The allocator core MUST not import any AWS / cloud SDK directly"

PR B shipped a scoped version (protocol.py + registry.py only) and explicitly
deferred full enforcement to "the provisioning-rewire PR" (PR D5).

After D5, the only files in lablink_allocator_service/ that may import
boto3 / botocore / aws_utils / terraform_utils are the AWS adapter layer:
    - providers/aws.py (the AWS provider itself)
    - providers/connectivity/allocator_proxied.py (AWS-specific connectivity)
    - utils/aws_utils.py (the AWS adapter — boto3 wrapper)
    - utils/terraform_utils.py (the terraform adapter)

Any other file importing those modules is an SR-F1 violation and means the
AWS surface has leaked back into the core. The fix is to push the call
behind the provider seam (provider.<method>(...) or a new method on
ComputeProvider), not to extend the allowlist below.
"""
import ast
import pathlib

import lablink_allocator_service as pkg

_PKG_ROOT = pathlib.Path(pkg.__file__).parent
_FORBIDDEN = ("boto3", "botocore", "aws_utils", "terraform_utils")

# Files permitted to import AWS modules. Every entry is a debt — prefer
# pushing AWS calls behind the provider seam over adding to this list.
_ALLOWED_PATHS = frozenset({
    "providers/aws.py",
    "providers/connectivity/allocator_proxied.py",
    "utils/aws_utils.py",
    "utils/terraform_utils.py",
})


def _direct_imports(pyfile: pathlib.Path) -> set[str]:
    """Return the set of module names directly imported by `pyfile`.

    Inspects only the AST of each file's own import statements. Does NOT
    follow the transitive path — this is a SHALLOW direct-import check,
    which catches all real SR-F1 violations because any AWS call in core
    code requires a direct import of the AWS module (Python has no
    "transitive import" semantics for symbol resolution at runtime).
    """
    tree = ast.parse(pyfile.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _is_aws_import(name: str) -> bool:
    """True if the imported module name contains any forbidden token."""
    return any(forbidden in name for forbidden in _FORBIDDEN)


def test_no_aws_imports_in_core():
    """Every .py under lablink_allocator_service/ outside the AWS adapter
    layer must NOT directly import boto3 / botocore / aws_utils / terraform_utils.
    """
    leaks: list[tuple[str, list[str]]] = []
    for pyfile in _PKG_ROOT.rglob("*.py"):
        rel = pyfile.relative_to(_PKG_ROOT).as_posix()
        if rel in _ALLOWED_PATHS:
            continue
        imported = _direct_imports(pyfile)
        bad = sorted(n for n in imported if _is_aws_import(n))
        if bad:
            leaks.append((rel, bad))
    assert not leaks, (
        "SR-F1 violation: files outside the AWS adapter import AWS modules:\n"
        + "\n".join(f"  {f}: {bad}" for f, bad in leaks)
        + "\n\nFix by pushing the AWS call behind the provider seam, NOT by "
          "adding to the _ALLOWED_PATHS allowlist."
    )


def test_protocol_and_registry_are_aws_free():
    """Original PR-B scope — kept as a fast-fail sentinel.

    The two core-facing modules MUST never pull AWS. If this test fails
    but test_no_aws_imports_in_core passes (impossible, but) the
    error message is more specific.
    """
    for mod in ("providers/protocol.py", "providers/registry.py"):
        imported = _direct_imports(_PKG_ROOT / mod)
        leaked = sorted(n for n in imported if _is_aws_import(n))
        assert not leaked, f"{mod} leaks AWS imports: {leaked}"
