"""First-time Identity Center setup — the console handoff flow.

This drives the user through enabling Identity Center, then automates
the rest (permission set creation + user assignment) via a script the
user pastes into AWS CloudShell. CloudShell inherits the user's
console-session credentials, so no local AWS CLI auth is needed for
the bootstrap. The CLI then writes ~/.aws/config and the user signs
in via `aws sso login` for steady-state.
"""

from __future__ import annotations

import configparser
import json
import os
import re
import webbrowser
from dataclasses import dataclass
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


def _is_valid_sso_start_url(url: str) -> bool:
    return bool(_SSO_URL_RE.match(url.strip()))


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


def copy_to_clipboard(payload: str) -> Path | None:
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


# Matches a typical email address. Permissive — just enough to catch
# obvious typos like missing "@". Identity Center accepts almost
# anything as a username, so the script also tries UserName lookup as
# a fallback when the email-by-attribute lookup fails.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip()))


# Tag used to delimit the bash heredoc the user pastes into CloudShell.
# Picked to be unmistakable in the user's terminal; never appears
# inside the script body.
_HEREDOC_TAG = "LABLINK_SETUP"

_BOOTSTRAP_SCRIPT_TEMPLATE = """\
bash <<'__HEREDOC_TAG__'
set -e

EMAIL="__EMAIL__"
PS_NAME="__PS_NAME__"

# Inline policy as a multi-line single-quoted string. Keeping this as a
# bash variable (rather than passing JSON inline on the aws CLI command)
# avoids the long-line copy-paste issue where terminals soft-wrap and
# insert spurious newlines mid-argument.
INLINE_POLICY='__INLINE_POLICY_JSON__'

INSTANCE_ARN=$(aws sso-admin list-instances \\
  --query 'Instances[0].InstanceArn' --output text)
ID_STORE_ID=$(aws sso-admin list-instances \\
  --query 'Instances[0].IdentityStoreId' --output text)
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "Setting up $PS_NAME permissions for $EMAIL on account $ACCOUNT_ID..."

# Create or find the permission set (idempotent)
PS_ARN=""
for arn in $(aws sso-admin list-permission-sets \\
    --instance-arn "$INSTANCE_ARN" --query 'PermissionSets[]' --output text); do
  name=$(aws sso-admin describe-permission-set \\
    --instance-arn "$INSTANCE_ARN" --permission-set-arn "$arn" \\
    --query 'PermissionSet.Name' --output text)
  if [ "$name" = "$PS_NAME" ]; then PS_ARN="$arn"; break; fi
done
if [ -z "$PS_ARN" ]; then
  PS_ARN=$(aws sso-admin create-permission-set \\
    --instance-arn "$INSTANCE_ARN" --name "$PS_NAME" \\
    --query 'PermissionSet.PermissionSetArn' --output text)
  echo "  created permission set"
else
  echo "  permission set already exists"
fi

# Attach managed policies (idempotent — duplicate attaches are no-ops)
for POLICY in __MANAGED_POLICY_ARNS__; do
  aws sso-admin attach-managed-policy-to-permission-set \\
    --instance-arn "$INSTANCE_ARN" --permission-set-arn "$PS_ARN" \\
    --managed-policy-arn "$POLICY" 2>/dev/null || true
done
echo "  attached managed policies"

# Set inline policy (always overwrites — keeps it in sync with the CLI)
aws sso-admin put-inline-policy-to-permission-set \\
  --instance-arn "$INSTANCE_ARN" --permission-set-arn "$PS_ARN" \\
  --inline-policy "$INLINE_POLICY"
echo "  set inline policy"

# Look up Identity Center user — prefer email match, fall back to UserName
USER_ID=$(aws identitystore list-users --identity-store-id "$ID_STORE_ID" \\
  --query "Users[?Emails[?Value=='$EMAIL']].UserId | [0]" \\
  --output text 2>/dev/null)
if [ -z "$USER_ID" ] || [ "$USER_ID" = "None" ]; then
  USER_ID=$(aws identitystore list-users --identity-store-id "$ID_STORE_ID" \\
    --filters "AttributePath=UserName,AttributeValue=$EMAIL" \\
    --query 'Users[0].UserId' --output text 2>/dev/null)
fi
if [ -z "$USER_ID" ] || [ "$USER_ID" = "None" ]; then
  echo ""
  echo "ERROR: No Identity Center user matched '$EMAIL'."
  echo ""
  echo "Most likely your Identity Center username is different from"
  echo "your email. The 'Add user' form has separate Username and"
  echo "Email fields, and lookups failed against both for this value."
  echo ""
  echo "Existing Identity Center users in this account:"
  aws identitystore list-users --identity-store-id "$ID_STORE_ID" \\
    --query 'Users[].{UserName:UserName,Email:Emails[0].Value}' \\
    --output table
  echo ""
  echo "Re-run the script with EMAIL set to the UserName shown above"
  echo "(or fix the user in Identity Center so Username == email)."
  exit 1
fi

# Assign user to this AWS account (idempotent)
aws sso-admin create-account-assignment \\
  --instance-arn "$INSTANCE_ARN" --target-id "$ACCOUNT_ID" \\
  --target-type AWS_ACCOUNT --permission-set-arn "$PS_ARN" \\
  --principal-id "$USER_ID" --principal-type USER >/dev/null 2>&1 || true
echo "  assigned user to account"

echo ""
echo "Done. Return to your lablink terminal and press Enter."
__HEREDOC_TAG__
"""


