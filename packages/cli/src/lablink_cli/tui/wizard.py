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
    AMI_MAP,
    AWS_REGIONS,
    CPU_INSTANCE_TYPES,
    DEPLOYMENT_NAME_RE,
    GPU_INSTANCE_TYPES,
    VALID_ENVIRONMENTS,
    Config,
    config_to_dict,
    save_config,
    validate_config,
)

DEFAULT_CONFIG_DIR = Path.home() / ".lablink"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.yaml"


# ---------------------------------------------------------------------------
# Screen 1: Deployment Name & Environment
# ---------------------------------------------------------------------------
class DeploymentScreen(Screen):
    """Configure deployment name and environment."""

    BINDINGS = [Binding("escape", "quit", "Quit")]

    def action_quit(self) -> None:
        self.app.exit()

    def compose(self) -> ComposeResult:
        cfg = self.app.config

        # Determine pre-selected environment index
        env_list = list(VALID_ENVIRONMENTS)
        try:
            env_idx = env_list.index(cfg.environment)
        except ValueError:
            env_idx = len(env_list) - 1  # default to prod

        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 1 of 6: Deployment Identity",
                classes="step-title",
            )
            yield Label(
                "Give this deployment a unique name and "
                "select the environment.",
                classes="step-description",
            )

            yield Label(
                "Deployment Name", classes="field-label"
            )
            yield Input(
                value=cfg.deployment_name or "",
                placeholder="e.g. sleap-lablink, deeplabcut-lablink",
                id="deployment-name",
            )
            yield Label(
                "3-32 chars, lowercase kebab-case "
                "(letters, digits, hyphens)",
                classes="step-description",
                id="name-hint",
            )

            yield Label(
                "Environment", classes="field-label"
            )
            with RadioSet(id="env-select"):
                for i, env in enumerate(env_list):
                    yield RadioButton(
                        env, value=(i == env_idx)
                    )

            yield Label(
                "", id="deploy-error", classes="error"
            )

        with Center():
            with Horizontal(classes="nav-buttons"):
                yield Button(
                    "Next", variant="primary", id="next"
                )
        yield Footer()

    @on(Button.Pressed, "#next")
    def _next(self) -> None:
        name = self.query_one(
            "#deployment-name", Input
        ).value.strip()
        error_label = self.query_one("#deploy-error", Label)

        # Validate deployment name
        if not name:
            error_label.update(
                "Deployment name is required"
            )
            error_label.display = True
            return
        if (
            len(name) < 3
            or len(name) > 32
            or not DEPLOYMENT_NAME_RE.match(name)
        ):
            error_label.update(
                "Must be 3-32 chars, lowercase kebab-case "
                "(e.g., 'sleap-lablink')"
            )
            error_label.display = True
            return

        error_label.display = False
        self.app.config.deployment_name = name

        # Read environment from radio set
        env_radio = self.query_one("#env-select", RadioSet)
        env_list = list(VALID_ENVIRONMENTS)
        self.app.config.environment = env_list[
            env_radio.pressed_index
        ]

        self.app.push_screen(RegionScreen())


