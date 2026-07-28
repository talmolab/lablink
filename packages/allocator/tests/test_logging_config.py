"""The package logger must carry the configured level explicitly.

Regression guard for a bug introduced when main.py's route handlers were
split into routes/ blueprints. Each new module logs through its own
``logging.getLogger(__name__)`` with no explicit level, so it inherits the
package logger — and root cannot be relied on, because
``utils/aws_utils`` calls ``logging.basicConfig(level=INFO)`` at import time
and the ``providers.registry`` import at the top of main.py pulls it in.
That makes main.py's own ``basicConfig(level=_log_level)`` a no-op with root
pinned at INFO.

Before the split every ``logger.debug()`` lived in main.py and rode main's
own explicitly-levelled logger, so the pinned root was harmless. After it,
seven ``logger.debug()`` calls across routes/ were silently dropped in
dev/test/ci-test until the package logger was levelled explicitly.
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
        f"{logging.getLevelName(main._log_level)}. Root cannot be relied on "
        "here — utils/aws_utils calls basicConfig() first, so main.py's own "
        "basicConfig() is a no-op."
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
