"""SR-F1 scoped import guard — DIRECT-IMPORT-ONLY; NOT full SR-F1 enforcement.

Scope: ONLY `providers/protocol.py` and `providers/registry.py` are guarded.
`providers/aws.py` is intentionally excluded (it legitimately uses boto3/terraform utils).

Limitation: this guard inspects only the AST of each file's *own* import statements.
It deliberately does NOT follow the transitive path
`protocol.py → client_session → utils.aws_utils`
(`client_session.py` imports `aws_utils` today, which is fine — the seam
between core abstractions and AWS lives at the protocol/registry boundary, not deeper).

The full import-graph SR-F1 test is deferred to the provisioning-rewire PR
where SR-F1 is actually achieved end-to-end.
"""

import ast
import pathlib

import lablink_allocator_service.providers as providers_pkg

_PKG_DIR = pathlib.Path(providers_pkg.__file__).parent
_FORBIDDEN = ("boto3", "botocore", "aws_utils", "terraform_utils")


def _imports(pyfile: pathlib.Path) -> set[str]:
    tree = ast.parse(pyfile.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_protocol_and_registry_are_aws_free():
    # These two modules are the core-facing seam — they must never pull AWS.
    for mod in ("protocol.py", "registry.py"):
        imported = _imports(_PKG_DIR / mod)
        leaked = [
            n for n in imported
            if any(f in n for f in _FORBIDDEN)
        ]
        assert not leaked, f"{mod} leaks AWS imports: {leaked}"
