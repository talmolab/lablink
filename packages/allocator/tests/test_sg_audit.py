"""Tests for the SG audit module used pre-`terraform apply`."""
import pytest

from lablink_allocator_service.utils.sg_audit import (
    SGAuditFailure,
    audit_terraform_plan,
)


CLEAN_PLAN = """
  + resource "aws_security_group" "lablink_sg" {
      + ingress {
          + from_port       = 22
          + to_port         = 22
          + protocol        = "tcp"
          + cidr_blocks     = ["0.0.0.0/0"]
        }
      + ingress {
          + from_port       = 6080
          + to_port         = 6080
          + protocol        = "tcp"
          + security_groups = ["sg-allocator"]
        }
      + ingress {
          + from_port       = 7070
          + to_port         = 7070
          + protocol        = "tcp"
          + security_groups = ["sg-allocator"]
        }
    }
"""

VIOLATING_6080 = """
  + ingress {
      + from_port   = 6080
      + to_port     = 6080
      + protocol    = "tcp"
      + cidr_blocks = ["0.0.0.0/0"]
    }
"""

VIOLATING_7070_V6 = """
  + ingress {
      + from_port        = 7070
      + to_port          = 7070
      + protocol         = "tcp"
      + ipv6_cidr_blocks = ["::/0"]
    }
"""

VIOLATING_6080_MIXED_CIDR = """
  + ingress {
      + from_port   = 6080
      + to_port     = 6080
      + protocol    = "tcp"
      + cidr_blocks = ["10.0.0.0/8", "0.0.0.0/0"]
    }
"""


def test_audit_passes_on_clean_plan():
    """SG-locked :6080 and :7070, plus :22 open to the world, is acceptable."""
    audit_terraform_plan(CLEAN_PLAN)  # should not raise


def test_audit_fails_on_public_6080():
    with pytest.raises(SGAuditFailure, match="6080"):
        audit_terraform_plan(VIOLATING_6080)


def test_audit_fails_on_ipv6_public_7070():
    with pytest.raises(SGAuditFailure, match="7070"):
        audit_terraform_plan(VIOLATING_7070_V6)


def test_audit_fails_when_public_cidr_is_one_of_many():
    """An ingress with a list containing 0.0.0.0/0 alongside private
    ranges still grants public access — must reject."""
    with pytest.raises(SGAuditFailure, match="6080"):
        audit_terraform_plan(VIOLATING_6080_MIXED_CIDR)


def test_audit_fails_closed_on_unrecognized_output():
    """If the plan text contains no ingress blocks, refuse to apply
    rather than silently letting an unparseable plan through."""
    with pytest.raises(SGAuditFailure, match="parse"):
        audit_terraform_plan("garbage that does not look like a plan")


def test_audit_ignores_unprotected_ports():
    """Public ingress on a port we don't protect (e.g., :443) is not
    this audit's job — it's the bigger SG-cleanup follow-up's job."""
    plan = """
      + ingress {
          + from_port   = 443
          + to_port     = 443
          + protocol    = "tcp"
          + cidr_blocks = ["0.0.0.0/0"]
        }
    """
    audit_terraform_plan(plan)  # should not raise