# ---------------------------------------------------------------------------
# Screen 2: AWS Region
# ---------------------------------------------------------------------------
class RegionScreen(Screen):
    """Select AWS region."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def action_back(self) -> None:
        self.app.pop_screen()

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 2 of 6: AWS Region", classes="step-title"
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
                yield Button("Back", id="back")
                yield Button("Next", variant="primary", id="next")
        yield Footer()

    @on(OptionList.OptionSelected)
    def _select(self, event: OptionList.OptionSelected) -> None:
        region = str(event.option.id)
        self.app.config.app.region = region
        # Auto-select AMI for the chosen region
        if region in AMI_MAP:
            self.app.config.machine.ami_id = AMI_MAP[region]

    @on(Button.Pressed, "#back")
    def _back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#next")
    def _next(self) -> None:
        self.app.push_screen(MachineScreen())


# ---------------------------------------------------------------------------
# Screen 3: Machine Configuration
# ---------------------------------------------------------------------------
class MachineScreen(Screen):
    """Configure client VM instance type and software."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 3 of 6: Machine Configuration",
                classes="step-title",
            )

            yield Label("Instance Type", classes="field-label")
            gpu_options = [
                Option(
                    f"{t['type']:18s} {t['gpu']:14s} "
                    f"{t['vcpu']} vCPU  {t['ram']:8s} {t['cost']}",
                    id=t["type"],
                )
                for t in GPU_INSTANCE_TYPES
            ]
            cpu_options = [
                Option(
                    f"{t['type']:18s} {'—':14s} "
                    f"{t['vcpu']} vCPU  {t['ram']:8s} {t['cost']}",
                    id=t["type"],
                )
                for t in CPU_INSTANCE_TYPES
            ]
            yield OptionList(
                Option("── GPU Instances ──", disabled=True),
                *gpu_options,
                None,
                Option(
                    "── CPU Only (no GPU) ──", disabled=True
                ),
                *cpu_options,
                id="instance-list",
            )

            cfg = self.app.config

            yield Label("Software Name", classes="field-label")
            yield Input(
                value=cfg.machine.software or "",
                placeholder="e.g. sleap, deeplabcut, napari",
                id="software",
            )

            yield Label(
                "Data File Extension", classes="field-label"
            )
            yield Input(
                value=cfg.machine.extension or "",
                placeholder="e.g. slp, h5, csv",
                id="extension",
            )

            yield Label(
                "Git Repository (optional)", classes="field-label"
            )
            yield Input(
                value=cfg.machine.repository or "",
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
        self.app.config.machine.repository = (
            repository if repository else None
        )

        self.app.push_screen(DnsScreen())


# ---------------------------------------------------------------------------
# Screen 4: DNS & SSL
# ---------------------------------------------------------------------------
class DnsScreen(Screen):
    """Configure DNS and SSL settings."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        cfg = self.app.config

        # Determine which radio button to pre-select
        if not cfg.dns.enabled:
            default_idx = 0
        elif cfg.ssl.provider == "letsencrypt":
            default_idx = 1
        elif cfg.ssl.provider == "cloudflare":
            default_idx = 2
        elif cfg.ssl.provider == "acm":
            default_idx = 3
        else:
            default_idx = 0

        has_domain = default_idx > 0

        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 4 of 6: DNS & SSL", classes="step-title"
            )

            yield Label("Access Method", classes="field-label")
            with RadioSet(id="dns-mode"):
                yield RadioButton(
                    "IP Only (no domain, HTTP)",
                    value=(default_idx == 0),
                )
                yield RadioButton(
                    "Domain with Let's Encrypt",
                    value=(default_idx == 1),
                )
                yield RadioButton(
                    "Domain with CloudFlare",
                    value=(default_idx == 2),
                )
                yield RadioButton(
                    "Domain with AWS ACM (+ALB)",
                    value=(default_idx == 3),
                )

            yield Label(
                "Domain Name",
                classes="field-label",
                id="domain-label",
            )
            yield Input(
                value=cfg.dns.domain or "",
                placeholder="lablink.example.com",
                id="domain",
                disabled=not has_domain,
            )

            yield Label(
                "Email (for SSL certificates)",
                classes="field-label",
                id="email-label",
            )
            yield Input(
                value=cfg.ssl.email or "",
                placeholder="admin@example.com",
                id="ssl-email",
                disabled=(default_idx != 1),
            )

            yield Label(
                "ACM Certificate ARN",
                classes="field-label",
                id="acm-label",
            )
            yield Input(
                value=cfg.ssl.certificate_arn or "",
                placeholder=(
                    "arn:aws:acm:region:account:certificate/id"
                ),
                id="acm-arn",
                disabled=(default_idx != 3),
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
            cfg.eip.strategy = "dynamic"
        elif idx == 2:
            # CloudFlare
            cfg.dns.enabled = True
            cfg.dns.terraform_managed = False
            cfg.dns.domain = domain
            cfg.ssl.provider = "cloudflare"
            cfg.eip.strategy = "dynamic"
        elif idx == 3:
            # ACM
            cfg.dns.enabled = True
            cfg.dns.terraform_managed = True
            cfg.dns.domain = domain
            cfg.ssl.provider = "acm"
            cfg.ssl.certificate_arn = acm_arn
            cfg.eip.strategy = "dynamic"

        self.app.push_screen(StartupScreen())


# ---------------------------------------------------------------------------
# Screen 5: Startup Script
# ---------------------------------------------------------------------------
STARTUP_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "terraform"
    / "config"
    / "startup-template.sh"
)


class StartupScreen(Screen):
    """Configure custom startup script for client VMs."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        cfg = self.app.config

        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 5 of 6: Client Startup Script",
                classes="step-title",
            )
            yield Label(
                "Optional script that runs inside each "
                "client VM container after launch.",
                classes="step-description",
            )

            yield Label("Startup Script", classes="field-label")
            with RadioSet(id="startup-mode"):
                yield RadioButton(
                    "None (no startup script)",
                    value=not cfg.startup_script.enabled,
                )
                yield RadioButton(
                    "Use template (edit below)",
                    value=(
                        cfg.startup_script.enabled
                        and not self._has_custom_path()
                    ),
                )
                yield RadioButton(
                    "Use file from disk",
                    value=(
                        cfg.startup_script.enabled
                        and self._has_custom_path()
                    ),
                )

            # Determine initial mode
            is_template = (
                cfg.startup_script.enabled
                and not self._has_custom_path()
            )
            is_file = (
                cfg.startup_script.enabled
                and self._has_custom_path()
            )

            # Template editor
            template_content = self._load_template()
            yield TextArea(
                template_content,
                id="script-editor",
                language="bash",
                disabled=not is_template,
            )

            # File path input
            yield Label(
                "Script file path",
                classes="field-label",
                id="path-label",
            )
            yield Input(
                value=(
                    cfg.startup_script.path
                    if self._has_custom_path()
                    else ""
                ),
                placeholder="/path/to/startup.sh",
                id="script-path",
                disabled=not is_file,
            )

            yield Label(
                "On error", classes="field-label"
            )
            with RadioSet(id="on-error"):
                yield RadioButton(
                    "Continue (log and proceed)",
                    value=(
                        cfg.startup_script.on_error
                        == "continue"
                    ),
                )
                yield RadioButton(
                    "Fail (stop VM setup)",
                    value=(
                        cfg.startup_script.on_error == "fail"
                    ),
                )

        with Center():
            with Horizontal(classes="nav-buttons"):
                yield Button("Back", id="back")
                yield Button(
                    "Next", variant="primary", id="next"
                )
        yield Footer()

    def _has_custom_path(self) -> bool:
        cfg = self.app.config
        return (
            cfg.startup_script.enabled
            and cfg.startup_script.path
            and cfg.startup_script.path
            != "config/custom-startup.sh"
        )

    def _load_template(self) -> str:
        # Load existing user script if available, otherwise bundled template
        existing_script = DEFAULT_CONFIG_DIR / "custom-startup.sh"
        if existing_script.exists():
            return existing_script.read_text()
        if STARTUP_TEMPLATE_PATH.exists():
            return STARTUP_TEMPLATE_PATH.read_text()
        return "#!/bin/bash\necho 'Custom startup script'\n"

    @on(RadioSet.Changed, "#startup-mode")
    def _mode_changed(self, event: RadioSet.Changed) -> None:
        idx = event.index
        editor = self.query_one("#script-editor", TextArea)
        path_input = self.query_one("#script-path", Input)

        if idx == 0:
            # None
            editor.disabled = True
            path_input.disabled = True
        elif idx == 1:
            # Template
            editor.disabled = False
            path_input.disabled = True
        elif idx == 2:
            # File from disk
            editor.disabled = True
            path_input.disabled = False

    @on(Button.Pressed, "#back")
    def _back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#next")
    def _next(self) -> None:
        cfg = self.app.config
        radio = self.query_one("#startup-mode", RadioSet)
        idx = radio.pressed_index

        error_radio = self.query_one("#on-error", RadioSet)
        cfg.startup_script.on_error = (
            "fail"
            if error_radio.pressed_index == 1
            else "continue"
        )

        if idx == 0:
            # Disabled
            cfg.startup_script.enabled = False
            cfg.startup_script.path = ""
            self.app._startup_script_content = None
        elif idx == 1:
            # Template — save editor content
            cfg.startup_script.enabled = True
            cfg.startup_script.path = (
                "config/custom-startup.sh"
            )
            editor = self.query_one(
                "#script-editor", TextArea
            )
            self.app._startup_script_content = editor.text
        elif idx == 2:
            # File from disk — read content, normalize path
            local_path = self.query_one(
                "#script-path", Input
            ).value.strip()
            try:
                self.app._startup_script_content = (
                    Path(local_path).read_text()
                )
                cfg.startup_script.enabled = True
                cfg.startup_script.path = (
                    "config/custom-startup.sh"
                )
            except (FileNotFoundError, OSError):
                cfg.startup_script.enabled = False
                self.app._startup_script_content = None

        self.app.push_screen(ReviewScreen())


# ---------------------------------------------------------------------------
# Screen 6: Review & Save
# ---------------------------------------------------------------------------
class ReviewScreen(Screen):
    """Review configuration and save."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 6 of 6: Review & Save",
                classes="step-title",
            )
            yield TextArea(
                id="review-yaml",
                read_only=True,
                language="yaml",
            )
            yield Label(
                "", id="save-path-label",
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

        self.query_one("#save-path-label", Label).update(
            f"Config will be saved to: {self.app.save_path}"
        )

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
        save_path = self.app.save_path
        save_config(self.app.config, save_path)

        # Write startup script if provided
        content = getattr(
            self.app, "_startup_script_content", None
        )
        if content:
            script_path = (
                save_path.parent / "custom-startup.sh"
            )
            script_path.write_text(content)
            script_path.chmod(0o755)

        self.app.exit(
            message=f"Config saved to {save_path}"
        )


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

    def __init__(
        self,
        existing_config: Config | None = None,
        save_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.config = existing_config if existing_config else Config()
        self.save_path = save_path or DEFAULT_CONFIG_PATH
        self._startup_script_content: str | None = None

    def on_mount(self) -> None:
        self.push_screen(DeploymentScreen())
