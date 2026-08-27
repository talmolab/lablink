"""Health checks and cost estimation for LabLink deployments."""

from __future__ import annotations

import json
import os
import socket
import ssl
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3
from botocore.exceptions import ClientError
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from lablink_allocator_service.conf.structured_config import Config

from lablink_cli import manual
from lablink_cli.api import USER_AGENT
from lablink_cli.commands.utils import (
    AwsQueryError,
    aws_credentials_error,
    get_client_vms,
    get_deploy_dir as _get_deploy_dir,
    get_tofu_outputs,
    TofuError,
    print_aws_error,
)
from lablink_cli.docker import Docker, default_docker

console = Console()

# Fallback daily costs (Feb 2025 on-demand, us-east-1)
FALLBACK_COSTS: dict[str, dict[str, float]] = {
    "ec2": {
        "t3.large": 0.0832 * 24,
        "t3.xlarge": 0.1664 * 24,
        "g4dn.xlarge": 0.526 * 24,
        "g4dn.2xlarge": 0.752 * 24,
        "g5.xlarge": 1.006 * 24,
        "g5.2xlarge": 1.212 * 24,
        "p3.2xlarge": 3.06 * 24,
    },
    "ebs_per_gb": 0.08,
    "eip": 0.005 * 24,
    "route53_zone": 0.50 / 30,
    "alb": 0.0225 * 24,
}



# ------------------------------------------------------------------
# Health checks
# ------------------------------------------------------------------
def check_dns(domain: str, expected_ip: str) -> dict:
    """Check DNS resolution."""
    result = {"check": "DNS Resolution", "status": "skip"}
    if not domain:
        result["detail"] = "No domain configured"
        return result

    try:
        resolved_ip = socket.gethostbyname(domain)
        if resolved_ip == expected_ip:
            result["status"] = "pass"
            result["detail"] = f"{domain} → {resolved_ip}"
        else:
            result["status"] = "warn"
            result["detail"] = (
                f"{domain} → {resolved_ip} "
                f"(expected {expected_ip})"
            )
    except socket.gaierror:
        result["status"] = "fail"
        result["detail"] = f"{domain} does not resolve"
    return result


def check_http(url: str) -> dict:
    """Check HTTP connectivity to the allocator."""
    result = {"check": "HTTP Health", "status": "fail"}
    try:
        req = Request(url, method="GET")
        req.add_header("User-Agent", USER_AGENT)
        resp = urlopen(req, timeout=10)  # noqa: S310
        code = resp.getcode()
        if code and code < 400:
            result["status"] = "pass"
            result["detail"] = f"{url} → HTTP {code}"
        else:
            result["status"] = "warn"
            result["detail"] = f"{url} → HTTP {code}"
    except URLError as e:
        result["detail"] = f"{url} → {e.reason}"
    except Exception as e:
        result["detail"] = f"{url} → {e}"
    return result


def check_health_endpoint(base_url: str) -> dict:
    """Check the allocator /api/health endpoint for structured readiness.

    Returns a dict with:
      - status: "pass" | "starting" | "unreachable"
      - healthy: bool
      - uptime_seconds: float | None
      - checks: dict | None (from the health endpoint response)
      - detail: str
    """
    url = f"{base_url.rstrip('/')}/api/health"
    result: dict = {
        "status": "unreachable",
        "healthy": False,
        "uptime_seconds": None,
        "checks": None,
        "detail": "",
    }
    try:
        req = Request(url, method="GET")
        req.add_header("User-Agent", USER_AGENT)
        resp = urlopen(req, timeout=10)  # noqa: S310
        body = json.loads(resp.read().decode())
        if body.get("status") == "healthy":
            result["status"] = "pass"
            result["healthy"] = True
        else:
            result["status"] = "starting"
        result["uptime_seconds"] = body.get("uptime_seconds")
        result["checks"] = body.get("checks")
        result["detail"] = f"{url} → {body.get('status')}"
    except HTTPError as e:
        try:
            body = json.loads(e.read().decode())
            result["status"] = "starting"
            result["uptime_seconds"] = body.get("uptime_seconds")
            result["checks"] = body.get("checks")
            result["detail"] = f"{url} → {body.get('status')}"
        except Exception:
            result["detail"] = f"{url} → HTTP {e.code}"
    except URLError as e:
        result["detail"] = f"{url} → {e.reason}"
    except Exception as e:
        result["detail"] = f"{url} → {e}"
    return result


