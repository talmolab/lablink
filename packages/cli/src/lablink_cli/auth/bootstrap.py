"""First-time Identity Center setup — the console handoff flow.

This drives the user through enabling Identity Center, creating
themselves a user, creating the lablink permission set, and assigning
the user to the AWS account. All steps happen in the AWS Console;
this module just opens the right URLs, prompts for the SSO Start URL,
and writes ~/.aws/config.
"""

from __future__ import annotations

import configparser
import json
import os
import re
import webbrowser
from dataclasses import dataclass, field, asdict
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from lablink_cli.auth import policy
from lablink_cli.auth.utils import aws_config_path

console = Console()

# Identity Center console URL. We don't deep-link to /permissionsets/create
# or /aws-accounts because those hash-routed URLs are unstable across AWS
# console releases (they fail with "Cannot read properties of undefined
# (reading 'noHash')" if the SPA isn't initialized yet). The textual copy
# in each _step_ function below tells the user where to navigate from home.
IDENTITY_CENTER_CONSOLE_URL = "https://console.aws.amazon.com/singlesignon/home"
CREATE_PERMISSION_SET_URL = IDENTITY_CENTER_CONSOLE_URL
ASSIGN_USERS_URL = IDENTITY_CENTER_CONSOLE_URL

# Matches https://d-XXXXXXXXXX.awsapps.com/start or
# https://<alias>.awsapps.com/start
_SSO_URL_RE = re.compile(
    r"^https://(?:d-[a-z0-9]{10}|[a-z0-9-]+)\.awsapps\.com/start/?$"
)


@dataclass
class SSOBootstrapResult:
    start_url: str
    sso_region: str
    permission_set_name: str
    deployment_region: str


@dataclass
class BootstrapState:
    """Bootstrap progress, persisted to ~/.lablink/bootstrap-state.json.

    Resumability is purely file-based: instances do not hold a file
    handle. `load` / `save` / `clear` operate on the well-known path
    each time, so a Ctrl-C between steps simply leaves the file behind
    for the next invocation to pick up.
    """

    sso_start_url: str
    sso_region: str
    permission_set_name: str
    steps_complete: list[str] = field(default_factory=list)

    @classmethod
    def path(cls) -> Path:
        """Return the on-disk location of the persisted state."""
        home = Path(os.environ.get("HOME", str(Path.home())))
        return home / ".lablink" / "bootstrap-state.json"

    @classmethod
    def load(cls) -> "BootstrapState | None":
        """Read state from disk. Returns None if missing or corrupt."""
        path = cls.path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return cls(**data)
        except (json.JSONDecodeError, TypeError, OSError):
            return None

    def save(self) -> None:
        """Persist this state to disk, creating parent dirs as needed."""
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def clear(cls) -> None:
        """Remove the persisted state file if it exists."""
        path = cls.path()
        if path.exists():
            path.unlink()


def _is_valid_sso_start_url(url: str) -> bool:
    return bool(_SSO_URL_RE.match(url.strip()))


def _extract_region_from_url(url: str) -> str | None:
    """Identity Center start URLs don't encode region; return None."""
    return None


def _write_aws_config(result: SSOBootstrapResult) -> None:
    """Write [sso-session lablink] and [profile lablink] without clobbering others."""
    config_path = aws_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    parser = configparser.ConfigParser()
    if config_path.exists():
        parser.read(config_path)

    sso_session_section = "sso-session lablink"
    profile_section = "profile lablink"

    if sso_session_section not in parser.sections():
        parser.add_section(sso_session_section)
    parser.set(sso_session_section, "sso_start_url", result.start_url)
    parser.set(sso_session_section, "sso_region", result.sso_region)
    parser.set(sso_session_section, "sso_registration_scopes", "sso:account:access")

    if profile_section not in parser.sections():
        parser.add_section(profile_section)
    parser.set(profile_section, "sso_session", "lablink")
    parser.set(profile_section, "sso_role_name", result.permission_set_name)
    parser.set(profile_section, "region", result.deployment_region)

    with open(config_path, "w") as fp:
        parser.write(fp)


def _pyperclip_copy(text: str) -> None:
    """Wrapped for testability — patch this to simulate pyperclip failures."""
    import pyperclip

    pyperclip.copy(text)


def _copy_to_clipboard(payload: str) -> Path | None:
    """Copy payload to clipboard. On failure, write to a file and return its path."""
    try:
        _pyperclip_copy(payload)
        return None
    except Exception:
        home = Path(os.environ.get("HOME", str(Path.home())))
        out = home / ".lablink" / "permission-set-policy.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload)
        return out


