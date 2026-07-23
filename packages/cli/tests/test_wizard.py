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


def _build_cfg_and_app(
    deployment_name: str = "sleap-lablink",
    environment: str = "prod",
):
    """Build a Config + ConfigWizard suitable for DnsScreen tests."""
    from lablink_cli.config.schema import Config
    from lablink_cli.tui.wizard import ConfigWizard

    cfg = Config()
    cfg.deployment_name = deployment_name
    cfg.environment = environment
    cfg.provider = "aws"
    app = ConfigWizard(existing_config=cfg)
    return cfg, app


def _select_radio_by_id(screen, radioset_id: str, button_id: str) -> None:
    """Set the RadioButton with the given id to value=True within the RadioSet.

    Only flips the target to True; RadioSet's own RadioButton.Changed handler
    unsets the previously-pressed sibling inside a prevent block. Setting the
    sibling to False here would race that handler — its "click off" guard
    re-asserts value=True when it sees Changed(value=False), so depending on
    cross-widget message-queue order both buttons can end up True and
    `_save_advanced` (which returns the first True button) reads the wrong one.
    """
    from textual.widgets import RadioButton, RadioSet

    radio_set = screen.query_one(radioset_id, RadioSet)
    for btn in radio_set.query(RadioButton):
        if btn.id == button_id:
            btn.value = True
            return


def test_dns_guided_cloudflare_sets_persistent_eip():
    """Guided + Cloudflare radio → cfg.eip.strategy == 'persistent'."""
    import asyncio
    from lablink_cli.tui.wizard import DnsScreen

    cfg, app = _build_cfg_and_app()

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = DnsScreen()
            app.push_screen(screen)
            await pilot.pause()
            _select_radio_by_id(screen, "#dns-mode", "dns-cloudflare")
            # Populate required Cloudflare fields so _next() doesn't bail.
            screen.query_one("#domain").value = "lablink.sleap.ai"
            await pilot.pause()
            screen._next()
            await pilot.pause()

    asyncio.run(_run())
    assert cfg.eip.strategy == "persistent"


def test_dns_guided_letsencrypt_sets_dynamic_eip():
    """Guided + Let's Encrypt → cfg.eip.strategy == 'dynamic'."""
    import asyncio
    from lablink_cli.tui.wizard import DnsScreen

    cfg, app = _build_cfg_and_app()

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = DnsScreen()
            app.push_screen(screen)
            await pilot.pause()
            _select_radio_by_id(screen, "#dns-mode", "dns-letsencrypt")
            screen.query_one("#domain").value = "lablink.example.com"
            screen.query_one("#ssl-email").value = "admin@example.com"
            await pilot.pause()
            screen._next()
            await pilot.pause()

    asyncio.run(_run())
    assert cfg.eip.strategy == "dynamic"


def test_dns_guided_none_sets_dynamic_eip():
    """Guided + None (IP only) → cfg.eip.strategy == 'dynamic'."""
    import asyncio
    from lablink_cli.tui.wizard import DnsScreen

    cfg, app = _build_cfg_and_app()

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = DnsScreen()
            app.push_screen(screen)
            await pilot.pause()
            _select_radio_by_id(screen, "#dns-mode", "dns-none")
            await pilot.pause()
            screen._next()
            await pilot.pause()

    asyncio.run(_run())
    assert cfg.eip.strategy == "dynamic"


def test_dns_guided_self_signed_sets_dynamic_eip():
    """Guided + Self-signed → cfg.eip.strategy == 'dynamic'."""
    import asyncio
    from lablink_cli.tui.wizard import DnsScreen

    cfg, app = _build_cfg_and_app()

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = DnsScreen()
            app.push_screen(screen)
            await pilot.pause()
            _select_radio_by_id(screen, "#dns-mode", "dns-self_signed")
            await pilot.pause()
            screen._next()
            await pilot.pause()

    asyncio.run(_run())
    assert cfg.eip.strategy == "dynamic"


def test_dns_guided_cloudflare_shows_eip_help():
    """Selecting Cloudflare reveals a help label containing the literal EIP tag."""
    import asyncio
    from lablink_cli.tui.wizard import DnsScreen

    cfg, app = _build_cfg_and_app(
        deployment_name="sleap-lablink", environment="prod"
    )

    async def _run() -> str:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = DnsScreen()
            app.push_screen(screen)
            await pilot.pause()
            _select_radio_by_id(screen, "#dns-mode", "dns-cloudflare")
            await pilot.pause()
            label = screen.query_one("#eip-help")
            return str(label.render())

    text = asyncio.run(_run())
    assert "sleap-lablink-eip-prod" in text