def check_ssl_cert(domain: str) -> dict:
    """Check SSL certificate validity."""
    result = {"check": "SSL Certificate", "status": "skip"}
    if not domain:
        result["detail"] = "No domain configured"
        return result

    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(
            socket.socket(), server_hostname=domain
        ) as sock:
            sock.settimeout(10)
            sock.connect((domain, 443))
            cert = sock.getpeercert()

        if not cert:
            result["status"] = "fail"
            result["detail"] = "No certificate returned"
            return result

        # Parse expiry
        not_after = cert.get("notAfter", "")
        if not_after:
            expiry = datetime.strptime(
                not_after, "%b %d %H:%M:%S %Y %Z"
            ).replace(tzinfo=timezone.utc)
            days_left = (
                expiry - datetime.now(timezone.utc)
            ).days

            issuer_parts = dict(
                x[0] for x in cert.get("issuer", ())
            )
            issuer = issuer_parts.get(
                "organizationName", "Unknown"
            )

            if days_left > 14:
                result["status"] = "pass"
            elif days_left > 0:
                result["status"] = "warn"
            else:
                result["status"] = "fail"

            result["detail"] = (
                f"Issuer: {issuer}, "
                f"Expires: {expiry.date()} "
                f"({days_left} days)"
            )
        else:
            result["status"] = "warn"
            result["detail"] = "Could not parse expiry"

    except ssl.SSLError as e:
        result["status"] = "fail"
        result["detail"] = f"SSL error: {e}"
    except (ConnectionRefusedError, OSError) as e:
        result["status"] = "fail"
        result["detail"] = f"Connection failed: {e}"
    return result


# ------------------------------------------------------------------
# Cost estimation
# ------------------------------------------------------------------
REGION_NAME_MAP = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-central-1": "EU (Frankfurt)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
}


def _get_ec2_price(
    pricing_client, instance_type: str, location: str
) -> float | None:
    """Query AWS Pricing API for EC2 on-demand hourly price."""
    try:
        resp = pricing_client.get_products(
            ServiceCode="AmazonEC2",
            Filters=[
                {
                    "Type": "TERM_MATCH",
                    "Field": "instanceType",
                    "Value": instance_type,
                },
                {
                    "Type": "TERM_MATCH",
                    "Field": "location",
                    "Value": location,
                },
                {
                    "Type": "TERM_MATCH",
                    "Field": "operatingSystem",
                    "Value": "Linux",
                },
                {
                    "Type": "TERM_MATCH",
                    "Field": "tenancy",
                    "Value": "Shared",
                },
                {
                    "Type": "TERM_MATCH",
                    "Field": "preInstalledSw",
                    "Value": "NA",
                },
                {
                    "Type": "TERM_MATCH",
                    "Field": "capacitystatus",
                    "Value": "Used",
                },
            ],
            MaxResults=1,
        )
        if resp["PriceList"]:
            product = json.loads(resp["PriceList"][0])
            terms = product["terms"]["OnDemand"]
            for term in terms.values():
                for dim in term["priceDimensions"].values():
                    price = float(
                        dim["pricePerUnit"]["USD"]
                    )
                    if price > 0:
                        return price
    except (ClientError, KeyError, ValueError):
        pass
    return None


