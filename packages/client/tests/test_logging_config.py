"""Entry points configure logging; library modules only getLogger() (#409)."""

import ast
import json
import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path

PACKAGE_ROOT = (
    Path(__file__).resolve().parents[1] / "src" / "lablink_client_service"
)

ENTRY_POINTS = ["check_gpu.py", "heartbeat.py", "update_inuse_status.py"]

EXPECTED_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
EXPECTED_SET_LEVEL = (
    "logging.getLogger('lablink_client_service').setLevel(logging.DEBUG)"
)


def _import_time_calls(tree: ast.Module):
    stack: list[ast.AST] = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def _call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return getattr(func, "id", None)


def _main_of(filename: str) -> ast.FunctionDef:
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
    return main_fn


def _logging_config_of(filename: str) -> tuple[dict, list]:
    basic_config: dict = {}
    set_levels: list[str] = []
    for node in ast.walk(_main_of(filename)):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name == "basicConfig":
            basic_config = {kw.arg: ast.unparse(kw.value) for kw in node.keywords}
        elif name == "setLevel":
            set_levels.append(ast.unparse(node))
    return basic_config, sorted(set_levels)


def test_no_basic_config_at_import_time():
    """basicConfig() at import time makes the level a function of import order."""
    offenders = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for call in _import_time_calls(tree):
            if _call_name(call) == "basicConfig":
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{call.lineno}")

    assert not offenders, (
        "logging.basicConfig() runs at import time in: "
        + ", ".join(offenders)
        + ". Move it into the entry point's main()."
    )


def test_every_entry_point_configures_logging():
    """Unconfigured, a service's records reach no handler at all."""
    missing = []
    for filename in ENTRY_POINTS:
        basic_config, set_levels = _logging_config_of(filename)
        if not basic_config:
            missing.append(f"{filename}: no logging.basicConfig() in main()")
        elif not set_levels:
            missing.append(f"{filename}: no setLevel() for the package logger")

    assert not missing, "; ".join(missing)


def test_entry_points_agree_on_logging_configuration():
    """The three inlined copies must not drift — one log stream, one shape."""
    configs = {name: _logging_config_of(name) for name in ENTRY_POINTS}
    reference_name, reference = next(iter(configs.items()))

    for name, config in configs.items():
        assert config == reference, (
            f"{name} configures logging differently from {reference_name}:\n"
            f"  {name}: {config}\n"
            f"  {reference_name}: {reference}"
        )

    basic_config, set_levels = reference
    assert basic_config.get("level") == "logging.INFO", (
        "root must stay at INFO as the third-party noise floor, got "
        f"{basic_config.get('level')}"
    )
    assert basic_config.get("format") == repr(EXPECTED_FORMAT), (
        f"unexpected log format {basic_config.get('format')}"
    )
    assert set_levels == [EXPECTED_SET_LEVEL], (
        f"unexpected package-logger level call: {set_levels}"
    )


def test_configured_levels_behave_as_intended():
    """Our package logs at DEBUG; urllib3 stays at INFO and root owns the format.

    Runs heartbeat's main() in a subprocess — pytest owns root here, so an
    in-process basicConfig() is a no-op and would mask the result.
    """
    probe = textwrap.dedent(
        """
        import json
        import logging
        from unittest.mock import patch

        from omegaconf import OmegaConf

        from lablink_client_service import heartbeat

        cfg = OmegaConf.create({"allocator": {"host": "localhost", "port": 80}})
        with patch.object(heartbeat, "run_heartbeat_loop"):
            heartbeat.main(cfg)

        name = logging.getLevelName
        root = logging.getLogger()
        print(json.dumps({
            "root": name(root.level),
            "package": name(logging.getLogger("lablink_client_service").level),
            "service": name(
                logging.getLogger(
                    "lablink_client_service.heartbeat"
                ).getEffectiveLevel()
            ),
            "urllib3": name(logging.getLogger("urllib3").getEffectiveLevel()),
            "handlers": len(root.handlers),
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
        env={
            **os.environ,
            "ALLOCATOR_URL": "https://test.com",
            "CLIENT_SECRET": "test-secret",
        },
    )
    assert result.returncode == 0, f"probe failed:\n{result.stdout}\n{result.stderr}"
    probed = json.loads(result.stdout.strip().splitlines()[-1])

    assert probed["package"] == "DEBUG", (
        f"package logger is {probed['package']}, expected DEBUG — heartbeat's "
        "POST-failure logger.debug() calls would be dropped"
    )
    assert probed["service"] == "DEBUG", (
        f"a service module resolves to {probed['service']}, expected DEBUG"
    )
    assert probed["root"] == "INFO", (
        f"root is {probed['root']}, expected INFO as the third-party floor"
    )
    assert probed["urllib3"] == "INFO", (
        f"urllib3 resolves to {probed['urllib3']}; at DEBUG it logs every "
        "connection and buries our own output"
    )
    assert probed["handlers"] == 1, (
        f"expected exactly one root handler, got {probed['handlers']}"
    )
    assert probed["formats"] == [EXPECTED_FORMAT], (
        f"root handler format is {probed['formats']}"
    )


def test_main_raises_the_package_logger_in_process():
    """In-process counterpart so coverage sees main()'s logging lines run."""
    from unittest.mock import patch

    from omegaconf import OmegaConf

    from lablink_client_service import heartbeat

    logging.getLogger("lablink_client_service").setLevel(logging.NOTSET)
    cfg = OmegaConf.create({"allocator": {"host": "localhost", "port": 80}})

    with patch.dict(
        os.environ,
        {"ALLOCATOR_URL": "https://test.com", "CLIENT_SECRET": "test-secret"},
    ):
        with patch.object(heartbeat, "run_heartbeat_loop"):
            heartbeat.main(cfg)

    assert logging.getLogger("lablink_client_service").level == logging.DEBUG
