"""SG audit run before `terraform apply` in /api/launch.

Refuses any client ingress on :6080 or :7070 that includes 0.0.0.0/0
or ::/0. Fails closed on unrecognizable plan output: if the parser
can't find any ingress blocks, refuse to proceed.

The audit takes the textual output of `terraform plan -no-color` and
walks each `ingress { ... }` block, checking the protected ports for
public-Internet ingress.
"""
import re


class SGAuditFailure(RuntimeError):
    """Raised when the audit detects a violating ingress rule, or
    when the plan text can't be parsed (fail-closed semantics)."""


_INGRESS_RE = re.compile(
    r"\bingress\s*\{(?P<body>[^}]*?)\}",
    re.MULTILINE | re.DOTALL,
)
_FROM_PORT_RE = re.compile(r"from_port\s*=\s*(\d+)")
_CIDR_RE = re.compile(r"cidr_blocks\s*=\s*\[([^\]]*)\]")
_V6_CIDR_RE = re.compile(r"ipv6_cidr_blocks\s*=\s*\[([^\]]*)\]")

SG_AUDIT_PROTECTED_PORTS = {6080, 7070}
_PUBLIC_V4 = "0.0.0.0/0"
_PUBLIC_V6 = "::/0"


def audit_terraform_plan(plan_text: str) -> None:
    """Walk every ingress block in the plan; refuse the apply if any
    rule on a protected port exposes 0.0.0.0/0 or ::/0.

    Raises:
        SGAuditFailure: on a violating ingress rule OR when the plan
            text contains no ingress blocks at all (fail closed).
    """
    if "ingress" not in plan_text and "aws_security_group" not in plan_text:
        raise SGAuditFailure(
            "Couldn't parse Terraform plan (no ingress blocks). "
            "Refusing to apply (fail closed)."
        )
    for m in _INGRESS_RE.finditer(plan_text):
        body = m.group("body")
        port_m = _FROM_PORT_RE.search(body)
        if not port_m:
            continue
        port = int(port_m.group(1))
        if port not in SG_AUDIT_PROTECTED_PORTS:
            continue
        v4 = _CIDR_RE.search(body)
        v6 = _V6_CIDR_RE.search(body)
        if v4 and _PUBLIC_V4 in v4.group(1):
            raise SGAuditFailure(
                f"Port {port} has 0.0.0.0/0 ingress. "
                f"Restrict to allocator SG."
            )
        if v6 and _PUBLIC_V6 in v6.group(1):
            raise SGAuditFailure(
                f"Port {port} has ::/0 ingress. "
                f"Restrict to allocator SG."
            )