def estimate_costs(
    cfg: Config, use_pricing_api: bool = True
) -> list[dict]:
    """Estimate daily costs for the deployment.

    Pass ``use_pricing_api=False`` when AWS credentials are known to be
    unusable, to skip Pricing API calls that can only fail and fall
    straight through to FALLBACK_COSTS.
    """
    region = cfg.app.region
    location = REGION_NAME_MAP.get(region, region)
    costs: list[dict] = []

    # Try AWS Pricing API (only available in us-east-1)
    pricing = None
    use_api = False
    if use_pricing_api:
        try:
            pricing = boto3.client(
                "pricing", region_name="us-east-1"
            )
            use_api = True
        except Exception:
            use_api = False
            pricing = None

    # Allocator EC2 (always t3.large)
    alloc_type = "t3.large"
    if use_api:
        price = _get_ec2_price(
            pricing, alloc_type, location
        )
    else:
        price = None
    daily = (
        price * 24
        if price
        else FALLBACK_COSTS["ec2"].get(alloc_type, 2.0)
    )
    costs.append(
        {
            "resource": f"Allocator EC2 ({alloc_type})",
            "daily": daily,
            "note": "always on",
        }
    )

    # EBS (30 GB gp3 assumed for allocator)
    ebs_daily = FALLBACK_COSTS["ebs_per_gb"] * 30 / 30
    costs.append(
        {
            "resource": "Allocator EBS (30 GB gp3)",
            "daily": ebs_daily,
            "note": "always on",
        }
    )

    # Elastic IP
    costs.append(
        {
            "resource": "Elastic IP",
            "daily": FALLBACK_COSTS["eip"],
            "note": "free while attached",
        }
    )

    # Route53
    if cfg.dns.enabled:
        costs.append(
            {
                "resource": "Route53 Hosted Zone",
                "daily": FALLBACK_COSTS["route53_zone"],
                "note": "$0.50/month",
            }
        )

    # ALB (ACM only)
    if cfg.ssl.provider == "acm":
        costs.append(
            {
                "resource": "Application Load Balancer",
                "daily": FALLBACK_COSTS["alb"],
                "note": "~$20/month",
            }
        )

    # Client VMs (per-VM cost, not always on)
    client_type = cfg.machine.machine_type
    if use_api:
        client_price = _get_ec2_price(
            pricing, client_type, location
        )
    else:
        client_price = None
    client_daily = (
        client_price * 24
        if client_price
        else FALLBACK_COSTS["ec2"].get(client_type)
    )
    if client_daily:
        costs.append(
            {
                "resource": f"Client VM ({client_type})",
                "daily": client_daily,
                "note": "per VM, on-demand",
            }
        )

    return costs


def _render_tofu_state(
    deploy_dir: Path, aws_unavailable: bool = False
) -> dict:
    """Read and display OpenTofu outputs. Returns outputs dict.

    ``aws_unavailable`` only picks the wording for a failed read: when
    credentials are already known to be dead, the block printed above
    carries the remedy, so repeating tofu's own STS complaint here adds
    noise instead of information.
    """
    if not deploy_dir.exists():
        return {}

    console.print("[bold]OpenTofu State[/bold]")
    try:
        outputs = get_tofu_outputs(deploy_dir)
    except TofuError as e:
        if aws_unavailable:
            console.print(
                "  [yellow]State unreadable — see AWS credentials "
                "above[/yellow]"
            )
        else:
            console.print(
                f"  [yellow]State unreadable:[/yellow] {escape(str(e))}"
            )
        console.print()
        return {}

    if outputs:
        state_table = Table(show_header=False)
        state_table.add_column("Key", style="bold")
        state_table.add_column("Value")
        for k, v in outputs.items():
            if k == "private_key_pem":
                v = "(sensitive)"
            state_table.add_row(k, str(v))
        console.print(state_table)
    else:
        console.print(
            "  [yellow]No OpenTofu state found[/yellow]"
        )
    console.print()
    return outputs


def _build_health_url(cfg: Config, outputs: dict) -> str:
    """Build the URL to use for HTTP health checks."""
    domain = cfg.dns.domain if cfg.dns.enabled else ""
    ip = outputs.get("ec2_public_ip", "")
    use_https = cfg.ssl.provider != "none"

    if domain and use_https:
        return f"https://{domain}"
    if domain:
        return f"http://{domain}"
    if ip:
        return f"http://{ip}"
    return ""


def _print_admin_url(base_url: str) -> None:
    """Print the admin page URL, if we could build one."""
    if base_url:
        console.print(f"[bold]Admin URL:[/bold] {base_url.rstrip('/')}/admin")