def render_bootstrap_script(email: str) -> str:
    """Render the CloudShell heredoc that creates the permission set and
    assigns the user.

    Inlines MANAGED_POLICY_ARNS and INLINE_POLICY from policy.py at call
    time so the script is always in sync with the CLI's source of truth.
    The inline policy is rendered with indentation (multi-line bash
    variable) so no individual line is so long that a terminal will
    soft-wrap and break the paste.
    """
    arn_list = " \\\n  ".join(policy.MANAGED_POLICY_ARNS)
    # Pretty-printed JSON keeps each line short. Single-quoted bash
    # strings can span newlines; JSON has no single quotes, so no
    # escaping is needed.
    inline_json = json.dumps(policy.INLINE_POLICY, indent=2)
    return (
        _BOOTSTRAP_SCRIPT_TEMPLATE
        .replace("__HEREDOC_TAG__", _HEREDOC_TAG)
        .replace("__EMAIL__", email)
        .replace("__PS_NAME__", policy.PERMISSION_SET_NAME_DEFAULT)
        .replace("__MANAGED_POLICY_ARNS__", arn_list)
        .replace("__INLINE_POLICY_JSON__", inline_json)
    )


def _step_enable_identity_center() -> tuple[str, str]:
    """Walk the user through enabling Identity Center. Returns (start_url, region)."""
    console.print(
        Panel(
            "Welcome to LabLink. This is your first sign-in.\n\n"
            "We'll set up an AWS sign-in for you so the CLI can deploy lab\n"
            "infrastructure on your behalf — no access keys, no copy-pasting\n"
            "secrets. You'll sign in through your browser each session.\n\n"
            "First-time setup takes [bold]5–10 minutes[/bold]. You'll do "
            "two things in the AWS web console:\n\n"
            "  [bold]1.[/bold] Turn on AWS's sign-in service "
            "(it's called [italic]Identity Center[/italic]) and "
            "create a\n"
            "     sign-in for yourself.\n"
            "  [bold]2.[/bold] Paste one command into AWS's in-browser "
            "terminal to grant\n"
            "     your sign-in permission to run lablink.\n\n"
            "[bold yellow]Before you continue:[/bold yellow] install an "
            "authenticator app on your phone\n"
            "(Authy, Google Authenticator, 1Password, or similar). AWS "
            "requires\ntwo-factor authentication and you'll pair the app "
            "partway through.",
            title="First-time setup",
            border_style="cyan",
        )
    )
    input("Press Enter when you're ready to open the AWS Console...")
    webbrowser.open(IDENTITY_CENTER_CONSOLE_URL)

    console.print(
        "\n[bold]Step 1 of 2: Turn on the AWS sign-in service[/bold]\n"
        "In the AWS Console tab that just opened:\n"
        "  1. Click [bold]Enable[/bold]. (If asked, choose "
        "[bold]account instance[/bold] for personal accounts.)\n"
        "  2. Wait ~30 seconds while AWS sets things up.\n"
        "  3. In the left sidebar, click [bold]Users[/bold] → "
        "[bold]Add user[/bold].\n"
        "  4. Fill in the form. [bold yellow]The 'Add user' wizard has "
        "three pages[/bold yellow] —\n"
        "     you must click [bold]Next[/bold] all the way through and "
        "click [bold]Add user[/bold] on the\n"
        "     final review page, or no user will be created. "
        "[bold]Use your email as the\n"
        "     Username[/bold] (not just the local-part) so the next step's "
        "lookup matches.\n"
        "  5. Check your email for an [bold]Accept invitation[/bold] link. "
        "Click it,\n"
        "     set a password, and pair your authenticator app.\n"
        "  6. Return to the Identity Center home page (the page you opened "
        "in step 1).\n"
        "  7. On the dashboard, find the [bold]AWS access portal URLs[/bold] "
        "section\n"
        "     and copy the link shown there — we'll call this your "
        "[bold]sign-in link[/bold]\n"
        "     (AWS labels it the [italic]SSO Start URL[/italic]).\n"
    )

    while True:
        start_url = typer.prompt("Paste your sign-in link here")
        if _is_valid_sso_start_url(start_url):
            break
        console.print(
            "[red]That doesn't look like an AWS sign-in link.[/red] "
            "Expected something like [dim]https://d-9067abc123.awsapps.com/start[/dim]"
        )

    sso_region = typer.prompt(
        "AWS region (shown in the top-right corner of the AWS Console)",
        default="us-east-1",
    )
    return start_url.strip(), sso_region.strip()


