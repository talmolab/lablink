"""Logging is configured by entry points; library modules only getLogger().

Replaces test_logger_utils.py, which covered the CloudWatch-era
`CloudAndConsoleLogger` wrapper that the three client services used to assign
over their module-level `logger` inside `main()`.

The rule these guard is the one from allocator issue #409: a module that calls
`logging.basicConfig()` at import time mutates global logging state for
whatever process imports it, and `basicConfig()` is a no-op once root has a
handler — so import order silently decides the level and format for everything
that follows.
"""

import ast
import json
import logging
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from lablink_client_service.logging_setup import (
    PACKAGE_LOGGER,
    configure_service_logging,
)

PACKAGE_ROOT = (
    Path(__file__).resolve().parents[1] / "src" / "lablink_client_service"
)

# Console-script entry points that must configure logging themselves.
ENTRY_POINTS = ["check_gpu.py", "heartbeat.py", "update_inuse_status.py"]


def _import_time_calls(tree: ast.Module):
    """Yield every Call node that runs when the module is imported.

    Descends through module-scope ``if``/``try``/``with``/``for`` and class
    bodies (all of which run at import) but stops at function and lambda
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


def test_no_basic_config_at_import_time():
    """No module in this package may configure logging as an import side
    effect — not even the entry points, all of which do it from a function.
    """
    offenders = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for call in _import_time_calls(tree):
            func = call.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", None)
            )
            if name == "basicConfig":
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{call.lineno}")

    assert not offenders, (
        "logging.basicConfig() runs at import time in: "
        + ", ".join(offenders)
        + ". Move it into the entry point's main()."
    )


def test_every_entry_point_configures_logging():
    """Each console script must call configure_service_logging() from main().

    Without it the service's own INFO records never reach a handler: root sits
    at WARNING with no handler, so logging falls back to lastResort and the
    "Starting ..." liveness lines vanish from the container logs.
    """
    missing = []
    for filename in ENTRY_POINTS:
        tree = ast.parse((PACKAGE_ROOT / filename).read_text())
        main_fn = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "main"
            ),
            None,
        )
        assert main_fn is not None, f"{filename} has no main()"
        called = {
            node.func.id
            for node in ast.walk(main_fn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        if "configure_service_logging" not in called:
            missing.append(filename)

    assert not missing, (
        "main() does not call configure_service_logging() in: "
        + ", ".join(missing)
    )


def _probe(body: str) -> dict:
    """Run `body` in a clean interpreter and return the JSON it prints.

    A subprocess is required: pytest installs its own root handler, which makes
    basicConfig() a no-op and would mask exactly what these tests assert.
    """
    probe = textwrap.dedent(
        """
        import json
        import logging

        from lablink_client_service.logging_setup import (
            configure_service_logging,
        )

        {body}

        name = logging.getLevelName
        root = logging.getLogger()
        print(json.dumps({{
            "root": name(root.level),
            "package": name(logging.getLogger("lablink_client_service").level),
            "service": name(
                logging.getLogger(
                    "lablink_client_service.heartbeat"
                ).getEffectiveLevel()
            ),
            "urllib3": name(logging.getLogger("urllib3").getEffectiveLevel()),
            "requests": name(logging.getLogger("requests").getEffectiveLevel()),
            "handlers": len(root.handlers),
            "formats": [
                h.formatter._fmt if h.formatter else None for h in root.handlers
            ],
        }}))
        """
    ).format(body=body)
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True
    )
    assert result.returncode == 0, f"probe failed:\n{result.stdout}\n{result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_configure_service_logging_installs_one_formatted_handler():
    probed = _probe("configure_service_logging()")

    assert probed["handlers"] == 1, (
        f"expected exactly one root handler, got {probed['handlers']}"
    )
    assert probed["formats"] == ["%(asctime)s %(levelname)s %(name)s: %(message)s"], (
        f"root handler format is {probed['formats']}"
    )


def test_package_logs_at_debug_without_dragging_third_parties_along():
    """The two-level split, which is the whole point of the helper.

    DEBUG is what these services have always run at — CloudAndConsoleLogger
    defaulted to it. Setting DEBUG on *root* instead would also switch on
    urllib3, which logs every connection and request line and would bury
    heartbeat's own POST-failure debug output.
    """
    probed = _probe("configure_service_logging()")

    assert probed["package"] == "DEBUG", (
        f"package logger is {probed['package']}, expected DEBUG"
    )
    assert probed["service"] == "DEBUG", (
        f"a service module resolves to {probed['service']}, expected DEBUG"
    )
    assert probed["root"] == "INFO", (
        f"root is {probed['root']}, expected INFO as the third-party floor"
    )
    for lib in ("urllib3", "requests"):
        assert probed[lib] == "INFO", f"{lib} resolves to {probed[lib]}, expected INFO"


def test_level_argument_is_honoured():
    probed = _probe("configure_service_logging(logging.WARNING)")

    assert probed["package"] == "WARNING", (
        f"package logger is {probed['package']}, expected WARNING"
    )
    assert probed["root"] == "INFO", "root should be unaffected by the level argument"


@pytest.fixture
def package_logger():
    """Yield the package logger and restore its level afterwards.

    configure_service_logging() mutates process-global state, so an in-process
    call has to be undone or it leaks into every test that runs after it.
    """
    logger = logging.getLogger(PACKAGE_LOGGER)
    previous = logger.level
    yield logger
    logger.setLevel(previous)


def test_sets_the_package_logger_level_in_process(package_logger):
    """Exercises the real function rather than a subprocess copy of it.

    Only the setLevel half is observable here — pytest owns root, so its
    basicConfig() is a no-op under the test runner. The root handler, format
    and third-party floor are asserted by the probes above.
    """
    configure_service_logging(logging.WARNING)
    assert package_logger.level == logging.WARNING

    configure_service_logging()
    assert package_logger.level == logging.DEBUG
