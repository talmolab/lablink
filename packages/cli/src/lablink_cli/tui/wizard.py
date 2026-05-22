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
                "Step 1: Deployment Identity",
                classes="step-title",
            )
            yield Label(
                "Name your lab (e.g., 'sleap-lablink' for a SLEAP course).\n"
                "This prevents resource conflicts if multiple labs "
                "share the same AWS account.",
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

        self.app.push_screen(ProviderScreen())


# ---------------------------------------------------------------------------
# Screen 2: Provider (AWS vs Manual BYO)
# ---------------------------------------------------------------------------
class ProviderScreen(Screen):
    """Choose the VM provisioning provider."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def action_back(self) -> None:
        self.app.pop_screen()

    def compose(self) -> ComposeResult:
        cfg = self.app.config
        current = getattr(cfg, "provider", "aws") or "aws"

        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 2: Provider",
                classes="step-title",
            )
            yield Label(
                "Choose how client VMs are provisioned.\n"
                "AWS provisions EC2 instances via Terraform.\n"
                "Manual (BYO) skips provisioning — you supply Linux GPU\n"
                "boxes that register themselves with `lablink register`.",
                classes="step-description",
            )

            yield Label("Provider", classes="field-label")
            with RadioSet(id="provider-select"):
                yield RadioButton(
                    "aws — AWS EC2 (default)",
                    value=(current == "aws"),
                    id="provider-aws",
                )
                yield RadioButton(
                    "manual — Bring-Your-Own boxes",
                    value=(current == "manual"),
                    id="provider-manual",
                )

        with Center():
            with Horizontal(classes="nav-buttons"):
                yield Button("Back", id="back")
                yield Button("Next", variant="primary", id="next")
        yield Footer()

    @on(Button.Pressed, "#back")
    def _back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#next")
    def _next(self) -> None:
        cfg = self.app.config
        rb = self.query_one("#provider-select", RadioSet)
        chosen = "aws"
        if rb.pressed_button and rb.pressed_button.id == "provider-manual":
            chosen = "manual"
        cfg.provider = chosen

        if chosen == "manual":
            # For manual, force ssl.provider to a supported value if it
            # was previously set to a public-TLS option.
            if cfg.ssl.provider in ("letsencrypt", "acm", "cloudflare"):
                cfg.ssl.provider = "none"
            # Reset the image to the manual default if the user is still on the
            # AWS schema default. Manual BYO uses lablink-client; AWS path uses
            # lablink-client-base-image baked into the GPU AMI.
            aws_image_default = "ghcr.io/talmolab/lablink-client-base-image:latest"
            if not cfg.machine.image or cfg.machine.image == aws_image_default:
                cfg.machine.image = ManualMachineScreen.DEFAULT_IMAGE
            self.app.push_screen(ManualMachineScreen())
        else:
            self.app.push_screen(RegionScreen())


# ---------------------------------------------------------------------------
# Screen 3 (Manual path only): Client image
# ---------------------------------------------------------------------------
class ManualMachineScreen(Screen):
    """Configure the client Docker image for manual (BYO) deployments."""

    BINDINGS = [Binding("escape", "back", "Back")]

    DEFAULT_IMAGE = "ghcr.io/talmolab/lablink-client:0.4.0"

    def action_back(self) -> None:
        self.app.pop_screen()

    def compose(self) -> ComposeResult:
        cfg = self.app.config
        current_image = cfg.machine.image or self.DEFAULT_IMAGE

        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 3: Client image",
                classes="step-title",
            )
            yield Label(
                "Docker image that BYO boxes will pull and run after "
                "they register. Defaults to the latest published image.",
                classes="step-description",
            )
            yield Label("Client image", classes="field-label")
            yield Input(
                value=current_image,
                placeholder=self.DEFAULT_IMAGE,
                id="client-image",
            )
        with Center():
            with Horizontal(classes="nav-buttons"):
                yield Button("Back", id="back")
                yield Button("Next", variant="primary", id="next")
        yield Footer()

    @on(Button.Pressed, "#back")
    def _back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#next")
    def _next(self) -> None:
        cfg = self.app.config
        image = self.query_one("#client-image", Input).value.strip()
        cfg.machine.image = image or self.DEFAULT_IMAGE
        # Skip Region + Machine instance-type + EIP — go straight to DNS/SSL
        self.app.push_screen(DnsScreen())


# ---------------------------------------------------------------------------
# Screen 2 (AWS path): AWS Region
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
                "Step 2: AWS Region", classes="step-title"
            )
            yield Label(
                "Select the AWS region closest to your students.\n"
                "This affects latency and VM availability.",
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
                "Step 3: Machine Configuration",
                classes="step-title",
            )
            yield Label(
                "Select the instance type for student VMs. "
                "GPU instances are recommended for ML workloads.\n"
                "Docs: https://aws.amazon.com/ec2/instance-types/",
                classes="step-description",
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

            yield Label(
                "Software Name (the tool students will use)",
                classes="field-label",
            )
            yield Input(
                value=cfg.machine.software or "",
                placeholder="e.g. sleap, deeplabcut, napari",
                id="software",
            )

            yield Label(
                "Git Repository (course materials cloned into each VM)",
                classes="field-label",
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
        repository = self.query_one("#repository", Input).value

        if software:
            self.app.config.machine.software = software
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

    PROVIDER_BY_BUTTON_ID = {
        "dns-none": "none",
        "dns-letsencrypt": "letsencrypt",
        "dns-cloudflare": "cloudflare",
        "dns-acm": "acm",
        "dns-self_signed": "self_signed",
    }

    def compose(self) -> ComposeResult:
        cfg = self.app.config

        # Determine which radio button to pre-select.
        # Indices follow AWS-style ordering (0..4); when manual provider is
        # selected we hide indices 1..3 but the same numbering is used
        # for the value-checking logic below.
        if not cfg.dns.enabled and cfg.ssl.provider == "self_signed":
            default_idx = 4
        elif not cfg.dns.enabled:
            default_idx = 0
        elif cfg.ssl.provider == "letsencrypt":
            default_idx = 1
        elif cfg.ssl.provider == "cloudflare":
            default_idx = 2
        elif cfg.ssl.provider == "acm":
            default_idx = 3
        else:
            default_idx = 0

        is_manual = getattr(cfg, "provider", "aws") == "manual"

        # Initial disabled state for the three text inputs, computed from
        # the pre-selected provider (after manual filtering).
        if default_idx == 1 and not is_manual:
            domain_disabled = False
            email_disabled = False
            acm_disabled = True
        elif default_idx == 2 and not is_manual:
            domain_disabled = False
            email_disabled = True
            acm_disabled = True
        elif default_idx == 3 and not is_manual:
            domain_disabled = False
            email_disabled = True
            acm_disabled = False
        else:
            domain_disabled = True
            email_disabled = True
            acm_disabled = True

        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 4: DNS & SSL", classes="step-title"
            )

            yield Label("Access Method", classes="field-label")
            with RadioSet(id="dns-mode"):
                yield RadioButton(
                    "IP Only — simplest setup, access via IP, no SSL",
                    value=(default_idx == 0),
                    id="dns-none",
                )
                if not is_manual:
                    yield RadioButton(
                        "Let's Encrypt — free automatic SSL, requires a "
                        "domain (https://letsencrypt.org/)",
                        value=(default_idx == 1),
                        id="dns-letsencrypt",
                    )
                    yield RadioButton(
                        "CloudFlare — use if your domain is already on "
                        "CloudFlare (https://www.cloudflare.com/application-services/products/ssl/)",
                        value=(default_idx == 2),
                        id="dns-cloudflare",
                    )
                    yield RadioButton(
                        "AWS ACM — AWS-managed SSL with load balancer, "
                        "requires certificate "
                        "(https://docs.aws.amazon.com/acm/latest/userguide/acm-overview.html)",
                        value=(default_idx == 3),
                        id="dns-acm",
                    )
                yield RadioButton(
                    "Self-signed — browser warns once; fine for closed-LAN labs",
                    value=(default_idx == 4),
                    id="dns-self_signed",
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
                disabled=domain_disabled,
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
                disabled=email_disabled,
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
                disabled=acm_disabled,
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
        provider = self.PROVIDER_BY_BUTTON_ID.get(event.pressed.id, "none")

        domain_input = self.query_one("#domain", Input)
        email_input = self.query_one("#ssl-email", Input)
        acm_input = self.query_one("#acm-arn", Input)

        domain_needed = provider in ("letsencrypt", "cloudflare", "acm")
        email_needed = provider == "letsencrypt"
        acm_needed = provider == "acm"

        domain_input.disabled = not domain_needed
        email_input.disabled = not email_needed
        acm_input.disabled = not acm_needed

    @on(Button.Pressed, "#back")
    def _back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#next")
    def _next(self) -> None:
        radio = self.query_one("#dns-mode", RadioSet)
        pressed_button = getattr(radio, "pressed_button", None)
        if pressed_button is not None:
            pressed_id = pressed_button.id
        else:
            # Fallback for older Textual: find the button with value=True
            pressed_id = "dns-none"
            for btn in radio.query(RadioButton):
                if btn.value:
                    pressed_id = btn.id
                    break
        provider = self.PROVIDER_BY_BUTTON_ID.get(pressed_id, "none")
        cfg = self.app.config

        domain = self.query_one("#domain", Input).value
        email = self.query_one("#ssl-email", Input).value
        acm_arn = self.query_one("#acm-arn", Input).value

        if provider == "none":
            cfg.dns.enabled = False
            cfg.ssl.provider = "none"
            cfg.eip.strategy = "dynamic"
        elif provider == "letsencrypt":
            cfg.dns.enabled = True
            cfg.dns.terraform_managed = True
            cfg.dns.domain = domain
            cfg.ssl.provider = "letsencrypt"
            cfg.ssl.email = email
            cfg.eip.strategy = "dynamic"
        elif provider == "cloudflare":
            cfg.dns.enabled = True
            cfg.dns.terraform_managed = False
            cfg.dns.domain = domain
            cfg.ssl.provider = "cloudflare"
            cfg.eip.strategy = "dynamic"
        elif provider == "acm":
            cfg.dns.enabled = True
            cfg.dns.terraform_managed = True
            cfg.dns.domain = domain
            cfg.ssl.provider = "acm"
            cfg.ssl.certificate_arn = acm_arn
            cfg.eip.strategy = "dynamic"
        elif provider == "self_signed":
            cfg.dns.enabled = False
            cfg.ssl.provider = "self_signed"
            cfg.eip.strategy = "dynamic"

        is_manual = getattr(cfg, "provider", "aws") == "manual"
        if is_manual:
            self.app.push_screen(ReviewScreen())
        else:
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
                "Step 5: Client Startup Script",
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
            yield Button(
                "Check path",
                id="check-path",
                disabled=not is_file,
            )
            yield Label(
                "",
                id="path-status",
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

        check_btn = self.query_one("#check-path", Button)
        if idx == 0:
            # None
            editor.disabled = True
            path_input.disabled = True
            check_btn.disabled = True
        elif idx == 1:
            # Template
            editor.disabled = False
            path_input.disabled = True
            check_btn.disabled = True
        elif idx == 2:
            # File from disk
            editor.disabled = True
            path_input.disabled = False
            check_btn.disabled = False

    @on(Button.Pressed, "#check-path")
    def _check_path(self) -> None:
        path_input = self.query_one("#script-path", Input)
        status = self.query_one("#path-status", Label)
        local_path = path_input.value.strip()
        if not local_path:
            status.update("No path entered.")
            return
        p = Path(local_path)
        if not p.exists():
            status.update(f"Not found: {local_path}")
        elif not p.is_file():
            status.update(f"Not a file: {local_path}")
        else:
            status.update(f"Found: {local_path}")

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
                "Step 6: Review & Save",
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
    #check-path {
        margin: 1 2;
    }
    #path-status {
        margin: 0 2;
        color: $text-muted;
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