def _render_health_checks(cfg: Config, outputs: dict) -> None:
    """Run and display health checks."""
    domain = cfg.dns.domain if cfg.dns.enabled else ""
    use_https = cfg.ssl.provider != "none"
    url = _build_health_url(cfg, outputs)

    console.print("[bold]Health Checks[/bold]")
    checks = []

    if domain:
        checks.append(check_dns(domain, outputs.get("ec2_public_ip", "")))
    if url:
        health = check_health_endpoint(url)
        detail = health.get("detail", "")
        if health["healthy"] and health.get("uptime_seconds") is not None:
            detail += f" (uptime: {health['uptime_seconds']}s)"
        checks.append({
            "check": "Allocator Health",
            "status": "pass" if health["healthy"] else (
                "warn" if health["status"] == "starting" else "fail"
            ),
            "detail": detail,
        })
    if domain and use_https:
        checks.append(check_ssl_cert(domain))

    if checks:
        health_table = Table(show_header=True)
        health_table.add_column("Check")
        health_table.add_column("Status")
        health_table.add_column("Detail")

        status_styles = {
            "pass": "[green]PASS[/green]",
            "fail": "[red]FAIL[/red]",
            "warn": "[yellow]WARN[/yellow]",
            "skip": "[dim]SKIP[/dim]",
        }

        for c in checks:
            health_table.add_row(
                c["check"],
                status_styles.get(
                    c["status"], c["status"]
                ),
                c.get("detail", ""),
            )
        console.print(health_table)
    else:
        console.print(
            "  [dim]No deployment found — "
            "skipping health checks[/dim]"
        )
    console.print()


def _render_client_vms(cfg: Config, aws_unavailable: bool = False) -> None:
    """Query and display client VM status.

    "No client VMs found" is reserved for a query that succeeded and
    matched nothing. A failed query says so instead.
    """
    console.print("[bold]Client VMs[/bold]")
    if aws_unavailable:
        console.print(
            "  [dim]Inventory unavailable — see AWS credentials "
            "above[/dim]"
        )
        console.print()
        return

    try:
        vms = get_client_vms(cfg)
    except AwsQueryError as e:
        print_aws_error(e, prefix="Could not query EC2")
        console.print()
        return

    if not vms:
        console.print(
            "  [dim]No client VMs found[/dim]"
        )
        console.print()
        return

    vm_table = Table(show_header=True)
    vm_table.add_column("Name")
    vm_table.add_column("Instance ID")
    vm_table.add_column("Type")
    vm_table.add_column("State")
    vm_table.add_column("Public IP")

    running_count = 0
    stopped_count = 0
    for vm in vms:
        state = vm["state"]
        if state == "running":
            running_count += 1
            state_str = "[green]running[/green]"
        elif state == "stopped":
            stopped_count += 1
            state_str = "[red]stopped[/red]"
        else:
            state_str = f"[yellow]{state}[/yellow]"
        vm_table.add_row(
            vm["name"],
            vm["instance_id"],
            vm["type"],
            state_str,
            vm["public_ip"] or "—",
        )

    console.print(vm_table)

    parts = []
    if running_count:
        parts.append(
            f"[green]{running_count} running[/green]"
        )
    if stopped_count:
        parts.append(
            f"[red]{stopped_count} stopped[/red]"
        )
    console.print(f"  {', '.join(parts)}")

    if running_count:
        vm_type = vms[0]["type"]
        hourly = FALLBACK_COSTS["ec2"].get(vm_type)
        if hourly:
            daily = hourly
            hourly_rate = daily / 24
            total_hourly = hourly_rate * running_count
            console.print(
                f"  [dim]Estimated burn rate: "
                f"${total_hourly:.2f}/hr "
                f"(${total_hourly * 24:.2f}/day) "
                f"for {running_count} "
                f"x {vm_type}[/dim]"
            )
    console.print()


