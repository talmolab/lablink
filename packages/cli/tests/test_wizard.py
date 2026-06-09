"""TUI wizard — monitoring screen toggle."""

from __future__ import annotations

import asyncio


def _drive_monitoring_toggle(initial_enabled: bool, click_enabled: bool) -> bool:
    """Drive MonitoringScreen, return cfg.monitoring.enabled after Next.

    Pushes MonitoringScreen directly onto the wizard app (bypasses the
    four preceding screens) so the test focuses on the toggle behavior.
    """
    from lablink_cli.config.schema import Config
    from lablink_cli.tui.wizard import ConfigWizard, MonitoringScreen

    cfg = Config()
    cfg.monitoring.enabled = initial_enabled
    app = ConfigWizard(existing_config=cfg)

    async def _run() -> None:
        from textual.widgets import RadioButton, RadioSet

        async with app.run_test() as pilot:
            await pilot.pause()
            screen = MonitoringScreen()
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()
            # Radio order: index 0 = Disabled, index 1 = Enabled.
            target_index = 1 if click_enabled else 0
            radio_set = screen.query_one("#monitoring-mode", RadioSet)
            buttons = list(radio_set.query(RadioButton))
            buttons[target_index].value = True
            await pilot.pause()
            # Invoke the screen's Next handler directly — clicking via the
            # pilot needs viewport coords that aren't reliable in headless
            # tests, and we just want to verify the state-write behavior.
            screen._next()
            await pilot.pause()

    asyncio.run(_run())
    return cfg.monitoring.enabled


def test_monitoring_screen_writes_enabled_true():
    assert _drive_monitoring_toggle(
        initial_enabled=False, click_enabled=True
    ) is True


def test_monitoring_screen_writes_enabled_false():
    assert _drive_monitoring_toggle(
        initial_enabled=True, click_enabled=False
    ) is False


def test_monitoring_screen_does_not_touch_other_fields():
    """Toggling enabled must NOT clobber process_allowlist / watch_dir / intervals."""
    from lablink_cli.config.schema import Config
    from lablink_cli.tui.wizard import ConfigWizard, MonitoringScreen

    cfg = Config()
    original_allowlist = list(cfg.monitoring.process_allowlist)
    original_watch_dir = cfg.monitoring.watch_dir
    original_sample = cfg.monitoring.sample_interval_seconds
    original_push = cfg.monitoring.push_interval_seconds

    app = ConfigWizard(existing_config=cfg)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(MonitoringScreen())
            await pilot.pause()
            await pilot.click("#next")
            await pilot.pause()

    asyncio.run(_run())

    assert cfg.monitoring.process_allowlist == original_allowlist
    assert cfg.monitoring.watch_dir == original_watch_dir
    assert cfg.monitoring.sample_interval_seconds == original_sample
    assert cfg.monitoring.push_interval_seconds == original_push
