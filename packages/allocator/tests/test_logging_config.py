"""The package logger must carry the configured level explicitly.

Regression guard for #406: when main.py's route handlers were split into
routes/ blueprints, each new module logged through its own
``logging.getLogger(__name__)`` with no explicit level. Setting the level once
on the package logger is what keeps the seven ``logger.debug()`` calls across
routes/ alive in dev/test/ci-test.
"""

import logging

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


def test_package_logger_carries_configured_level():
    """Guards the fix directly: delete the setLevel call in main.py and this
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
