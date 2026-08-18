"""Generate docs/api-endpoints.md from the allocator's route modules.

The page is assembled at build time by statically parsing (``ast``, no
imports) every module in ``packages/allocator/src/lablink_allocator_service/
routes/``. Each ``@bp.route`` handler becomes one endpoint entry:

- method + path come from the decorator,
- the auth gate is inferred from the other decorators
  (``@auth.login_required`` -> HTTP Basic, ``@require_client_secret`` ->
  client secret, neither -> none), overridable by an ``Auth:`` line in the
  handler's docstring (needed where the check is inline, e.g. the register
  token),
- the body is the handler's docstring, rendered verbatim as Markdown.

A route without a docstring FAILS the docs build on purpose: the docstring
is the documentation, so a new endpoint cannot ship undocumented.

Keep cross-page links (``[...](database.md#...)``) in the section intros
below, not in docstrings — the same docstrings are rendered by mkdocstrings
under ``reference/``, where relative links would break.
"""

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

import mkdocs_gen_files

ROUTES_DIR = (
    Path(__file__).parent.parent.parent
    / "packages"
    / "allocator"
    / "src"
    / "lablink_allocator_service"
    / "routes"
)

OUT_PATH = "api-endpoints.md"

AUTH_BY_DECORATOR = {
    "login_required": "Admin (HTTP Basic)",
    "require_client_secret": "Client secret (Bearer)",
}

PAGE_INTRO = """\
# API Endpoints

This page is generated at build time from the route handlers in
`packages/allocator/src/lablink_allocator_service/routes/` — the docstring on
each handler is the documentation you read here. To change it, edit the
docstring.

## Authentication

LabLink uses four gates. All bearer credentials go in
`Authorization: Bearer <token>`.

| Gate | Credential | Guards |
|---|---|---|
| **HTTP Basic** | `app.admin_user` / `app.admin_password` from `config.yaml` | `/admin/*` pages and the operator JSON APIs |
| **Client secret** | A per-client secret minted when that client registers, stored as an argon2 hash | client → allocator telemetry (`/api/heartbeat`, `/api/vm-status`, …) |
| **Register token** | One deployment-wide bootstrap token, also stored hashed | `POST /api/v1/clients/register` only |
| **Signed cookie** | `lablink_session`, minted by `/api/request_vm` | `GET /desktop` |

A handful of endpoints are deliberately unauthenticated: `/` and
`/api/request_vm` (participant-facing), `/api/health` and
`/api/unassigned_vms_count` (health/monitoring), and `/internal/*` (reachable
only from the allocator's own nginx, never exposed publicly).

Secrets are per-client, so a leaked one compromises a single machine. The
register token is the only deployment-wide credential, and it can do nothing
but register.
"""


@dataclass
class Section:
    """One page section: a routes module, in the order listed in SECTIONS."""

    title: str
    intro: str = ""


# Page order. A routes module missing from this dict still gets a section
# (title-cased module name, no intro, appended at the end) so a new module
# can never silently vanish from the docs.
SECTIONS: dict[str, Section] = {
    "public.py": Section(
        title="Participant Endpoints",
        intro=(
            "What a workshop participant touches: the landing page and the "
            "seat-claim endpoint. The participant supplies nothing but an "
            "email address."
        ),
    ),
    "desktop.py": Section(
        title="Participant Desktop",
    ),
    "internal_proxy_auth.py": Section(
        title="Internal Proxy Authorization",
        intro=(
            "`auth_request` subrequest targets for the allocator's own "
            "nginx. Never routed publicly."
        ),
    ),
    "health.py": Section(
        title="Health",
    ),
    "vm_telemetry.py": Section(
        title="Client VM Telemetry",
        intro=(
            "Client VMs *report upward* through these; they are never told "
            "about an assignment. The allocator pushes assignments the other "
            "way, by calling the client's local agent (see "
            "`POST /api/request_vm` and [Database](database.md#triggers)). "
            "All telemetry writes require that client's own secret as a "
            "bearer token — see [Authentication](#authentication)."
        ),
    ),
    "provisioning.py": Section(
        title="Provisioning and Operations",
        intro=(
            "Creating and destroying the VM pool. Long-running OpenTofu work "
            "runs asynchronously: launch/destroy enqueue a job in the "
            "[`operations` table](database.md#operations-table) and the "
            "operations endpoints expose its progress."
        ),
    ),
    "registration.py": Section(
        title="Client Registration API",
        intro=(
            "Used by bring-your-own (BYO) client machines to enrol "
            "themselves under the `manual` provider. AWS-provisioned clients "
            "also register, with credentials supplied by OpenTofu.\n\n"
            "Registration is what the CLI's `lablink client register` drives "
            "— see [Bring-Your-Own Clients](cli/byo-clients.md#step-4-register-each-box) "
            "for the operator-facing walkthrough, and "
            "[Configuration](configuration.md#manual-provider-options-manual) "
            "for the `manual.*` settings it depends on."
        ),
    ),
    "schedules.py": Section(
        title="Scheduled Destruction API",
        intro=(
            "Lets an operator schedule tear-down ahead of time — useful for "
            "capping the cost of a workshop deployment. Schedules are "
            "persisted in the "
            "[`scheduled_destructions` table](database.md#scheduled_destructions-table)."
        ),
    ),
    "metrics.py": Section(
        title="Session Metrics API",
        intro="Populated only when `monitoring.enabled` is true.",
    ),
    "allocator_logs.py": Section(
        title="Allocator Logs",
    ),
    "admin_sessions.py": Section(
        title="Admin Session Actions",
        intro=(
            "Per-VM operator actions on the **Instances** page: preview a "
            "desktop, join a participant's session, release a seat, clear a "
            "health lockout."
        ),
    ),
    "admin_pages.py": Section(
        title="Admin Pages",
        intro=(
            "Operator HTML pages, all behind HTTP Basic Auth. They are "
            "walked through in the [Workshop Guide](workshop-guide.md), and "
            "`/admin/byo-onboarding` in "
            "[Bring-Your-Own Clients](cli/byo-clients.md#step-4-register-each-box)."
        ),
    ),
}


