"""LabLink permission set — single source of truth.

The contents here are what `lablink login` displays during the
first-time Identity Center bootstrap and what `lablink doctor` audits
against the live SSO session.

When `lablink-template` adds a Terraform resource that needs a service
not currently in MANAGED_POLICY_ARNS or INLINE_POLICY, update this
file. `lablink doctor` will flag the gap; the operator runs
`lablink login --update-policy` to refresh their permission set.
"""

from __future__ import annotations

import json
from typing import Any

# AWS-managed policies attached to the lablink permission set.
# Each maps to one or more Terraform resource types in
# lablink-template/lablink-infrastructure/*.tf.
MANAGED_POLICY_ARNS: list[str] = [
    "arn:aws:iam::aws:policy/AmazonEC2FullAccess",
    "arn:aws:iam::aws:policy/ElasticLoadBalancingFullAccess",
    "arn:aws:iam::aws:policy/AmazonRoute53FullAccess",
    "arn:aws:iam::aws:policy/IAMFullAccess",
    "arn:aws:iam::aws:policy/CloudWatchFullAccess",
    "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess",
    "arn:aws:iam::aws:policy/AWSCloudTrail_FullAccess",
    "arn:aws:iam::aws:policy/AmazonSNSFullAccess",
]

# Inline policy attached to the same permission set, scoping
# resource-level access where AWS supports it.
INLINE_POLICY: dict[str, Any] = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "STS",
            "Effect": "Allow",
            "Action": ["sts:GetCallerIdentity"],
            "Resource": "*",
        },
        {
            "Sid": "TerraformStateBucket",
            "Effect": "Allow",
            "Action": ["s3:*"],
            "Resource": [
                "arn:aws:s3:::lablink-tf-state-*",
                "arn:aws:s3:::lablink-tf-state-*/*",
            ],
        },
        {
            "Sid": "CloudTrailLogsBucket",
            "Effect": "Allow",
            "Action": ["s3:*"],
            "Resource": [
                "arn:aws:s3:::*-cloudtrail-bucket-*",
                "arn:aws:s3:::*-cloudtrail-bucket-*/*",
            ],
        },
        {
            "Sid": "TerraformLockTable",
            "Effect": "Allow",
            "Action": ["dynamodb:*"],
            "Resource": "arn:aws:dynamodb:*:*:table/lock-table",
        },
        {
            "Sid": "Budgets",
            "Effect": "Allow",
            "Action": ["budgets:*"],
            "Resource": "*",
        },
    ],
}

# Representative read-only actions used by `lablink doctor` to dry-run
# the live permission set via iam.simulate_principal_policy. One per
# managed policy + one per inline statement.
AUDIT_ACTIONS: list[str] = [
    "ec2:DescribeInstances",
    "elasticloadbalancing:DescribeLoadBalancers",
    "route53:ListHostedZones",
    "iam:GetRole",
    "cloudwatch:DescribeAlarms",
    "logs:DescribeLogGroups",
    "cloudtrail:DescribeTrails",
    "sns:ListTopics",
    "sts:GetCallerIdentity",
    "s3:ListBucket",
    "dynamodb:DescribeTable",
    "budgets:DescribeBudgets",
]

PERMISSION_SET_NAME_DEFAULT = "lablink"


def render_inline_policy_json() -> str:
    """Return the inline policy as a pretty-printed JSON string for clipboard."""
    return json.dumps(INLINE_POLICY, indent=2)
