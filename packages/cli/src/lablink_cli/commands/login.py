"""`lablink login` — orchestrate Identity Center bootstrap + SSO sign-in."""

from __future__ import annotations

import configparser
import datetime as dt
import json
import webbrowser

import boto3
import typer
from rich.console import Console
from rich.panel import Panel

from lablink_cli.auth import policy
from lablink_cli.auth.bootstrap import (
    CREATE_PERMISSION_SET_URL,
    SSOBootstrapResult,
    copy_to_clipboard,
    run_bootstrap,
)
from lablink_cli.auth.credentials import (
    PROFILE_NAME,
    SSO_SESSION_NAME,
    has_sso_profile,
    is_logged_in,
)
from lablink_cli.auth.sso_flow import (
    SSOConfig,
    login as sso_login,
    resolve_role,
    select_account,
)
from lablink_cli.auth.utils import aws_config_path, sso_cache_path

console = Console()


def _read_sso_config() -> SSOConfig:
    parser = configparser.ConfigParser()
    parser.read(aws_config_path())
    section = f"sso-session {SSO_SESSION_NAME}"
    return SSOConfig(
        start_url=parser.get(section, "sso_start_url"),
        region=parser.get(section, "sso_region"),
    )


def _read_profile_field(field: str) -> str | None:
    parser = configparser.ConfigParser()
    parser.read(aws_config_path())
    section = f"profile {PROFILE_NAME}"
    if section not in parser.sections():
        return None
    return parser.get(section, field, fallback=None)


def _write_profile_field(field: str, value: str) -> None:
    cfg_path = aws_config_path()
    parser = configparser.ConfigParser()
    parser.read(cfg_path)
    section = f"profile {PROFILE_NAME}"
    if section not in parser.sections():
        parser.add_section(section)
    parser.set(section, field, value)
    with open(cfg_path, "w") as fp:
        parser.write(fp)


def _token_expiry_human() -> str:
    """Return a human-readable 'in 4h 12m' for the cached SSO token."""
    cache_path = sso_cache_path(SSO_SESSION_NAME)

    try:
        data = json.loads(cache_path.read_text())
        expiry = dt.datetime.fromisoformat(
            data["expiresAt"].replace("Z", "+00:00")
        )
    except (OSError, KeyError, ValueError):
        return "unknown"

    delta = expiry - dt.datetime.now(dt.timezone.utc)
    seconds = max(0, int(delta.total_seconds()))
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    return f"{hours}h {minutes}m"


def run_steady_state() -> None:
    """Run the SSO device-code flow against the existing [sso-session lablink]."""
    sso_config = _read_sso_config()

    access_token = sso_login(sso_config)

    account_id = _read_profile_field("sso_account_id")
    if not account_id:
        account_id = select_account(
            sso_config=sso_config, access_token=access_token
        )
        _write_profile_field("sso_account_id", account_id)

    role = _read_profile_field("sso_role_name") or "lablink"
    resolved_role = resolve_role(
        sso_config=sso_config,
        access_token=access_token,
        account_id=account_id,
        preferred_role_name=role,
    )
    if resolved_role != role:
        _write_profile_field("sso_role_name", resolved_role)

    sts = boto3.Session(profile_name=PROFILE_NAME).client("sts")
    identity = sts.get_caller_identity()
    expiry_human = _token_expiry_human()

    console.print(
        "\n[green]✓[/green] Signed in via Identity Center"
    )
    console.print(f"[green]✓[/green] AWS Account: [bold]{account_id}[/bold]")
    console.print(f"[green]✓[/green] Permission set: [bold]{resolved_role}[/bold]")
    console.print(f"[green]✓[/green] Token valid for: [bold]{expiry_human}[/bold]")
    console.print(f"[dim]ARN: {identity.get('Arn', '')}[/dim]\n")