@dataclass
class Endpoint:
    routes: list[tuple[str, list[str]]]  # (path, methods)
    auth: str
    doc: str
    lineno: int = 0
    order: int = field(default=0)


def _route_decorators(func: ast.FunctionDef) -> list[tuple[str, list[str]]]:
    """Extract (path, methods) from every @bp.route(...) on a function."""
    routes = []
    for dec in func.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        target = dec.func
        if not (isinstance(target, ast.Attribute) and target.attr == "route"):
            continue
        if not (dec.args and isinstance(dec.args[0], ast.Constant)):
            continue
        path = dec.args[0].value
        methods = ["GET"]
        for kw in dec.keywords:
            if kw.arg == "methods" and isinstance(kw.value, ast.List):
                methods = [
                    elt.value
                    for elt in kw.value.elts
                    if isinstance(elt, ast.Constant)
                ]
        routes.append((path, methods))
    return routes


def _auth_from_decorators(func: ast.FunctionDef) -> str:
    for dec in func.decorator_list:
        name = None
        if isinstance(dec, ast.Attribute):
            name = dec.attr
        elif isinstance(dec, ast.Name):
            name = dec.id
        elif isinstance(dec, ast.Call):
            if isinstance(dec.func, ast.Attribute):
                name = dec.func.attr
            elif isinstance(dec.func, ast.Name):
                name = dec.func.id
        if name in AUTH_BY_DECORATOR:
            return AUTH_BY_DECORATOR[name]
    return "None"


def _split_auth_override(doc: str) -> tuple[str | None, str]:
    """Pull a leading ``Auth: ...`` paragraph line out of the docstring.

    Only a line that starts exactly with ``Auth:`` counts, so prose that
    merely mentions auth is left alone.
    """
    lines = doc.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("Auth:"):
            override = line.strip()[len("Auth:") :].strip()
            rest = lines[:i] + lines[i + 1 :]
            return override, "\n".join(rest)
    return None, doc


def _parse_module(path: Path) -> list[Endpoint]:
    tree = ast.parse(path.read_text(), filename=str(path))
    endpoints = []
    missing = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        routes = _route_decorators(node)
        if not routes:
            continue
        doc = ast.get_docstring(node)
        if not doc:
            missing.append(f"{path.name}:{node.lineno} {node.name}")
            continue
        override, doc = _split_auth_override(doc)
        auth = override or _auth_from_decorators(node)
        endpoints.append(
            Endpoint(routes=routes, auth=auth, doc=doc.strip(), lineno=node.lineno)
        )
    if missing:
        raise RuntimeError(
            "Route handler(s) missing a docstring — the docstring IS the "
            "api-endpoints.md entry, add one:\n  " + "\n  ".join(missing)
        )
    endpoints.sort(key=lambda e: e.lineno)
    return endpoints


def _endpoint_heading(ep: Endpoint) -> str:
    parts = [
        f"`{'|'.join(methods)} {path}`" for path, methods in ep.routes
    ]
    return "### " + ", ".join(parts)


def main() -> None:
    if not ROUTES_DIR.exists():
        print(
            f"⚠️  {ROUTES_DIR} not found - skipping API endpoints generation",
            file=sys.stderr,
        )
        return

    module_files = sorted(
        p.name for p in ROUTES_DIR.glob("*.py") if p.name != "__init__.py"
    )
    ordered = [m for m in SECTIONS if m in module_files]
    ordered += [m for m in module_files if m not in SECTIONS]

    out = [PAGE_INTRO]
    for module in ordered:
        endpoints = _parse_module(ROUTES_DIR / module)
        if not endpoints:
            continue
        section = SECTIONS.get(
            module, Section(title=module.removesuffix(".py").replace("_", " ").title())
        )
        out.append(f"\n## {section.title}\n")
        if section.intro:
            out.append(section.intro + "\n")
        for ep in endpoints:
            out.append(_endpoint_heading(ep) + "\n")
            out.append(f"**Authentication:** {ep.auth}\n")
            out.append(ep.doc + "\n")

    with mkdocs_gen_files.open(OUT_PATH, "w") as fd:
        fd.write("\n".join(out))


main()
