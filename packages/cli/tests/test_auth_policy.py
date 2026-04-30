"""Tests for the lablink permission-set policy module."""

from __future__ import annotations

import json

from lablink_cli.auth import policy


def test_managed_policy_arns_cover_required_services():
    arns = policy.MANAGED_POLICY_ARNS
    assert "arn:aws:iam::aws:policy/AmazonEC2FullAccess" in arns
    assert "arn:aws:iam::aws:policy/ElasticLoadBalancingFullAccess" in arns
    assert "arn:aws:iam::aws:policy/AmazonRoute53FullAccess" in arns
    assert "arn:aws:iam::aws:policy/IAMFullAccess" in arns
    assert "arn:aws:iam::aws:policy/CloudWatchFullAccess" in arns
    assert "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess" in arns
    assert "arn:aws:iam::aws:policy/AWSCloudTrail_FullAccess" in arns
    assert "arn:aws:iam::aws:policy/AmazonSNSFullAccess" in arns


def test_inline_policy_is_valid_iam_policy_json():
    doc = policy.INLINE_POLICY
    assert doc["Version"] == "2012-10-17"
    assert isinstance(doc["Statement"], list)
    assert len(doc["Statement"]) > 0
    for stmt in doc["Statement"]:
        assert "Sid" in stmt
        assert stmt["Effect"] == "Allow"
        assert "Action" in stmt
        assert "Resource" in stmt


def test_inline_policy_scopes_terraform_state_bucket():
    statements = {s["Sid"]: s for s in policy.INLINE_POLICY["Statement"]}
    s3 = statements["TerraformStateBucket"]
    assert "arn:aws:s3:::lablink-tf-state-*" in s3["Resource"]
    assert "arn:aws:s3:::lablink-tf-state-*/*" in s3["Resource"]


def test_inline_policy_scopes_cloudtrail_bucket():
    statements = {s["Sid"]: s for s in policy.INLINE_POLICY["Statement"]}
    ct = statements["CloudTrailLogsBucket"]
    assert "arn:aws:s3:::*-cloudtrail-bucket-*" in ct["Resource"]


def test_inline_policy_scopes_dynamodb_lock_table():
    statements = {s["Sid"]: s for s in policy.INLINE_POLICY["Statement"]}
    ddb = statements["TerraformLockTable"]
    assert ddb["Resource"] == "arn:aws:dynamodb:*:*:table/lock-table"


def test_inline_policy_includes_sts_get_caller_identity():
    statements = {s["Sid"]: s for s in policy.INLINE_POLICY["Statement"]}
    sts = statements["STS"]
    assert "sts:GetCallerIdentity" in sts["Action"]


def test_inline_policy_includes_budgets():
    statements = {s["Sid"]: s for s in policy.INLINE_POLICY["Statement"]}
    budgets = statements["Budgets"]
    assert "budgets:*" in budgets["Action"]


def test_render_inline_policy_returns_valid_json_string():
    rendered = policy.render_inline_policy_json()
    parsed = json.loads(rendered)
    assert parsed == policy.INLINE_POLICY


def test_audit_actions_lists_one_action_per_managed_policy():
    """The audit dry-run uses one representative action per managed policy."""
    actions = policy.AUDIT_ACTIONS
    assert isinstance(actions, list)
    # One per managed policy + at least one per inline statement
    assert len(actions) >= len(policy.MANAGED_POLICY_ARNS)
    for action in actions:
        assert isinstance(action, str)
        assert ":" in action  # service:action format