def _prompt_email() -> str:
    """Collect the email the user typed when creating their Identity Center user."""
    while True:
        email = typer.prompt(
            "Email you used to create the Identity Center user"
        )
        if _is_valid_email(email):
            return email.strip()
        console.print(
            "[red]That doesn't look like an email address.[/red] "
            "Use the same email you typed in the [bold]Add user[/bold] form."
        )


def _step_create_permission_set() -> str:
    """Walk the user through creating the lablink permission set."""
    payload = policy.render_inline_policy_json()
    fallback_path = copy_to_clipboard(payload)

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


def _save_bootstrap_script(script: str) -> Path:
    """Save the rendered script to ~/.lablink/cloudshell-bootstrap.sh.

    Provides a paste-failure fallback: the user can either upload this
    file via CloudShell's "Actions → Upload file" menu, or `cat` it to
    re-print a clean copy.
    """
    home = Path(os.environ.get("HOME", str(Path.home())))
    out = home / ".lablink" / "cloudshell-bootstrap.sh"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(script)
    return out


def _step_grant_permissions_cloudshell(email: str) -> None:
    """New default step 2: user pastes a script into AWS CloudShell.

    CloudShell runs as the user's console-session identity, so the
    `aws ...` calls in the script work with no extra setup. The script
    creates the permission set, attaches policies, and assigns the
    user to the current AWS account — replacing what used to be 14
    manual console clicks across two separate flows.

    The script is also saved to ~/.lablink/cloudshell-bootstrap.sh as
    a fallback for terminals that mangle multi-line paste (some Windows
    terminals, certain SSH setups, mouse-select-only environments).
    The user can then upload that file via CloudShell's
    "Actions → Upload file" menu instead of copy-pasting.
    """
    script = render_bootstrap_script(email)
    script_path = _save_bootstrap_script(script)

    console.print(
        "\n[bold]Step 2 of 2: Grant your sign-in permission to run "
        "lablink[/bold]\n"
        "We'll use AWS [bold]CloudShell[/bold] — a free terminal in your "
        "browser that\n"
        "automatically uses your AWS Console sign-in. No local AWS CLI "
        "setup needed.\n\n"
        "  1. In the AWS Console (still open in your browser), click the "
        "[bold]CloudShell[/bold]\n"
        "     icon in the top-right toolbar (it looks like "
        "[bold]>_[/bold]).\n"
        "  2. Wait ~10 seconds for the terminal to start.\n"
        "  3. [bold]Copy the script printed below[/bold] and paste it "
        "into CloudShell,\n"
        "     then press Enter.\n"
        "  4. The script takes ~30 seconds. Wait until you see "
        "[green]Done.[/green]\n"
    )

    # Print rule + plain script + rule. No Panel: vertical bars (│) on
    # every line of a Rich Panel get included in the user's clipboard
    # and break the bash heredoc. ``highlight=False, markup=False`` keeps
    # Rich from interpreting any character in the script body.
    console.rule("[bold cyan]Begin script — copy from below[/bold cyan]")
    console.print(script, highlight=False, markup=False)
    console.rule("[bold cyan]End script[/bold cyan]")

    console.print(
        f"\n[dim]Paste mangled? The same script was saved to "
        f"[bold]{script_path}[/bold].\n"
        "In CloudShell, click [bold]Actions → Upload file[/bold], pick that "
        "file, then run\n"
        "[bold]bash ~/cloudshell-bootstrap.sh[/bold] in CloudShell.[/dim]\n"
    )
    input("Press Enter once you see Done. in CloudShell...")


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


def run_bootstrap(
    *,
    deployment_region: str,
    manual: bool = False,
) -> SSOBootstrapResult:
    """Run the full first-time bootstrap flow.

    Default flow uses CloudShell — the user pastes one script that does
    permission-set creation and user assignment in ~30 seconds. The
    ``manual`` mode preserves the original click-through-the-console
    flow as an escape hatch (CloudShell-unavailable regions, paranoid
    auditors, debugging).

    All AWS-side state created by the bootstrap (Identity Center
    enabled, user created, permission set, assignment) persists across
    runs, so if the user Ctrl-Cs partway through they can simply
    re-run `lablink login` and re-confirm what's already in place.
    """
    start_url, sso_region = _step_enable_identity_center()

    if manual:
        permission_set_name = _step_create_permission_set()
        _step_assign_user(permission_set_name)
    else:
        email = _prompt_email()
        _step_grant_permissions_cloudshell(email)
        permission_set_name = policy.PERMISSION_SET_NAME_DEFAULT

    result = SSOBootstrapResult(
        start_url=start_url,
        sso_region=sso_region,
        permission_set_name=permission_set_name,
        deployment_region=deployment_region,
    )
    _write_aws_config(result)
    return result
