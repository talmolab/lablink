"""Logging is configured by entry points; library modules only getLogger().

Issue #409. ``utils/aws_utils`` used to call ``logging.basicConfig(level=INFO)``
at module scope, and ``validate_config`` called it at module scope too with
``level=WARNING, format="%(message)s"``. Both are reachable by plain import, and
``basicConfig()`` is a no-op once root has a handler — so whichever module the
process imported first silently decided the root level *and* the log format for
everything that followed. main.py imports ``providers.registry`` →
``providers/aws.py`` → ``utils/aws_utils`` near the top, so its own
``basicConfig(level=_log_level, format=...)`` never did anything: the allocator
shipped its logs in Python's default ``LEVEL:name:message`` form, with no
timestamps, and root pinned at INFO.

The visible symptom was #406: after main.py's route handlers were split into
routes/ blueprints, each module logged through ``getLogger(__name__)`` with no
explicit level, inherited the pinned root, and seven ``logger.debug()`` calls
across routes/ went silent in dev/test/ci-test — the environments where you
want them. #406 fixed that by levelling the package logger; #409 removed the
import-time reconfiguration underneath it.

These tests guard both halves: the structural rule (no module-scope
``basicConfig`` in library code) and the resulting behaviour (package logger
carries the configured level, root owns the format, third-party loggers are
not dragged along).
"""

import ast
import json
import logging
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

PACKAGE_ROOT = (
    Path(__file__).resolve().parents[1] / "src" / "lablink_allocator_service"
)

# main.py is the allocator entry point (`lablink-allocator`) and is the one
# module allowed to configure logging at import time rather than from a
# function: it emits the REGISTER_TOKEN line at module scope, and `lablink
# deploy` scrapes that out of the container logs, so it cannot wait for main()
# to be called. validate_config.py is an entry point too, but it has no
# module-scope logging, so it configures from main() like a well-behaved one.
BASIC_CONFIG_AT_IMPORT_ALLOWED = {"main.py"}

# The format main.py installs on root. Kept here rather than imported so a
# change to main.py has to be made deliberately in two places.
EXPECTED_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Every module that logs through the package logger and therefore depends on
# its level. Keep in sync when a blueprint is added.
ROUTE_MODULES = [
    "admin_pages",
    "admin_sessions",
    "health",
    "metrics",
    "provisioning",
    "public",
    "schedules",
    "vm_telemetry",
]


