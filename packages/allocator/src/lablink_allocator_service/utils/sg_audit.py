"""SG audit run before `terraform apply` in /api/launch.

Refuses any client ingress on :6080 or :7070 that includes 0.0.0.0/0
or ::/0. Inspects the structured JSON plan produced by
``terraform show -json <planfile>`` rather than parsing the freeform
text plan, so the audit is robust to provider rendering changes.

Fails closed: if the plan JSON has an aws_security_group change with
no usable ``after.ingress`` field, the audit refuses rather than
silently passing.
"""
from typing import Any


class SGAuditFailure(RuntimeError):
    """Raised when the audit detects a violating ingress rule, or
    when the plan can't be interpreted (fail-closed semantics)."""


SG_AUDIT_PROTECTED_PORTS = {6080, 7070}
_PUBLIC_V4 = "0.0.0.0/0"
_PUBLIC_V6 = "::/0"


def audit_terraform_plan(plan_json: Any) -> None:
    """Walk every aws_security_group change in the JSON plan; refuse
    the apply if any post-change ingress rule on a protected port
    exposes 0.0.0.0/0 or ::/0.

    Args:
        plan_json: parsed output of ``terraform show -json <planfile>``.
            Typed ``Any`` because ``json.loads`` can yield any shape;
            the function validates the top-level structure before use.

    Raises:
        SGAuditFailure: on a violating ingress rule, or when an
            aws_security_group change has create/update actions but
            no parseable ingress in its 'after' state (fail closed).
    """
    if not isinstance(plan_json, dict):
        raise SGAuditFailure(
            "Plan JSON is not a dict; cannot audit. "
            "Refusing to apply (fail closed)."
        )

    resource_changes = plan_json.get("resource_changes", [])
    if not isinstance(resource_changes, list):
        raise SGAuditFailure(
            "Plan JSON missing resource_changes array; "
            "cannot audit. Refusing to apply (fail closed)."
        )

    for rc in resource_changes:
        if not isinstance(rc, dict):
            continue
        if rc.get("type") != "aws_security_group":
            continue

        change = rc.get("change") or {}
        actions = change.get("actions") or []
        # Only audit changes that result in a live SG with ingress rules.
        # Pure delete / no-op / read introduce no new exposure.
        if "create" not in actions and "update" not in actions:
            continue

        after = change.get("after")
        if not isinstance(after, dict):
            raise SGAuditFailure(
                f"aws_security_group ({rc.get('address')}) "
                f"change has no 'after' state to audit. "
                f"Refusing to apply (fail closed)."
            )

        ingress = after.get("ingress")
        if ingress is None:
            raise SGAuditFailure(
                f"aws_security_group ({rc.get('address')}) has no "
                f"'ingress' field in 'after'. "
                f"Refusing to apply (fail closed)."
            )
        if not isinstance(ingress, list):
            raise SGAuditFailure(
                f"aws_security_group ({rc.get('address')}) 'ingress' "
                f"is not a list. Refusing to apply (fail closed)."
            )

        for rule in ingress:
            if not isinstance(rule, dict):
                continue
            port = rule.get("from_port")
            if port not in SG_AUDIT_PROTECTED_PORTS:
                continue
            cidrs = rule.get("cidr_blocks") or []
            v6_cidrs = rule.get("ipv6_cidr_blocks") or []
            if isinstance(cidrs, list) and _PUBLIC_V4 in cidrs:
                raise SGAuditFailure(
                    f"Port {port} has 0.0.0.0/0 ingress. "
                    f"Restrict to allocator SG."
                )
            if isinstance(v6_cidrs, list) and _PUBLIC_V6 in v6_cidrs:
                raise SGAuditFailure(
                    f"Port {port} has ::/0 ingress. "
                    f"Restrict to allocator SG."
                )