def _render_cost_estimate(cfg: Config, live_pricing: bool = True) -> None:
    """Calculate and display cost estimate."""
    console.print("[bold]Cost Estimate (daily)[/bold]")
    costs = estimate_costs(cfg, use_pricing_api=live_pricing)

    cost_table = Table(show_header=True)
    cost_table.add_column("Resource")
    cost_table.add_column("Daily", justify="right")
    cost_table.add_column("Monthly", justify="right")
    cost_table.add_column("Note", style="dim")

    base_total = 0.0
    for c in costs:
        daily = c["daily"]
        monthly = daily * 30
        if "per VM" not in c.get("note", ""):
            base_total += daily
        cost_table.add_row(
            c["resource"],
            f"${daily:.2f}",
            f"${monthly:.2f}",
            c.get("note", ""),
        )

    cost_table.add_row(
        "[bold]Base Total[/bold]",
        f"[bold]${base_total:.2f}[/bold]",
        f"[bold]${base_total * 30:.2f}[/bold]",
        "excl. client VMs",
    )
    console.print(cost_table)
    if live_pricing:
        console.print(
            "  [dim]Prices are on-demand estimates. "
            "Actual costs may vary.[/dim]"
        )
    else:
        console.print(
            "  [dim]Fallback prices (Feb 2025 on-demand) — live "
            "pricing needs working AWS credentials.[/dim]"
        )


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------
def _render_manual_clients_table(clients: list[dict]) -> None:
    """Print a Rich table of registered BYO clients."""
    table = Table(show_header=True)
    table.add_column("Hostname")
    table.add_column("Provider")
    table.add_column("Status")
    table.add_column("Healthy")
    table.add_column("In use")
    table.add_column("GPU")
    table.add_column("Endpoint")

    for c in clients:
        status_val = c.get("status") or "-"
        if status_val == "running":
            status_str = "[green]running[/green]"
        elif status_val in ("stopped", "failed"):
            status_str = f"[red]{status_val}[/red]"
        else:
            status_str = f"[yellow]{status_val}[/yellow]"

        healthy_val = c.get("healthy")
        if healthy_val in (None, ""):
            healthy_str = "-"
        elif str(healthy_val).lower() in ("true", "yes", "ok", "healthy"):
            healthy_str = "[green]yes[/green]"
        else:
            healthy_str = f"[yellow]{healthy_val}[/yellow]"

        gpu_present = c.get("gpu_present")
        gpu_model = c.get("gpu_model") or ""
        if gpu_present is True:
            gpu_str = gpu_model or "yes"
        elif gpu_present is False:
            gpu_str = "no"
        else:
            gpu_str = "-"

        table.add_row(
            c.get("hostname") or "-",
            c.get("provider") or "-",
            status_str,
            healthy_str,
            "yes" if c.get("inuse") else "no",
            gpu_str,
            c.get("endpoint_url") or "-",
        )

    console.print(table)


def _run_status_manual(
    cfg: Config,
    *,
    docker: Docker | None = None,
    workdir_root: Path | None = None,
) -> None:
    """Report compose stack health, allocator HTTP health, and BYO clients.

    `workdir_root` overrides the default compose root (used by tests).
    """
    docker = docker or default_docker()
    workdir = manual.workdir(cfg, workdir_root)

    console.print(
        f"[bold]Manual deployment:[/bold] {cfg.deployment_name}"
    )

    if not workdir.exists():
        console.print(
            f"[yellow]No compose stack at {workdir} — run "
            "`lablink deploy` first.[/yellow]"
        )
        return

    runtime = manual.deployment_runtime(workdir)

    if runtime == "compose":
        ps = docker.compose(workdir, "ps")
        if ps.ok:
            console.print(ps.stdout)
    else:
        console.print(
            "[dim]Lifecycle: managed by external platform "
            "(rendered with --render-only) — container status is not "
            "visible from here; check your platform's workload view.[/dim]"
        )

    base_url = manual.base_url(cfg)
    if runtime == "external":
        # No local container to probe — the allocator only exists at its
        # public URL, staged in the same canonical-URL file the
        # funnel/cloudflare path below reads. A missing URL means
        # --render-only produced a bundle with no supported exposure —
        # there's nothing to reach, so say so explicitly instead of
        # silently falling back to localhost, which has nothing listening
        # on it for an external-runtime deployment.
        base_url = manual.public_url(workdir)
        if not base_url:
            console.print(
                "[red]No public URL recorded for this external-runtime "
                "deployment.[/red]\n"
                f"Expected one at {workdir / manual.CANONICAL_URL_FILENAME} — "
                "re-render with `lablink deploy --render-only` after "
                "setting manual.participant_exposure: cloudflare_tunnel, "
                "or check whether the platform workload is running."
            )
            return
    health = check_health_endpoint(base_url)
    if health.get("healthy"):
        console.print(
            f"[green]Allocator healthy at {base_url}/api/health[/green]"
        )
    elif runtime == "external":
        console.print(
            f"[yellow]Allocator not healthy at {base_url}/api/health "
            "(is the platform workload running?)[/yellow]"
        )
    else:
        console.print(
            f"[yellow]Allocator not healthy at {base_url}/api/health[/yellow]"
        )

    # localhost above is the local liveness probe; it is not the address
    # participants (or BYO clients) use. When the stack is Funnel-exposed,
    # surface the public URL too — and check it, since Funnel being off or
    # the tailnet being down is invisible from a localhost probe.
    public_url = manual.public_url(workdir)
    if public_url:
        label = (
            "Tailscale Funnel"
            if cfg.manual.participant_exposure == "tailscale_funnel"
            else "public"
        )
        console.print(f"[bold]Public URL ({label}):[/bold] {public_url}")
        public_health = check_health_endpoint(public_url)
        if public_health.get("healthy"):
            console.print(f"[green]Reachable at {public_url}/api/health[/green]")
        else:
            detail = public_health.get("detail") or public_health.get("status", "")
            console.print(
                f"[yellow]Not reachable at {public_url}/api/health"
                f"{f' — {detail}' if detail else ''}[/yellow]"
            )

    # No LAN detection on this path — degrades to localhost.
    _print_admin_url(public_url or base_url)

    console.print()
    console.print("[bold]Registered Clients[/bold]")
    creds = manual.admin_credentials(cfg, workdir)
    if creds is None:
        console.print(
            "[yellow]Admin credentials not found in config — "
            "cannot list clients. Open the admin dashboard at "
            f"{public_url or base_url} instead.[/yellow]"
        )
        return

    admin_user, admin_pw = creds
    # base_url is localhost for a compose stack (registered_clients'
    # default) and the recorded public URL for an external runtime — the
    # only address that deployment exists at.
    clients, err = manual.registered_clients(
        cfg, admin_user, admin_pw, base=base_url
    )
    if clients is None:
        console.print(f"[red]Failed to list clients: {err}[/red]")
        return
    if not clients:
        console.print(
            "  [dim]No clients registered yet. On each BYO box, run "
            "`lablink client register …` (token shown by `lablink deploy`).[/dim]"
        )
        return

    _render_manual_clients_table(clients)
    running = sum(1 for c in clients if c.get("status") == "running")
    console.print(
        f"  [dim]{len(clients)} registered, {running} running.[/dim]"
    )