def _import_time_calls(tree: ast.Module):
    """Yield every Call node that executes when the module is imported.

    Descends through module-scope ``if``/``try``/``with``/``for`` bodies and
    class bodies (all of which run at import) but stops at function and lambda
    boundaries (which do not).
    """
    stack: list[ast.AST] = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def _is_basic_config(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr == "basicConfig"
    if isinstance(func, ast.Name):
        return func.id == "basicConfig"
    return False


def test_no_basic_config_at_import_time():
    """The root-cause guard: re-add basicConfig() to any library module in this
    package and this fails, naming the file and line.
    """
    offenders = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path.name in BASIC_CONFIG_AT_IMPORT_ALLOWED:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for call in _import_time_calls(tree):
            if _is_basic_config(call):
                rel = path.relative_to(PACKAGE_ROOT)
                offenders.append(f"{rel}:{call.lineno}")

    assert not offenders, (
        "logging.basicConfig() runs at import time in library module(s): "
        + ", ".join(offenders)
        + ". Library modules must only call getLogger(); move the "
        "configuration into the entry point's main()."
    )


def test_importing_library_modules_leaves_root_logging_untouched():
    """The behavioural half of the guard, in a clean interpreter.

    Has to be a subprocess: pytest installs its own root handler, which would
    make any in-process basicConfig() a no-op and hide the very thing under
    test.
    """
    probe = textwrap.dedent(
        """
        import logging
        import sys

        root = logging.getLogger()
        before = (root.level, len(root.handlers))

        import lablink_allocator_service.utils.aws_utils  # noqa: F401
        import lablink_allocator_service.validate_config  # noqa: F401
        import lablink_allocator_service.providers.aws  # noqa: F401
        import lablink_allocator_service.providers.registry  # noqa: F401

        after = (root.level, len(root.handlers))
        print(f"before={before} after={after}")
        sys.exit(0 if before == after else 1)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "importing library modules mutated root logging state: "
        f"{result.stdout.strip()} {result.stderr.strip()}"
    )


def test_package_logger_carries_configured_level():
    """Guards #406's fix directly: delete the setLevel call in main.py and this
    fails in every environment, not just the ones where _log_level is DEBUG.
    """
    from lablink_allocator_service import main

    pkg = logging.getLogger("lablink_allocator_service")
    assert pkg.level == main._log_level, (
        f"package logger level is {logging.getLevelName(pkg.level)}, expected "
        f"{logging.getLevelName(main._log_level)}. The level must be set on the "
        "package explicitly — root is shared with third-party libraries and is "
        "deliberately held at INFO."
    )


def test_route_module_loggers_emit_at_the_configured_level():
    """The user-visible property: a logger.debug() in any blueprint is
    actually emitted when the deployment is configured for DEBUG.
    """
    from lablink_allocator_service import main

    for mod in ROUTE_MODULES:
        lg = logging.getLogger(f"lablink_allocator_service.routes.{mod}")
        assert lg.getEffectiveLevel() == main._log_level, (
            f"routes.{mod} resolves to "
            f"{logging.getLevelName(lg.getEffectiveLevel())}, expected "
            f"{logging.getLevelName(main._log_level)}"
        )
        assert lg.isEnabledFor(main._log_level), f"routes.{mod} is muted"


def test_main_logger_matches_route_module_loggers():
    """main.py must not carry its own explicit level. An explicit level on
    main alone is what masked the original bug: main kept logging while the
    eleven route modules went quiet, so the divergence was invisible.
    """
    from lablink_allocator_service import main

    assert main.logger.level == logging.NOTSET, (
        "main's logger should inherit from the package logger, not set its "
        "own level — an explicit level here re-creates the asymmetry that "
        "hid the dropped route-module debug logging."
    )
    for mod in ROUTE_MODULES:
        lg = logging.getLogger(f"lablink_allocator_service.routes.{mod}")
        assert lg.getEffectiveLevel() == main.logger.getEffectiveLevel()


def test_allocator_log_format_is_actually_installed(tmp_path):
    """main.py's format must reach the root handler.

    It never did before #409: aws_utils won the basicConfig race with no
    ``format=``, so every allocator log line came out as Python's default
    ``LEVEL:name:message`` with no timestamp. Asserting on the installed
    formatter is the only way to catch that — the level looked right.
    """
    formats = _probe_main_in_subprocess(tmp_path, environment="prod")["formats"]
    assert formats == [EXPECTED_FORMAT], (
        f"root handler formats are {formats}, expected exactly "
        f"[{EXPECTED_FORMAT!r}]"
    )


def test_debug_environments_do_not_drag_third_party_loggers_along(tmp_path):
    """The deliberate two-level split, exercised where it actually differs.

    Every other test here runs against the bundled config, where environment is
    "prod" and _log_level is INFO — so root and the package agree and the split
    is invisible. Under a dev config they diverge: our package goes to DEBUG,
    root stays at INFO so botocore doesn't log every API request and response
    body over the top of the output we came for.

    Collapsing this back to a single ``basicConfig(level=_log_level)`` fails
    here, and only here.
    """
    probed = _probe_main_in_subprocess(tmp_path, environment="dev")

    assert probed["log_level"] == "DEBUG", (
        f"a dev config should resolve to DEBUG, got {probed['log_level']}"
    )
    assert probed["package"] == "DEBUG", (
        "the package logger must carry the configured level, got "
        f"{probed['package']}"
    )
    assert probed["route"] == "DEBUG", (
        f"routes/ blueprints must inherit DEBUG, got {probed['route']}"
    )
    assert probed["root"] == "INFO", (
        f"root must stay at INFO as the third-party noise floor, got "
        f"{probed['root']}"
    )
    for lib in ("botocore", "paramiko", "urllib3"):
        assert probed[lib] == "INFO", (
            f"{lib} resolves to {probed[lib]}; a DEBUG root buries the "
            "allocator's own output"
        )


def _probe_main_in_subprocess(tmp_path, environment: str) -> dict:
    """Import main in a clean interpreter against a config with `environment`.

    Returns the resolved level names plus the root handlers' formats. A
    subprocess is required twice over: main.py configures logging at import
    time (so it must be a first import), and pytest's own root handler would
    otherwise mask the result.
    """
    bundled = (PACKAGE_ROOT / "conf" / "config.yaml").read_text()
    patched, count = re.subn(
        r"(?m)^environment:.*$", f'environment: "{environment}"', bundled
    )
    assert count == 1, (
        "expected exactly one top-level `environment:` line in the bundled "
        f"config, found {count}"
    )
    config_dir = tmp_path / "conf"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(patched)

    probe = textwrap.dedent(
        """
        import json
        import logging

        from lablink_allocator_service import main

        name = logging.getLevelName
        root = logging.getLogger()
        print(json.dumps({
            "environment": str(main.cfg.environment),
            "log_level": name(main._log_level),
            "root": name(root.level),
            "package": name(logging.getLogger("lablink_allocator_service").level),
            "route": name(
                logging.getLogger(
                    "lablink_allocator_service.routes.vm_telemetry"
                ).getEffectiveLevel()
            ),
            "botocore": name(logging.getLogger("botocore").getEffectiveLevel()),
            "paramiko": name(logging.getLogger("paramiko").getEffectiveLevel()),
            "urllib3": name(logging.getLogger("urllib3").getEffectiveLevel()),
            "formats": [
                h.formatter._fmt if h.formatter else None for h in root.handlers
            ],
        }))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env={**os.environ, "CONFIG_DIR": str(config_dir)},
    )
    assert result.returncode == 0, (
        f"probe failed:\n{result.stdout}\n{result.stderr}"
    )
    # main.py logs at import (and hydra warns), so take the last stdout line.
    probed = json.loads(result.stdout.strip().splitlines()[-1])
    assert probed["environment"] == environment, (
        f"probe ran against environment={probed['environment']!r}, expected "
        f"{environment!r} — CONFIG_DIR override did not take effect"
    )
    return probed