def _verify_permission_set() -> list[str]:
    """Return policy names that are missing from the active SSO role.

    Uses iam:SimulatePrincipalPolicy against AUDIT_ACTIONS so the check
    works regardless of which managed policy grants which action. Empty
    list = everything is in place.
    """
    from botocore.exceptions import ClientError

    session = boto3.Session(profile_name=PROFILE_NAME)
    arn = session.client("sts").get_caller_identity().get("Arn", "")
    # arn:aws:sts::ACCOUNT:assumed-role/AWSReservedSSO_lablink_HASH/USER
    # → arn:aws:iam::ACCOUNT:role/AWSReservedSSO_lablink_HASH
    principal_arn = (
        arn.replace(":sts:", ":iam:")
        .replace("assumed-role", "role")
        .rsplit("/", 1)[0]
    )

    iam = session.client("iam")
    unscoped = [
        a for a in policy.AUDIT_ACTIONS
        if a not in policy.AUDIT_RESOURCE_OVERRIDES
    ]
    eval_results = []
    try:
        if unscoped:
            eval_results.extend(
                iam.simulate_principal_policy(
                    PolicySourceArn=principal_arn,
                    ActionNames=unscoped,
                ).get("EvaluationResults", [])
            )
        for action, resource_arns in policy.AUDIT_RESOURCE_OVERRIDES.items():
            if action not in policy.AUDIT_ACTIONS:
                continue
            eval_results.extend(
                iam.simulate_principal_policy(
                    PolicySourceArn=principal_arn,
                    ActionNames=[action],
                    ResourceArns=resource_arns,
                ).get("EvaluationResults", [])
            )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "AccessDenied":
            # The simulate call itself needs iam:SimulatePrincipalPolicy,
            # which is part of IAMFullAccess. If we can't even simulate,
            # IAMFullAccess (or similar IAM read perms) is missing.
            return ["IAMFullAccess"]
        raise

    denied_actions = [
        r["EvalActionName"]
        for r in eval_results
        if r.get("EvalDecision") != "allowed"
    ]
    if not denied_actions:
        return []

    # Map denied actions back to policy names; dedupe while preserving order.
    seen: set[str] = set()
    missing: list[str] = []
    for action in denied_actions:
        name = policy.ACTION_TO_POLICY_NAME.get(action, action)
        if name not in seen:
            seen.add(name)
            missing.append(name)
    return missing


def _run_verifier_with_retry(*, max_attempts: int = 3) -> None:
    """Run _verify_permission_set with a small retry loop.

    On failure, lists missing policies and waits for the user to fix
    them in the AWS Console, then re-runs. Exits with a hint if the
    user hits the retry cap.
    """
    for attempt in range(1, max_attempts + 1):
        missing = _verify_permission_set()
        if not missing:
            console.print(
                "[green]✓[/green] Permission set has every required policy.\n"
            )
            return

        console.print(
            f"\n[yellow]Permission set is missing {len(missing)} "
            f"policy/policies:[/yellow]"
        )
        for name in missing:
            if name == "<inline>":
                console.print(
                    "  • [bold]inline policy[/bold] — run "
                    "[bold]lablink login --update-policy[/bold] to refresh."
                )
            else:
                console.print(f"  • [bold]{name}[/bold]")

        if attempt == max_attempts:
            console.print(
                "\n[yellow]Reached retry limit.[/yellow] Fix the policies above "
                "and run [bold]lablink doctor[/bold] when ready."
            )
            return

        console.print(
            "\nIn the AWS Console, attach the missing policy/policies to your "
            "[bold]lablink[/bold] permission set, then press Enter to "
            "re-check.\n"
            f"[dim]Attempt {attempt} of {max_attempts}.[/dim]"
        )
        input()


def run_login(
    deployment_region: str | None = None,
    update_policy: bool = False,
    manual: bool = False,
) -> None:
    """Top-level login orchestrator."""
    if update_policy:
        payload = policy.render_inline_policy_json()
        copy_to_clipboard(payload)
        console.print(
            Panel(
                "Permission set policy JSON copied to your clipboard.\n\n"
                "Open the AWS Console, navigate to your [bold]lablink[/bold]\n"
                "permission set, and replace its inline policy with the\n"
                "clipboard contents.",
                title="Update policy",
                border_style="cyan",
            )
        )
        webbrowser.open(CREATE_PERMISSION_SET_URL)
        return

    if is_logged_in():
        expiry = _token_expiry_human()
        console.print(
            f"Already signed in, valid for [bold]{expiry}[/bold]."
        )
        if not typer.confirm("Re-login?", default=False):
            return

    bootstrapped = False
    if not has_sso_profile():
        try:
            result: SSOBootstrapResult = run_bootstrap(
                deployment_region=deployment_region or "us-east-1",
                manual=manual,
            )
        except KeyboardInterrupt:
            console.print(
                "\n[yellow]Bootstrap interrupted.[/yellow] "
                "Re-run [bold]lablink login[/bold] to start over."
            )
            raise typer.Exit(1) from None
        console.print(
            f"\n[green]✓[/green] Identity Center configured "
            f"({result.start_url})\n"
        )
        bootstrapped = True

    run_steady_state()

    # Verify the permission set has every policy lablink needs. This is
    # most useful right after a fresh bootstrap (typo'd email, paste
    # mangled, manual flow forgot a policy) but cheap enough to run on
    # every login — catches policy drift if AWS removed something.
    if bootstrapped or manual:
        _run_verifier_with_retry()
