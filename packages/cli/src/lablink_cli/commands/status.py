"""Health checks and cost estimation for LabLink deployments."""

from __future__ import annotations

import json
import socket
import ssl
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

import boto3
from botocore.exceptions import ClientError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from lablink_allocator_service.conf.structured_config import Config

console = Console()

DEPLOY_DIR = Path.home() / ".lablink" / "deploy"

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
    "cloudwatch": 0.067,
    "cloudtrail": 0.10,
}


# ------------------------------------------------------------------
# Terraform state helpers
# ------------------------------------------------------------------
def get_terraform_outputs(deploy_dir: Path) -> dict[str, str]:
    """Read terraform outputs as a dict."""
    try:
        result = subprocess.run(
            ["terraform", "output", "-json"],
            cwd=deploy_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        raw = json.loads(result.stdout)
        return {
            k: v.get("value", "")
            for k, v in raw.items()
        }
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return {}


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


def estimate_costs(cfg: Config) -> list[dict]:
    """Estimate daily costs for the deployment."""
    region = cfg.app.region
    location = REGION_NAME_MAP.get(region, region)
    costs: list[dict] = []

    # Try AWS Pricing API (only available in us-east-1)
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

    # Monitoring
    if cfg.monitoring.enabled:
        costs.append(
            {
                "resource": "CloudWatch Alarms",
                "daily": FALLBACK_COSTS["cloudwatch"],
                "note": "",
            }
        )
        costs.append(
            {
                "resource": "CloudTrail",
                "daily": FALLBACK_COSTS["cloudtrail"],
                "note": "",
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


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------
def run_status(cfg: Config) -> None:
    """Run health checks and show cost estimate."""
    deploy_dir = DEPLOY_DIR

    console.print()
    console.print(
        Panel(
            "[bold]LabLink Status[/bold]",
            border_style="cyan",
        )
    )
    console.print()

    # --- Terraform outputs ---
    outputs = {}
    if deploy_dir.exists():
        console.print("[bold]Terraform State[/bold]")
        outputs = get_terraform_outputs(deploy_dir)
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
                "  [yellow]No Terraform state found[/yellow]"
            )
        console.print()

    ip = outputs.get("ec2_public_ip", "")
    domain = cfg.dns.domain if cfg.dns.enabled else ""
    use_https = cfg.ssl.provider != "none"

    # --- Health checks ---
    console.print("[bold]Health Checks[/bold]")
    checks = []

    # DNS
    if domain:
        checks.append(check_dns(domain, ip))

    # HTTP
    if domain and use_https:
        url = f"https://{domain}"
    elif domain:
        url = f"http://{domain}"
    elif ip:
        url = f"http://{ip}:5000"
    else:
        url = ""

    if url:
        checks.append(check_http(url))

    # SSL
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

    # --- Cost estimate ---
    console.print("[bold]Cost Estimate (daily)[/bold]")
    costs = estimate_costs(cfg)

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
    console.print(
        "  [dim]Prices are on-demand estimates. "
        "Actual costs may vary.[/dim]"
    )