def test_dns_screen_has_mode_toggle_default_guided():
    """DnsScreen mounts with a Guided/Advanced toggle; Guided default."""
    import asyncio
    from lablink_cli.tui.wizard import DnsScreen

    cfg, app = _build_cfg_and_app()

    async def _run() -> tuple[bool, bool]:
        from textual.widgets import RadioButton, RadioSet

        async with app.run_test() as pilot:
            await pilot.pause()
            screen = DnsScreen()
            app.push_screen(screen)
            await pilot.pause()
            radio_set = screen.query_one("#dns-screen-mode", RadioSet)
            buttons = list(radio_set.query(RadioButton))
            guided_selected = (
                buttons[0].id == "screen-mode-guided"
                and buttons[0].value is True
            )
            advanced_hidden = (
                screen.query_one("#dns-advanced").display is False
            )
            return guided_selected, advanced_hidden

    guided, hidden = asyncio.run(_run())
    assert guided is True
    assert hidden is True


def test_dns_advanced_persistent_eip_writes_through():
    """Advanced mode: flipping EIP radio to persistent writes cfg.eip.strategy."""
    import asyncio
    from lablink_cli.tui.wizard import DnsScreen

    cfg, app = _build_cfg_and_app()

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = DnsScreen()
            app.push_screen(screen)
            await pilot.pause()
            _select_radio_by_id(
                screen, "#dns-screen-mode", "screen-mode-advanced"
            )
            await pilot.pause()
            _select_radio_by_id(
                screen, "#adv-dns-enabled", "adv-dns-enabled-yes"
            )
            _select_radio_by_id(
                screen,
                "#adv-dns-tfmanaged",
                "adv-dns-tfmanaged-no",
            )
            _select_radio_by_id(
                screen,
                "#adv-ssl-provider",
                "adv-ssl-cloudflare",
            )
            _select_radio_by_id(
                screen,
                "#adv-eip-strategy",
                "adv-eip-persistent",
            )
            screen.query_one("#adv-dns-domain").value = (
                "lablink.sleap.ai"
            )
            await pilot.pause()
            screen._next()
            await pilot.pause()

    asyncio.run(_run())
    assert cfg.eip.strategy == "persistent"
    assert cfg.dns.enabled is True
    assert cfg.dns.terraform_managed is False
    assert cfg.dns.domain == "lablink.sleap.ai"
    assert cfg.ssl.provider == "cloudflare"


def test_dns_advanced_zone_id_writes_through():
    """Advanced mode: typed zone_id is saved to cfg.dns.zone_id."""
    import asyncio
    from lablink_cli.tui.wizard import DnsScreen

    cfg, app = _build_cfg_and_app()

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = DnsScreen()
            app.push_screen(screen)
            await pilot.pause()
            _select_radio_by_id(
                screen, "#dns-screen-mode", "screen-mode-advanced"
            )
            await pilot.pause()
            _select_radio_by_id(
                screen, "#adv-dns-enabled", "adv-dns-enabled-yes"
            )
            _select_radio_by_id(
                screen,
                "#adv-dns-tfmanaged",
                "adv-dns-tfmanaged-yes",
            )
            _select_radio_by_id(
                screen,
                "#adv-ssl-provider",
                "adv-ssl-letsencrypt",
            )
            screen.query_one("#adv-dns-domain").value = (
                "lablink.example.com"
            )
            screen.query_one("#adv-ssl-email").value = (
                "admin@example.com"
            )
            screen.query_one("#adv-dns-zone-id").value = (
                "Z0123456789ABCDEFG"
            )
            await pilot.pause()
            screen._next()
            await pilot.pause()

    asyncio.run(_run())
    assert cfg.dns.zone_id == "Z0123456789ABCDEFG"


