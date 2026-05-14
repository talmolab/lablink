"""Tests for the SG audit module used pre-`terraform apply`.

The audit consumes the structured JSON plan from
``terraform show -json <planfile>``. Fixtures are parsed Python dicts
that mirror that schema.
"""
import pytest

from lablink_allocator_service.utils.sg_audit import (
    SGAuditFailure,
    audit_terraform_plan,
)


def _sg_change(actions, after, address="aws_security_group.lablink_sg"):
    """Build a minimal resource_changes entry for an aws_security_group."""
    return {
        "address": address,
        "type": "aws_security_group",
        "name": address.split(".")[-1],
        "change": {
            "actions": actions,
            "before": None,
            "after": after,
            "after_unknown": {},
        },
    }


def _plan(*resource_changes):
    return {"resource_changes": list(resource_changes)}


CLEAN_INGRESS = [
    {
        "from_port": 22,
        "to_port": 22,
        "protocol": "tcp",
        "cidr_blocks": ["0.0.0.0/0"],
        "ipv6_cidr_blocks": [],
        "security_groups": [],
    },
    {
        "from_port": 6080,
        "to_port": 6080,
        "protocol": "tcp",
        "cidr_blocks": [],
        "ipv6_cidr_blocks": [],
        "security_groups": ["sg-allocator"],
        "description": "KasmVNC; allocator-only",
    },
    {
        "from_port": 7070,
        "to_port": 7070,
        "protocol": "tcp",
        "cidr_blocks": [],
        "ipv6_cidr_blocks": [],
        "security_groups": ["sg-allocator"],
    },
]


def test_audit_passes_on_clean_plan():
    """SG-locked :6080 and :7070, plus :22 open to the world, is acceptable."""
    plan = _plan(_sg_change(["create"], {"ingress": CLEAN_INGRESS}))
    audit_terraform_plan(plan)  # should not raise


def test_audit_fails_on_public_6080():
    plan = _plan(_sg_change(["create"], {
        "ingress": [{
            "from_port": 6080,
            "to_port": 6080,
            "protocol": "tcp",
            "cidr_blocks": ["0.0.0.0/0"],
            "ipv6_cidr_blocks": [],
        }],
    }))
    with pytest.raises(SGAuditFailure, match="6080"):
        audit_terraform_plan(plan)


def test_audit_fails_on_ipv6_public_7070():
    plan = _plan(_sg_change(["create"], {
        "ingress": [{
            "from_port": 7070,
            "to_port": 7070,
            "protocol": "tcp",
            "cidr_blocks": [],
            "ipv6_cidr_blocks": ["::/0"],
        }],
    }))
    with pytest.raises(SGAuditFailure, match="7070"):
        audit_terraform_plan(plan)


def test_audit_fails_when_public_cidr_is_one_of_many():
    """An ingress with a list containing 0.0.0.0/0 alongside private
    ranges still grants public access — must reject."""
    plan = _plan(_sg_change(["create"], {
        "ingress": [{
            "from_port": 6080,
            "to_port": 6080,
            "protocol": "tcp",
            "cidr_blocks": ["10.0.0.0/8", "0.0.0.0/0"],
            "ipv6_cidr_blocks": [],
        }],
    }))
    with pytest.raises(SGAuditFailure, match="6080"):
        audit_terraform_plan(plan)


def test_audit_passes_when_no_sg_change_in_plan():
    """Scale-up path: only aws_instance is being added; the SG was
    created (and audited) on a prior apply. Audit must pass."""
    plan = {"resource_changes": [
        {
            "address": "aws_instance.lablink_vm[0]",
            "type": "aws_instance",
            "name": "lablink_vm",
            "change": {
                "actions": ["create"],
                "before": None,
                "after": {"ami": "ami-12345", "instance_type": "t2.medium"},
                "after_unknown": {},
            },
        },
    ]}
    audit_terraform_plan(plan)  # should not raise


def test_audit_passes_when_sg_is_noop():
    """A no-op SG change introduces no new exposure — skip the audit."""
    plan = _plan(_sg_change(["no-op"], {"ingress": CLEAN_INGRESS}))
    audit_terraform_plan(plan)  # should not raise


def test_audit_passes_when_sg_is_deleted():
    """A pure delete removes exposure; nothing to audit."""
    plan = _plan(_sg_change(["delete"], None))
    audit_terraform_plan(plan)  # should not raise


def test_audit_fails_when_create_has_no_ingress_field():
    """Defensive: an SG create with no 'ingress' key is unparseable.
    Refuse rather than silently approve."""
    plan = _plan(_sg_change(["create"], {"name": "weird-no-ingress"}))
    with pytest.raises(SGAuditFailure, match="no 'ingress' field"):
        audit_terraform_plan(plan)


def test_audit_fails_when_create_has_null_after():
    """Defensive: an SG create with no 'after' state is unparseable."""
    plan = _plan(_sg_change(["create"], None))
    with pytest.raises(SGAuditFailure, match="no 'after' state"):
        audit_terraform_plan(plan)


def test_audit_fails_when_plan_is_not_a_dict():
    with pytest.raises(SGAuditFailure, match="not a dict"):
        audit_terraform_plan("not a plan")


def test_audit_fails_when_resource_changes_is_not_a_list():
    with pytest.raises(SGAuditFailure, match="resource_changes"):
        audit_terraform_plan({"resource_changes": "not a list"})


def test_audit_ignores_unprotected_ports():
    """Public ingress on a port we don't protect (e.g., :443) is not
    this audit's job."""
    plan = _plan(_sg_change(["create"], {
        "ingress": [{
            "from_port": 443,
            "to_port": 443,
            "protocol": "tcp",
            "cidr_blocks": ["0.0.0.0/0"],
            "ipv6_cidr_blocks": [],
        }],
    }))
    audit_terraform_plan(plan)  # should not raise


def test_audit_handles_replace_action():
    """A delete+create replace must still audit the create's 'after'."""
    plan = _plan(_sg_change(["delete", "create"], {
        "ingress": [{
            "from_port": 6080,
            "to_port": 6080,
            "protocol": "tcp",
            "cidr_blocks": ["0.0.0.0/0"],
            "ipv6_cidr_blocks": [],
        }],
    }))
    with pytest.raises(SGAuditFailure, match="6080"):
        audit_terraform_plan(plan)
