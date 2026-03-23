"""Textual TUI wizard for generating LabLink config."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    RadioButton,
    RadioSet,
    TextArea,
)
from textual.widgets.option_list import Option

from lablink_cli.config.schema import (
    AWS_REGIONS,
    GPU_INSTANCE_TYPES,
    Config,
    config_to_dict,
    save_config,
    validate_config,
)

DEFAULT_CONFIG_DIR = Path.home() / ".lablink"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.yaml"


# ---------------------------------------------------------------------------
# Screen 1: AWS Region
# ---------------------------------------------------------------------------
class RegionScreen(Screen):
    """Select AWS region."""

    BINDINGS = [Binding("escape", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 1 of 4: AWS Region", classes="step-title"
            )
            yield Label(
                "Select the AWS region closest to your users.",
                classes="step-description",
            )
            yield OptionList(
                *[
                    Option(
                        f"{r['id']:20s} {r['name']}",
                        id=r["id"],
                    )
                    for r in AWS_REGIONS
                ],
                id="region-list",
            )
        with Center():
            with Horizontal(classes="nav-buttons"):
                yield Button("Next", variant="primary", id="next")
        yield Footer()

    @on(OptionList.OptionSelected)
    def _select(self, event: OptionList.OptionSelected) -> None:
        self.app.config.app.region = str(event.option.id)

    @on(Button.Pressed, "#next")
    def _next(self) -> None:
        self.app.push_screen(MachineScreen())


# ---------------------------------------------------------------------------
# Screen 2: Machine Configuration
# ---------------------------------------------------------------------------
class MachineScreen(Screen):
    """Configure client VM instance type and software."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 2 of 4: Machine Configuration",
                classes="step-title",
            )

            yield Label("Instance Type", classes="field-label")
            yield OptionList(
                *[
                    Option(
                        f"{t['type']:18s} {t['gpu']:14s} "
                        f"{t['vcpu']} vCPU  {t['ram']:8s} {t['cost']}",
                        id=t["type"],
                    )
                    for t in GPU_INSTANCE_TYPES
                ],
                id="instance-list",
            )

            yield Label("Software Name", classes="field-label")
            yield Input(
                placeholder="e.g. sleap, deeplabcut, napari",
                id="software",
            )

            yield Label(
                "Data File Extension", classes="field-label"
            )
            yield Input(
                placeholder="e.g. slp, h5, csv",
                id="extension",
            )

            yield Label(
                "Git Repository (optional)", classes="field-label"
            )
            yield Input(
                placeholder=(
                    "https://github.com/org/repo.git"
                ),
                id="repository",
            )

        with Center():
            with Horizontal(classes="nav-buttons"):
                yield Button("Back", id="back")
                yield Button(
                    "Next", variant="primary", id="next"
                )
        yield Footer()

    @on(OptionList.OptionSelected, "#instance-list")
    def _select_instance(
        self, event: OptionList.OptionSelected
    ) -> None:
        self.app.config.machine.machine_type = str(
            event.option.id
        )

    @on(Button.Pressed, "#back")
    def _back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#next")
    def _next(self) -> None:
        software = self.query_one("#software", Input).value
        extension = self.query_one("#extension", Input).value
        repository = self.query_one("#repository", Input).value

        if software:
            self.app.config.machine.software = software
        if extension:
            self.app.config.machine.extension = extension
        if repository:
            self.app.config.machine.repository = repository

        self.app.push_screen(DnsScreen())