def test_dns_toggle_preserves_typed_domain():
    """Typing a domain in Guided, toggling to Advanced shows the same value."""
    import asyncio
    from lablink_cli.tui.wizard import DnsScreen

    cfg, app = _build_cfg_and_app()

    async def _run() -> str:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = DnsScreen()
            app.push_screen(screen)
            await pilot.pause()
            _select_radio_by_id(screen, "#dns-mode", "dns-cloudflare")
            await pilot.pause()
            screen.query_one("#domain").value = "lablink.sleap.ai"
            await pilot.pause()
            _select_radio_by_id(
                screen, "#dns-screen-mode", "screen-mode-advanced"
            )
            await pilot.pause()
            return screen.query_one("#adv-dns-domain").value

    domain = asyncio.run(_run())
    assert domain == "lablink.sleap.ai"


def test_dns_advanced_invalid_combo_blocks_next():
    """Advanced + invalid combo (DNS disabled + letsencrypt) → error shown, no push."""
    import asyncio
    from lablink_cli.tui.wizard import DnsScreen

    cfg, app = _build_cfg_and_app()

    async def _run() -> tuple[bool, int, str]:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = DnsScreen()
            app.push_screen(screen)
            await pilot.pause()
            stack_before = len(app.screen_stack)
            _select_radio_by_id(
                screen, "#dns-screen-mode", "screen-mode-advanced"
            )
            await pilot.pause()
            _select_radio_by_id(
                screen, "#adv-dns-enabled", "adv-dns-enabled-no"
            )
            _select_radio_by_id(
                screen,
                "#adv-ssl-provider",
                "adv-ssl-letsencrypt",
            )
            await pilot.pause()
            screen._next()
            await pilot.pause()
            stack_after = len(app.screen_stack)
            err = str(
                screen.query_one("#dns-validation-error").render()
            )
            visible = screen.query_one(
                "#dns-validation-error"
            ).display
            return visible, stack_after - stack_before, err

    visible, stack_delta, err = asyncio.run(_run())
    assert visible is True
    assert stack_delta == 0  # screen did not push StartupScreen
    assert err  # non-empty error text


def test_dns_advanced_eip_radio_is_scrollable_into_view():
    """Regression: under #dns-advanced the form is longer than the viewport.
    A previous CSS configuration left the inner VerticalScroll viewport
    sized to 1 row and the dns-advanced Container clamped to ~10 rows,
    so widgets near the bottom of Advanced (the EIP strategy radio
    being the rearmost) were unreachable — they rendered at y≈55 with
    no scroll headroom. This asserts the layout permits a real user to
    scroll the EIP radio into view at a normal terminal size."""
    import asyncio
    from textual.widgets import RadioSet

    cfg, app = _build_cfg_and_app()

    async def _run() -> tuple[int, int]:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            from lablink_cli.tui.wizard import DnsScreen

            screen = DnsScreen()
            app.push_screen(screen)
            await pilot.pause()

            # Real keyboard activation; pilot.click is unreliable on
            # RadioButtons in this Textual version (see issue tracker
            # / monitoring screen tests for the same workaround).
            mode = screen.query_one("#dns-screen-mode", RadioSet)
            mode.focus()
            await pilot.pause()
            await pilot.press("down", "enter")
            for _ in range(5):
                await pilot.pause()

            vs = next(iter(screen.query("VerticalScroll")))
            eip = screen.query_one("#adv-eip-strategy", RadioSet)
            vs.scroll_to_widget(eip, animate=False, top=True)
            for _ in range(5):
                await pilot.pause()
            return vs.max_scroll_y, eip.region.y

    max_scroll_y, eip_y = asyncio.run(_run())
    # If max_scroll_y == 0 the container collapsed and the user has no
    # way to reach the bottom of Advanced. Should be substantial.
    assert max_scroll_y > 0, (
        f"dns-advanced collapsed: VerticalScroll.max_scroll_y={max_scroll_y}; "
        "the EIP strategy radio (and any field below it) is unreachable."
    )
    # After scrolling, EIP should land inside the viewport (0..screen.height).
    assert 1 <= eip_y < 30, (
        f"After scroll_to_widget, EIP radio at y={eip_y} is outside the "
        "30-row test viewport — scroll isn't bringing it into view."
    )