def _render_aws_credentials_error(
    err: AwsQueryError, region: str
) -> None:
    """Report unusable AWS credentials and what it costs this report."""
    console.print("[bold]AWS credentials[/bold]")
    print_aws_error(err)
    profile = os.environ.get("AWS_PROFILE")
    if profile is None:
        profile_desc = "default"
    elif profile == "":
        # An exported-but-empty AWS_PROFILE fails every AWS call; saying
        # "default" here would contradict the error printed above.
        profile_desc = "(AWS_PROFILE is set but empty)"
    else:
        profile_desc = profile
    console.print(
        f"  [dim]Region: {region}, profile: {profile_desc}[/dim]"
    )
    if err.is_auth:
        console.print(
            "  [dim]OpenTofu state, VM inventory and live pricing are "
            "unavailable until this is fixed.[/dim]"
        )
    else:
        # Not a credential problem, so the AWS-backed sections below may
        # still work. Claiming they're unavailable would be a guess.
        console.print(
            "  [dim]Sections below may be incomplete.[/dim]"
        )
    console.print()


def run_status(cfg: Config) -> None:
    """Run health checks and show cost estimate."""
    if getattr(cfg, "provider", "aws") == "manual":
        _run_status_manual(cfg)
        return

    deploy_dir = _get_deploy_dir(cfg)

    console.print()
    console.print(
        Panel(
            "[bold]LabLink Status[/bold]\n"
            f"Deployment: {cfg.deployment_name}  |  "
            f"Environment: {cfg.environment}",
            border_style="cyan",
        )
    )
    console.print()

    # Probed up front: every AWS-backed section below degrades to an
    # empty result on a credential failure, which reads as "nothing is
    # deployed". Reported once here instead of three times below.
    aws_error = aws_credentials_error(cfg.app.region)
    if aws_error is not None:
        _render_aws_credentials_error(aws_error, cfg.app.region)

    # Only a *credential* failure dooms every AWS-backed section below. A
    # non-auth probe failure (transient blip, or STS blocked by a proxy or
    # VPC endpoint policy while EC2 answers fine) proves nothing about
    # EC2, so let the real queries run and report for themselves —
    # _render_client_vms already handles AwsQueryError.
    aws_down = aws_error is not None and aws_error.is_auth
    outputs = _render_tofu_state(deploy_dir, aws_unavailable=aws_down)
    # DNS/HTTP/SSL checks need no AWS credentials, so they still run.
    _render_health_checks(cfg, outputs)
    _print_admin_url(_build_health_url(cfg, outputs))
    _render_client_vms(cfg, aws_unavailable=aws_down)
    _render_cost_estimate(cfg, live_pricing=not aws_down)
