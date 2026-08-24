"""Facts about a manual (compose) deployment — the single owner.

``provider: manual`` runs the allocator as a local docker-compose stack
with BYO clients. Every fact about that stack — where its rendered
workdir lives, the base URL the CLI reaches it on, where its public URL
and admin credentials are stashed, how its registered clients are listed
— is derived here and nowhere else. Before this module existed the same
facts were re-derived independently across status, logs, cleanup,
deploy_compose, and utils, and two of the copies had drifted.

Leaf module: imports config and api only, never command modules —
command modules import *it*, so anything from ``lablink_cli.commands``
here closes an import cycle.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lablink_cli.api import USER_AGENT
from lablink_cli.config.schema import Config, resolve_from_saved_config

DEFAULT_COMPOSE_DIR = Path.home() / ".lablink" / "compose"
DEFAULT_HTTP_PORT = "80"

# Name of the file carrying the allocator's real public URL, staged next to
# config.yaml and bind-mounted to /config/<name>. Must stay in sync with
# config_helpers.CANONICAL_URL_FILENAME in the allocator package — duplicated
# rather than imported because each package's CI job installs only its own
# dependencies, so a cross-package import would fail there. Guarded by
# test_deploy_compose.py::TestCanonicalUrlFile::test_filename_matches_allocator.
CANONICAL_URL_FILENAME = "allocator-url"


def workdir(cfg: Config, root: Path | None = None) -> Path:
    """Path to the rendered compose working directory for this deployment.

    `root` overrides `DEFAULT_COMPOSE_DIR` (used by tests via `workdir_root`).
    """
    name = cfg.deployment_name or "lablink"
    return (root or DEFAULT_COMPOSE_DIR) / name


def base_url(cfg: Config) -> str:
    """The allocator base URL for a manual deployment.

    Always localhost: both compose templates publish ``${HTTP_PORT}:5000``
    on the host, and the CLI's manual paths already assume they run on
    that host (`status` and `logs` shell into the local container). Plain
    http — the compose stack has no TLS terminator (Caddy is part of the
    AWS infrastructure, not the container), which is why deploy only
    accepts ``ssl: none`` for manual.
    """
    return f"http://localhost:{DEFAULT_HTTP_PORT}"


def public_url(workdir: Path) -> str | None:
    """The participant-facing URL `lablink deploy` published for this stack.

    Read from the canonical-URL file staged in the deployment dir (the same
    file bind-mounted into the allocator, written from `tailscale funnel
    status`). Empty on every deployment that isn't Funnel-exposed, in which
    case there is no public URL to show and this returns None.
    """
    try:
        candidate = (workdir / CANONICAL_URL_FILENAME).read_text().strip()
    except OSError:
        return None
    return candidate if candidate.startswith(("http://", "https://")) else None


# Marker file written into the workdir by `lablink deploy --render-only`:
# its presence (containing exactly "external") means the allocator runs as a
# workload on an external container platform (Run:AI, Kubernetes, ...) — no
# local container, and the platform owns the lifecycle. Absent or holding
# anything else means today's compose-managed semantics, so every workdir
# predating the marker behaves exactly as before.
RUNTIME_FILENAME = "runtime"


def deployment_runtime(workdir: Path) -> str:
    """How this deployment's allocator lifecycle is managed.

    Returns ``"external"`` when the workdir carries the marker written by
    ``lablink deploy --render-only``, else ``"compose"``.
    """
    try:
        if (workdir / RUNTIME_FILENAME).read_text().strip() == "external":
            return "external"
    except (OSError, UnicodeDecodeError):
        pass
    return "compose"


def resolved_base_url(cfg: Config, workdir: Path) -> str | None:
    """The allocator base URL, honoring the runtime marker.

    Compose-managed deployments are reached on localhost (`base_url`);
    external-runtime deployments have no local container, so the only
    address is the recorded public URL — None when the workdir has none
    (deploy refuses to render such a bundle, but the file can go missing).
    """
    if deployment_runtime(workdir) == "external":
        return public_url(workdir)
    return base_url(cfg)


def admin_credentials(cfg: Config, workdir: Path) -> tuple[str, str] | None:
    """Find admin user/password for the manual compose stack.

    Tries cfg first, then the workdir's rendered config.yaml (which
    deploy_compose.render_compose_dir always writes with the resolved
    credentials) — the same two sources ``resolve_admin_credentials``
    consults for a manual config, minus its interactive prompt: callers
    here print their own guidance instead, so this returns None.
    """
    user = getattr(cfg.app, "admin_user", "") or ""
    pw = getattr(cfg.app, "admin_password", "") or ""
    if user and pw and user != "MISSING" and pw != "MISSING":
        return user, pw

    return resolve_from_saved_config(workdir / "config.yaml")


def registered_clients(
    cfg: Config, admin_user: str, admin_password: str, base: str | None = None
) -> tuple[list[dict] | None, str]:
    """GET /api/v1/clients with admin Basic auth.

    Returns (clients, error_message). On success, error_message is "".
    On failure, clients is None. `base` overrides the localhost base URL —
    external-runtime deployments pass their recorded public URL.
    """
    url = f"{(base or base_url(cfg)).rstrip('/')}/api/v1/clients"
    creds = f"{admin_user}:{admin_password}".encode()
    header = "Basic " + base64.b64encode(creds).decode()
    req = Request(
        url,
        method="GET",
        # USER_AGENT is load-bearing: Cloudflare-proxied allocators 403
        # urllib's default agent (see api.py).
        headers={"Authorization": header, "User-Agent": USER_AGENT},
    )
    try:
        resp = urlopen(req, timeout=10)  # noqa: S310
        body = json.loads(resp.read().decode())
        return body.get("clients", []) or [], ""
    except HTTPError as e:
        if e.code == 401:
            # A bare "HTTP 401" reads like an allocator fault. It's the
            # admin credentials, and they live in one of two files.
            return None, (
                f"the allocator rejected admin user '{admin_user}' "
                "(HTTP 401). Check app.admin_user / app.admin_password "
                "in ~/.lablink/config.yaml or in the rendered "
                "~/.lablink/compose/<deployment>/config.yaml — a "
                "redeploy can change them."
            )
        return None, f"HTTP {e.code} from {url}"
    except URLError as e:
        return None, f"{url} → {e.reason}"
    except Exception as e:
        return None, f"{url} → {e}"