# ---------------------------------------------------------------------------
# ManualConnectivityScreen
# ---------------------------------------------------------------------------
def _drive_connectivity_screen(
    *, choose_mesh_overlay: bool, overlay_tailnet: str = ""
):
    """Push ManualConnectivityScreen directly, drive it, return
    (cfg.manual.connectivity, cfg.manual.overlay_tailnet, screen_stack_grew)."""
    import asyncio
    from textual.widgets import Input, RadioButton, RadioSet

    cfg, app = _build_cfg_and_app()
    cfg.provider = "manual"

    async def _run() -> tuple[str, str, int]:
        from lablink_cli.tui.wizard import ManualConnectivityScreen

        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ManualConnectivityScreen()
            app.push_screen(screen)
            await pilot.pause()
            stack_before = len(app.screen_stack)

            if choose_mesh_overlay:
                radio_set = screen.query_one("#connectivity-select", RadioSet)
                for btn in radio_set.query(RadioButton):
                    if btn.id == "connectivity-mesh-overlay":
                        btn.value = True
                screen.query_one("#overlay-tailnet", Input).value = overlay_tailnet
            await pilot.pause()
            screen._next()
            await pilot.pause()
            return (
                cfg.manual.connectivity,
                cfg.manual.overlay_tailnet,
                len(app.screen_stack) - stack_before,
            )

    return asyncio.run(_run())


def test_connectivity_screen_defaults_to_lan_direct():
    connectivity, tailnet, stack_delta = _drive_connectivity_screen(
        choose_mesh_overlay=False
    )
    assert connectivity == "lan_direct"
    assert stack_delta == 1, "valid submission should push DnsScreen"


def test_connectivity_screen_writes_mesh_overlay_and_tailnet():
    connectivity, tailnet, stack_delta = _drive_connectivity_screen(
        choose_mesh_overlay=True, overlay_tailnet="example.ts.net"
    )
    assert connectivity == "mesh_overlay"
    assert tailnet == "example.ts.net"
    assert stack_delta == 1, "valid submission should push DnsScreen"


def test_connectivity_screen_blocks_next_when_tailnet_missing():
    """mesh_overlay chosen but no tailnet domain → validation error, no push."""
    connectivity, tailnet, stack_delta = _drive_connectivity_screen(
        choose_mesh_overlay=True, overlay_tailnet=""
    )
    assert connectivity == "mesh_overlay"
    assert stack_delta == 0, "invalid submission must not push DnsScreen"


def _drive_startup_retry_fields(
    max_attempts: str | None, base_delay: str | None, success_check: str | None
):
    """Push StartupScreen directly, optionally edit the retry fields, hit Next.

    Passing None for an input leaves its pre-filled value untouched;
    passing "" clears it (simulating a user deleting the field).
    """
    from lablink_cli.config.schema import Config
    from lablink_cli.tui.wizard import ConfigWizard, StartupScreen

    cfg = Config()
    app = ConfigWizard(existing_config=cfg)

    async def _run() -> None:
        from textual.widgets import Input

        async with app.run_test() as pilot:
            await pilot.pause()
            screen = StartupScreen()
            app.push_screen(screen)
            await pilot.pause()

            if max_attempts is not None:
                screen.query_one("#max-attempts", Input).value = max_attempts
            if base_delay is not None:
                screen.query_one("#base-delay", Input).value = base_delay
            if success_check is not None:
                screen.query_one("#success-check", Input).value = success_check
            await pilot.pause()

            # Invoke the screen's Next handler directly — clicking via the
            # pilot needs viewport coords that aren't reliable in headless
            # tests, matching the pattern used for MonitoringScreen/
            # ConnectivityScreen above.
            screen._next()
            await pilot.pause()

    asyncio.run(_run())
    return cfg.startup_script


def test_startup_screen_writes_retry_fields():
    result = _drive_startup_retry_fields(
        max_attempts="5",
        base_delay="45",
        success_check="/home/client/.local/bin/sleap --version",
    )
    assert result.max_attempts == 5
    assert result.base_delay_seconds == 45
    assert result.success_check == "/home/client/.local/bin/sleap --version"


def test_startup_screen_empty_numeric_fields_fall_back_to_defaults():
    """Clearing max-attempts/base-delay must not crash int() on '' — falls
    back to StartupConfig's own declared defaults (3, 30)."""
    result = _drive_startup_retry_fields(
        max_attempts="", base_delay="", success_check=None
    )
    assert result.max_attempts == 3
    assert result.base_delay_seconds == 30