# ---------------------------------------------------------------------------
# Screen 3: DNS & SSL
# ---------------------------------------------------------------------------
class DnsScreen(Screen):
    """Configure DNS and SSL settings."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 3 of 4: DNS & SSL", classes="step-title"
            )

            yield Label("Access Method", classes="field-label")
            with RadioSet(id="dns-mode"):
                yield RadioButton(
                    "IP Only (no domain, HTTP)", value=True
                )
                yield RadioButton("Domain with Let's Encrypt")
                yield RadioButton("Domain with CloudFlare")
                yield RadioButton("Domain with AWS ACM (+ALB)")

            yield Label(
                "Domain Name",
                classes="field-label",
                id="domain-label",
            )
            yield Input(
                placeholder="lablink.example.com",
                id="domain",
                disabled=True,
            )

            yield Label(
                "Email (for SSL certificates)",
                classes="field-label",
                id="email-label",
            )
            yield Input(
                placeholder="admin@example.com",
                id="ssl-email",
                disabled=True,
            )

            yield Label(
                "ACM Certificate ARN",
                classes="field-label",
                id="acm-label",
            )
            yield Input(
                placeholder=(
                    "arn:aws:acm:region:account:certificate/id"
                ),
                id="acm-arn",
                disabled=True,
            )

        with Center():
            with Horizontal(classes="nav-buttons"):
                yield Button("Back", id="back")
                yield Button(
                    "Next", variant="primary", id="next"
                )
        yield Footer()

    @on(RadioSet.Changed, "#dns-mode")
    def _dns_changed(self, event: RadioSet.Changed) -> None:
        idx = event.index
        domain_input = self.query_one("#domain", Input)
        email_input = self.query_one("#ssl-email", Input)
        acm_input = self.query_one("#acm-arn", Input)

        # IP only
        if idx == 0:
            domain_input.disabled = True
            email_input.disabled = True
            acm_input.disabled = True
        # Let's Encrypt
        elif idx == 1:
            domain_input.disabled = False
            email_input.disabled = False
            acm_input.disabled = True
        # CloudFlare
        elif idx == 2:
            domain_input.disabled = False
            email_input.disabled = True
            acm_input.disabled = True
        # ACM
        elif idx == 3:
            domain_input.disabled = False
            email_input.disabled = True
            acm_input.disabled = False

    @on(Button.Pressed, "#back")
    def _back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#next")
    def _next(self) -> None:
        radio = self.query_one("#dns-mode", RadioSet)
        idx = radio.pressed_index
        cfg = self.app.config

        domain = self.query_one("#domain", Input).value
        email = self.query_one("#ssl-email", Input).value
        acm_arn = self.query_one("#acm-arn", Input).value

        if idx == 0:
            # IP only
            cfg.dns.enabled = False
            cfg.ssl.provider = "none"
            cfg.eip.strategy = "dynamic"
        elif idx == 1:
            # Let's Encrypt
            cfg.dns.enabled = True
            cfg.dns.terraform_managed = True
            cfg.dns.domain = domain
            cfg.ssl.provider = "letsencrypt"
            cfg.ssl.email = email
            cfg.eip.strategy = "persistent"
        elif idx == 2:
            # CloudFlare
            cfg.dns.enabled = True
            cfg.dns.terraform_managed = False
            cfg.dns.domain = domain
            cfg.ssl.provider = "cloudflare"
            cfg.eip.strategy = "persistent"
        elif idx == 3:
            # ACM
            cfg.dns.enabled = True
            cfg.dns.terraform_managed = True
            cfg.dns.domain = domain
            cfg.ssl.provider = "acm"
            cfg.ssl.certificate_arn = acm_arn
            cfg.eip.strategy = "persistent"

        self.app.push_screen(ReviewScreen())


# ---------------------------------------------------------------------------
# Screen 4: Review & Save
# ---------------------------------------------------------------------------
class ReviewScreen(Screen):
    """Review configuration and save."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 4 of 4: Review & Save",
                classes="step-title",
            )
            yield TextArea(
                id="review-yaml",
                read_only=True,
                language="yaml",
            )
            yield Label(
                f"Config will be saved to: {DEFAULT_CONFIG_PATH}",
                classes="step-description",
            )
            errors_label = Label("", id="errors", classes="error")
            errors_label.display = False
            yield errors_label
        with Center():
            with Horizontal(classes="nav-buttons"):
                yield Button("Back", id="back")
                yield Button(
                    "Save & Exit",
                    variant="success",
                    id="save",
                )
        yield Footer()

    def on_mount(self) -> None:
        import yaml

        cfg_dict = config_to_dict(self.app.config)
        yaml_str = yaml.dump(
            cfg_dict, default_flow_style=False, sort_keys=False
        )
        self.query_one("#review-yaml", TextArea).text = yaml_str

        errors = validate_config(self.app.config)
        if errors:
            label = self.query_one("#errors", Label)
            label.update("\n".join(f"  * {e}" for e in errors))
            label.display = True

    @on(Button.Pressed, "#back")
    def _back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        errors = validate_config(self.app.config)
        if errors:
            return
        save_config(self.app.config, DEFAULT_CONFIG_PATH)
        self.app.exit(message=f"Config saved to {DEFAULT_CONFIG_PATH}")


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------
class ConfigWizard(App):
    """LabLink configuration wizard."""

    TITLE = "LabLink Setup Wizard"
    CSS = """
    Screen {
        align: center middle;
    }
    .step-title {
        text-style: bold;
        color: $accent;
        margin: 1 2;
        text-align: center;
        width: 100%;
    }
    .step-description {
        color: $text-muted;
        margin: 0 2 1 2;
        text-align: center;
        width: 100%;
    }
    .field-label {
        margin: 1 2 0 2;
        text-style: bold;
    }
    Input {
        margin: 0 2;
    }
    OptionList {
        margin: 0 2;
        height: auto;
        max-height: 12;
    }
    RadioSet {
        margin: 0 2;
    }
    TextArea {
        margin: 0 2;
        height: 20;
    }
    .nav-buttons {
        margin: 1 0;
        height: auto;
    }
    .nav-buttons Button {
        margin: 0 1;
    }
    .error {
        color: $error;
        margin: 1 2;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config = Config()

    def on_mount(self) -> None:
        self.push_screen(RegionScreen())