def _step_enable_identity_center() -> tuple[str, str]:
    """Walk the user through enabling Identity Center. Returns (start_url, region)."""
    console.print(
        Panel(
            "Welcome to LabLink. It looks like this is your first login.\n"
            "Setup takes about 5 minutes and only happens once.\n\n"
            "You will:\n"
            "  1. Enable AWS Identity Center in your AWS account\n"
            "  2. Create yourself a user (your name, email, password)\n"
            "  3. Attach the LabLink permission set to your user\n\n"
            "You'll need an authenticator app on your phone (Authy, Google\n"
            "Authenticator, 1Password) for the password setup step — Identity\n"
            "Center enforces MFA.",
            title="First-time setup",
            border_style="cyan",
        )
    )
    input("Press Enter to open the AWS Console in your browser...")
    webbrowser.open(IDENTITY_CENTER_CONSOLE_URL)

    console.print(
        "\nIn the AWS Console:\n"
        "  1. Click [bold]Enable[/bold]. (If asked, choose "
        "[bold]account instance[/bold] for personal accounts — either works.)\n"
        "  2. Wait ~30 seconds for it to provision.\n"
        "  3. In the left sidebar, click [bold]Users[/bold] → "
        "[bold]Add user[/bold].\n"
        "  4. Fill in your name + email and submit.\n"
        "  5. Check your email for the [bold]Accept invitation[/bold] link; "
        "set a password and MFA.\n"
        "  6. Return to the Identity Center home (the page you opened in step 1).\n"
        "  7. Copy the [bold]SSO Start URL[/bold] from the "
        "[bold]AWS access portal URLs[/bold] section on the dashboard.\n"
    )

    while True:
        start_url = typer.prompt("SSO Start URL")
        if _is_valid_sso_start_url(start_url):
            break
        console.print(
            "[red]That doesn't look like an SSO Start URL.[/red] "
            "Expected something like https://d-9067abc123.awsapps.com/start"
        )

    sso_region = typer.prompt(
        "AWS region where Identity Center is enabled",
        default="us-east-1",
    )
    return start_url.strip(), sso_region.strip()


def _step_create_permission_set() -> str:
    """Walk the user through creating the lablink permission set."""
    payload = policy.render_inline_policy_json()
    fallback_path = _copy_to_clipboard(payload)

    if fallback_path is None:
        clipboard_msg = (
            "The required policy JSON has been [bold]copied to your clipboard[/bold]."
        )
    else:
        clipboard_msg = (
            f"Your system doesn't have a clipboard, so the policy JSON was "
            f"saved to:\n  [bold]{fallback_path}[/bold]\n"
            "Open that file and copy its contents."
        )

    console.print(
        f"\nNow we need a Permission Set — this controls what LabLink can do.\n"
        f"{clipboard_msg}\n"
    )
    input("Press Enter to open the Identity Center console...")
    webbrowser.open(CREATE_PERMISSION_SET_URL)

    console.print(
        "\nIn the AWS Console:\n"
        "  1. In the left sidebar, find [bold]Permission sets[/bold]. "
        "(In newer consoles it's nested under "
        "[bold]Multi-account permissions[/bold] — expand that first.)\n"
        "  2. Click the [bold]Create permission set[/bold] button on the "
        "Permission sets page.\n"
        "  3. Choose [bold]Custom permission set[/bold] and click "
        "[bold]Next[/bold].\n"
        "  4. Under [bold]AWS managed policies[/bold], search for and "
        "attach each of:\n"
    )
    for arn in policy.MANAGED_POLICY_ARNS:
        name = arn.split("/")[-1]
        console.print(f"     • {name}")
    console.print(
        "  5. Expand [bold]Custom inline policy[/bold], paste from "
        "clipboard (Ctrl/Cmd-V), then click [bold]Next[/bold].\n"
        "  6. Name it [bold]lablink[/bold] (or your preference) and click "
        "[bold]Next[/bold] → [bold]Create[/bold].\n"
    )

    permission_set_name = typer.prompt(
        "What did you name the permission set?",
        default=policy.PERMISSION_SET_NAME_DEFAULT,
    )
    input("Press Enter once the permission set is created...")
    return permission_set_name.strip()


def _step_assign_user(permission_set_name: str) -> None:
    console.print(
        f"\nLast step — assign your user to your AWS account with the "
        f"[bold]{permission_set_name}[/bold] permission set.\n"
    )
    input("Press Enter to open the Identity Center console...")
    webbrowser.open(ASSIGN_USERS_URL)

    console.print(
        "\nIn the AWS Console:\n"
        "  1. In the left sidebar, find [bold]AWS accounts[/bold]. "
        "(In newer consoles it's nested under "
        "[bold]Multi-account permissions[/bold] — expand that first.)\n"
        "  2. Check the box next to your AWS account.\n"
        "  3. Click [bold]Assign users or groups[/bold].\n"
        "  4. On the [bold]Users[/bold] tab, select your user, click "
        "[bold]Next[/bold].\n"
        f"  5. Select the [bold]{permission_set_name}[/bold] permission set, "
        "click [bold]Next[/bold].\n"
        "  6. Click [bold]Submit[/bold].\n"
    )
    input("Press Enter when done...")


def run_bootstrap(*, deployment_region: str) -> SSOBootstrapResult:
    """Run the full first-time bootstrap flow with resumability."""
    state = BootstrapState.load()

    if state is None:
        start_url, sso_region = _step_enable_identity_center()
        state = BootstrapState(
            sso_start_url=start_url,
            sso_region=sso_region,
            permission_set_name=policy.PERMISSION_SET_NAME_DEFAULT,
            steps_complete=["enable"],
        )
        state.save()
    else:
        console.print(
            "[dim]Resuming bootstrap from a previous run...[/dim]"
        )

    if "permission_set" not in state.steps_complete:
        permission_set_name = _step_create_permission_set()
        state.permission_set_name = permission_set_name
        state.steps_complete.append("permission_set")
        state.save()

    if "assign" not in state.steps_complete:
        _step_assign_user(state.permission_set_name)
        state.steps_complete.append("assign")
        state.save()

    result = SSOBootstrapResult(
        start_url=state.sso_start_url,
        sso_region=state.sso_region,
        permission_set_name=state.permission_set_name,
        deployment_region=deployment_region,
    )
    _write_aws_config(result)
    BootstrapState.clear()
    return result
