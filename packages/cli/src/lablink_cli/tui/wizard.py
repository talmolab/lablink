"""Textual TUI wizard for generating LabLink config."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Horizontal, VerticalScroll
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
                "boxes that register themselves with `lablink client register`.",
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
            if not cfg.machine.image:
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

    DEFAULT_IMAGE = "ghcr.io/talmolab/lablink-client-base-image:latest"

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
        # Skip Region + Machine instance-type + EIP — go to connectivity.
        self.app.push_screen(ManualConnectivityScreen())


# ---------------------------------------------------------------------------
# Screen 4 (Manual path only): Client connectivity
# ---------------------------------------------------------------------------
class ManualConnectivityScreen(Screen):
    """How the student's browser reaches a manual client's KasmVNC desktop."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def action_back(self) -> None:
        self.app.pop_screen()

    def compose(self) -> ComposeResult:
        cfg = self.app.config
        current = getattr(cfg.manual, "connectivity", "lan_direct") or "lan_direct"

        yield Header()
        with VerticalScroll():
            # No "Step N:" prefix here deliberately — DnsScreen (the next
            # screen on this path) hardcodes "Step 4: DNS & SSL" and is
            # shared with the AWS path, so inserting a step between it and
            # ManualMachineScreen's "Step 3" would collide with that label
            # rather than shifting it. Renumbering DnsScreen is out of
            # scope here (it's shared, and the AWS path already has its
            # own pre-existing step-count drift across RegionScreen/
            # MachineScreen).
            yield Label(
                "Client connectivity",
                classes="step-title",
            )
            yield Label(
                "How the student's browser reaches a client's KasmVNC desktop.\n"
                "lan_direct: the client is on the allocator's own LAN (default).\n"
                "mesh_overlay: the client isn't on the allocator's LAN (e.g. a\n"
                "Run:AI-hosted workload) — reached over a Tailscale tailnet instead.",
                classes="step-description",
            )

            yield Label("Connectivity", classes="field-label")
            with RadioSet(id="connectivity-select"):
                yield RadioButton(
                    "lan_direct — client is on the allocator's LAN (default)",
                    value=(current == "lan_direct"),
                    id="connectivity-lan-direct",
                )
                yield RadioButton(
                    "mesh_overlay — client reached over Tailscale",
                    value=(current == "mesh_overlay"),
                    id="connectivity-mesh-overlay",
                )

            yield Label(
                "Tailscale tailnet domain (only used for mesh_overlay, "
                "e.g. example.ts.net)",
                classes="field-label",
            )
            yield Input(
                value=cfg.manual.overlay_tailnet or "",
                placeholder="example.ts.net",
                id="overlay-tailnet",
            )
            yield Label("", id="connectivity-error", classes="error")
        with Center():
            with Horizontal(classes="nav-buttons"):
                yield Button("Back", id="back")
                yield Button("Next", variant="primary", id="next")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#connectivity-error").display = False

    @on(Button.Pressed, "#back")
    def _back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#next")
    def _next(self) -> None:
        cfg = self.app.config
        rb = self.query_one("#connectivity-select", RadioSet)
        chosen = "lan_direct"
        if rb.pressed_button and rb.pressed_button.id == "connectivity-mesh-overlay":
            chosen = "mesh_overlay"
        cfg.manual.connectivity = chosen
        cfg.manual.overlay_tailnet = self.query_one(
            "#overlay-tailnet", Input
        ).value.strip()

        errors = [
            e for e in validate_config(cfg)
            if "connectivity" in e or "overlay_tailnet" in e
        ]
        error_label = self.query_one("#connectivity-error", Label)
        if errors:
            error_label.update("\n".join(errors))
            error_label.display = True
            return
        error_label.display = False

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

            # Mode toggle (Guided default, Advanced opt-in).
            with RadioSet(id="dns-screen-mode"):
                yield RadioButton(
                    "Guided — common presets",
                    value=True,
                    id="screen-mode-guided",
                )
                yield RadioButton(
                    "Advanced — edit every field directly",
                    value=False,
                    id="screen-mode-advanced",
                )

            with Container(id="dns-guided"):
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

                tag = (
                    f"{cfg.deployment_name or '<deployment_name>'}"
                    f"-eip-"
                    f"{cfg.environment or '<environment>'}"
                )
                yield Label(
                    "Persistent EIP required for Cloudflare.\n"
                    "Tag your pre-allocated EIP with:\n"
                    f"  Name = {tag}\n"
                    "Example:\n"
                    "  aws ec2 create-tags --resources eipalloc-XXXXX \\\n"
                    f"    --tags Key=Name,Value={tag}",
                    id="eip-help",
                    classes="step-description",
                )

            with Container(id="dns-advanced"):
                yield Label(
                    "Advanced — direct config edit. "
                    "Values from current config are pre-filled.",
                    classes="step-description",
                )

                yield Label("DNS", classes="field-label")

                yield Label("Enabled", classes="field-label")
                with RadioSet(id="adv-dns-enabled"):
                    yield RadioButton(
                        "Yes",
                        value=cfg.dns.enabled,
                        id="adv-dns-enabled-yes",
                    )
                    yield RadioButton(
                        "No",
                        value=not cfg.dns.enabled,
                        id="adv-dns-enabled-no",
                    )

                yield Label(
                    "Terraform-managed records",
                    classes="field-label",
                )
                with RadioSet(id="adv-dns-tfmanaged"):
                    yield RadioButton(
                        "Yes",
                        value=cfg.dns.terraform_managed,
                        id="adv-dns-tfmanaged-yes",
                    )
                    yield RadioButton(
                        "No",
                        value=not cfg.dns.terraform_managed,
                        id="adv-dns-tfmanaged-no",
                    )

                yield Label("Domain", classes="field-label")
                yield Input(
                    value=cfg.dns.domain or "",
                    placeholder="lablink.example.com",
                    id="adv-dns-domain",
                )

                yield Label(
                    "Zone ID (optional)", classes="field-label"
                )
                yield Input(
                    value=cfg.dns.zone_id or "",
                    placeholder="Z0123456789ABCDEFG",
                    id="adv-dns-zone-id",
                )

                yield Label("SSL", classes="field-label")
                yield Label("Provider", classes="field-label")
                with RadioSet(id="adv-ssl-provider"):
                    yield RadioButton(
                        "none",
                        value=(cfg.ssl.provider == "none"),
                        id="adv-ssl-none",
                    )
                    yield RadioButton(
                        "letsencrypt",
                        value=(cfg.ssl.provider == "letsencrypt"),
                        id="adv-ssl-letsencrypt",
                    )
                    yield RadioButton(
                        "cloudflare",
                        value=(cfg.ssl.provider == "cloudflare"),
                        id="adv-ssl-cloudflare",
                    )
                    yield RadioButton(
                        "acm",
                        value=(cfg.ssl.provider == "acm"),
                        id="adv-ssl-acm",
                    )
                    yield RadioButton(
                        "self_signed",
                        value=(cfg.ssl.provider == "self_signed"),
                        id="adv-ssl-self_signed",
                    )

                yield Label("Email", classes="field-label")
                yield Input(
                    value=cfg.ssl.email or "",
                    placeholder="admin@example.com",
                    id="adv-ssl-email",
                )

                yield Label(
                    "ACM Certificate ARN", classes="field-label"
                )
                yield Input(
                    value=cfg.ssl.certificate_arn or "",
                    placeholder=(
                        "arn:aws:acm:region:account:certificate/id"
                    ),
                    id="adv-ssl-acm-arn",
                )

                yield Label("EIP", classes="field-label")
                yield Label("Strategy", classes="field-label")
                with RadioSet(id="adv-eip-strategy"):
                    yield RadioButton(
                        "dynamic",
                        value=(cfg.eip.strategy == "dynamic"),
                        id="adv-eip-dynamic",
                    )
                    yield RadioButton(
                        "persistent",
                        value=(cfg.eip.strategy == "persistent"),
                        id="adv-eip-persistent",
                    )

                tag = (
                    f"{cfg.deployment_name or '<deployment_name>'}"
                    f"-eip-"
                    f"{cfg.environment or '<environment>'}"
                )
                yield Label(
                    "Persistent EIP requires a pre-allocated EIP tagged:\n"
                    f"  Name = {tag}",
                    id="adv-eip-help",
                    classes="step-description",
                )

                yield Label(
                    "",
                    id="dns-validation-error",
                    classes="step-description",
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

        # Toggle EIP-help visibility with the selected provider.
        self.query_one("#eip-help").display = (provider == "cloudflare")

    @on(RadioSet.Changed, "#dns-screen-mode")
    def _screen_mode_changed(self, event: RadioSet.Changed) -> None:
        is_advanced = event.pressed.id == "screen-mode-advanced"
        if is_advanced:
            # Save the Guided state to cfg so Advanced sees the latest.
            self._save_guided()
            self._refresh_advanced_from_cfg()
        else:
            # Going from Advanced back to Guided: save Advanced first.
            self._save_advanced()
            self._refresh_guided_from_cfg()
        self.query_one("#dns-guided").display = not is_advanced
        self.query_one("#dns-advanced").display = is_advanced

    def _refresh_advanced_from_cfg(self) -> None:
        cfg = self.app.config

        def _select(radioset_id: str, button_id: str) -> None:
            # We're called from RadioSet message handlers which run with
            # `prevent(RadioButton.Changed)` active, so simply setting
            # button.value won't propagate through RadioSet's single-selection
            # logic. Mutate values directly and update the RadioSet's
            # `_pressed_button` so callers see consistent state.
            radio_set = self.query_one(radioset_id, RadioSet)
            target: RadioButton | None = None
            for btn in radio_set.query(RadioButton):
                if btn.id == button_id:
                    target = btn
                else:
                    if btn.value:
                        btn.value = False
            if target is not None:
                target.value = True
                radio_set._pressed_button = target

        _select(
            "#adv-dns-enabled",
            "adv-dns-enabled-yes"
            if cfg.dns.enabled
            else "adv-dns-enabled-no",
        )
        _select(
            "#adv-dns-tfmanaged",
            "adv-dns-tfmanaged-yes"
            if cfg.dns.terraform_managed
            else "adv-dns-tfmanaged-no",
        )
        self.query_one("#adv-dns-domain").value = (
            cfg.dns.domain or ""
        )
        self.query_one("#adv-dns-zone-id").value = (
            cfg.dns.zone_id or ""
        )
        _select(
            "#adv-ssl-provider",
            {
                "none": "adv-ssl-none",
                "letsencrypt": "adv-ssl-letsencrypt",
                "cloudflare": "adv-ssl-cloudflare",
                "acm": "adv-ssl-acm",
                "self_signed": "adv-ssl-self_signed",
            }.get(cfg.ssl.provider, "adv-ssl-none"),
        )
        self.query_one("#adv-ssl-email").value = cfg.ssl.email or ""
        self.query_one("#adv-ssl-acm-arn").value = (
            cfg.ssl.certificate_arn or ""
        )
        _select(
            "#adv-eip-strategy",
            "adv-eip-persistent"
            if cfg.eip.strategy == "persistent"
            else "adv-eip-dynamic",
        )
        self.query_one("#adv-eip-help").display = (
            cfg.eip.strategy == "persistent"
        )

    def _refresh_guided_from_cfg(self) -> None:
        cfg = self.app.config
        self.query_one("#domain").value = cfg.dns.domain or ""
        self.query_one("#ssl-email").value = cfg.ssl.email or ""
        self.query_one("#acm-arn").value = (
            cfg.ssl.certificate_arn or ""
        )

        target_id = {
            "none": "dns-none",
            "letsencrypt": "dns-letsencrypt",
            "cloudflare": "dns-cloudflare",
            "acm": "dns-acm",
            "self_signed": "dns-self_signed",
        }.get(cfg.ssl.provider, "dns-none")
        if not cfg.dns.enabled and cfg.ssl.provider == "self_signed":
            target_id = "dns-self_signed"
        elif not cfg.dns.enabled and cfg.ssl.provider == "none":
            target_id = "dns-none"
        # Same caveat as `_refresh_advanced_from_cfg._select`: this runs from
        # inside a RadioSet message handler with RadioButton.Changed prevented,
        # so we mutate values directly and reset `_pressed_button`.
        dns_mode = self.query_one("#dns-mode", RadioSet)
        target: RadioButton | None = None
        for btn in dns_mode.query(RadioButton):
            if btn.id == target_id:
                target = btn
            else:
                if btn.value:
                    btn.value = False
        if target is not None:
            target.value = True
            dns_mode._pressed_button = target
        self.query_one("#eip-help").display = (
            cfg.ssl.provider == "cloudflare"
        )

    @on(RadioSet.Changed, "#adv-eip-strategy")
    def _adv_eip_changed(self, event: RadioSet.Changed) -> None:
        self.query_one("#adv-eip-help").display = (
            event.pressed.id == "adv-eip-persistent"
        )

    def on_mount(self) -> None:
        cfg = self.app.config
        is_cloudflare = (
            cfg.dns.enabled
            and cfg.ssl.provider == "cloudflare"
        )
        self.query_one("#eip-help").display = is_cloudflare
        self.query_one("#dns-guided").display = True
        self.query_one("#dns-advanced").display = False
        self.query_one("#adv-eip-help").display = (
            cfg.eip.strategy == "persistent"
        )
        self.query_one("#dns-validation-error").display = False

    @on(Button.Pressed, "#back")
    def _back(self) -> None:
        self.app.pop_screen()

    def _save_guided(self) -> None:
        radio = self.query_one("#dns-mode", RadioSet)
        pressed_button = getattr(radio, "pressed_button", None)
        if pressed_button is not None:
            pressed_id = pressed_button.id
        else:
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
            cfg.eip.strategy = "persistent"
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

    def _save_advanced(self) -> None:
        cfg = self.app.config

        def _selected_id(radioset_id: str) -> str:
            for btn in self.query_one(radioset_id).query(RadioButton):
                if btn.value:
                    return btn.id or ""
            return ""

        cfg.dns.enabled = (
            _selected_id("#adv-dns-enabled") == "adv-dns-enabled-yes"
        )
        cfg.dns.terraform_managed = (
            _selected_id("#adv-dns-tfmanaged")
            == "adv-dns-tfmanaged-yes"
        )
        cfg.dns.domain = self.query_one("#adv-dns-domain").value
        cfg.dns.zone_id = self.query_one("#adv-dns-zone-id").value

        provider_map = {
            "adv-ssl-none": "none",
            "adv-ssl-letsencrypt": "letsencrypt",
            "adv-ssl-cloudflare": "cloudflare",
            "adv-ssl-acm": "acm",
            "adv-ssl-self_signed": "self_signed",
        }
        cfg.ssl.provider = provider_map.get(
            _selected_id("#adv-ssl-provider"), "none"
        )
        cfg.ssl.email = self.query_one("#adv-ssl-email").value
        cfg.ssl.certificate_arn = self.query_one(
            "#adv-ssl-acm-arn"
        ).value

        cfg.eip.strategy = (
            "persistent"
            if _selected_id("#adv-eip-strategy")
            == "adv-eip-persistent"
            else "dynamic"
        )

    @on(Button.Pressed, "#next")
    def _next(self) -> None:
        from lablink_cli.config.schema import validate_config

        is_advanced = self.query_one("#dns-advanced").display
        if is_advanced:
            self._save_advanced()
        else:
            self._save_guided()

        if is_advanced:
            errors = validate_config(self.app.config)
            if errors:
                err_label = self.query_one("#dns-validation-error")
                err_label.update("\n".join(errors))
                err_label.display = True
                return

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

            yield Label(
                "Max attempts", classes="field-label"
            )
            yield Input(
                value=str(cfg.startup_script.max_attempts),
                type="integer",
                id="max-attempts",
            )

            yield Label(
                "Base delay (seconds)", classes="field-label"
            )
            yield Input(
                value=str(cfg.startup_script.base_delay_seconds),
                type="integer",
                id="base-delay",
            )

            yield Label(
                "Success check command (optional)",
                classes="field-label",
            )
            yield Input(
                value=cfg.startup_script.success_check,
                placeholder=(
                    "e.g. /home/client/.local/bin/sleap --version"
                ),
                id="success-check",
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

        max_attempts_value = self.query_one(
            "#max-attempts", Input
        ).value
        cfg.startup_script.max_attempts = (
            int(max_attempts_value) if max_attempts_value else 3
        )
        base_delay_value = self.query_one(
            "#base-delay", Input
        ).value
        cfg.startup_script.base_delay_seconds = (
            int(base_delay_value) if base_delay_value else 30
        )
        cfg.startup_script.success_check = self.query_one(
            "#success-check", Input
        ).value.strip()

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

        self.app.push_screen(MonitoringScreen())


# ---------------------------------------------------------------------------
# Screen 6: Session Metrics (Tier 1 Monitoring)
# ---------------------------------------------------------------------------
class MonitoringScreen(Screen):
    """Toggle Tier 1 session-metrics collection.

    Single switch only: enabled / disabled. All other MonitoringConfig
    fields (process_allowlist, watch_dir, intervals) keep their dataclass
    defaults — operators who need to customize them still hand-edit
    lablink.yaml. This screen is SLEAP-specific and expected to be
    removed when monitoring is generalized or dropped.
    """

    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        cfg = self.app.config

        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 6: Session Metrics (optional)",
                classes="step-title",
            )
            yield Label(
                "Collect anonymous per-VM session metrics "
                "(Tier 1 monitoring). Currently SLEAP-tuned — leave "
                "disabled for non-SLEAP workloads.",
                classes="step-description",
            )

            yield Label("Session metrics", classes="field-label")
            with RadioSet(id="monitoring-mode"):
                yield RadioButton(
                    "Disabled (default)",
                    value=not cfg.monitoring.enabled,
                )
                yield RadioButton(
                    "Enabled",
                    value=cfg.monitoring.enabled,
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
        radio = self.query_one("#monitoring-mode", RadioSet)
        cfg.monitoring.enabled = radio.pressed_index == 1
        self.app.push_screen(ReviewScreen())


# ---------------------------------------------------------------------------
# Screen 7: Review & Save
# ---------------------------------------------------------------------------
class ReviewScreen(Screen):
    """Review configuration and save."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Label(
                "Step 7: Review & Save",
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
    VerticalScroll {
        height: 1fr;
    }
    #dns-guided, #dns-advanced {
        height: auto;
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
