"""Tests for lablink_cli.commands.cleanup run_cleanup orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from lablink_cli.commands.cleanup import cleanup_iam, run_cleanup


# ------------------------------------------------------------------
# cleanup_iam
# ------------------------------------------------------------------
class TestCleanupIam:
    def test_dry_run(self):
        session = MagicMock()
        iam = MagicMock()
        sts = MagicMock()
        session.client.side_effect = (
            lambda svc, **kw: sts if svc == "sts" else iam
        )
        sts.get_caller_identity.return_value = {"Account": "123456789012"}

        # Instance profiles exist
        iam.get_instance_profile.return_value = {
            "InstanceProfile": {"Roles": [{"RoleName": "role-1"}]}
        }
        # Roles have policies
        iam.list_attached_role_policies.return_value = {
            "AttachedPolicies": [{"PolicyArn": "arn:aws:iam::123456789012:policy/test"}]
        }
        # Policies exist
        iam.get_policy.return_value = {"Policy": {}}

        cleanup_iam(session, "mylab", "dev", "sleap", dry_run=True)

        # In dry_run, should not delete anything
        iam.delete_instance_profile.assert_not_called()
        iam.delete_role.assert_not_called()
        iam.delete_policy.assert_not_called()


# ------------------------------------------------------------------
# run_cleanup
# ------------------------------------------------------------------
class TestRunCleanup:
    @patch("lablink_cli.commands.cleanup.cleanup_local")
    @patch("lablink_cli.commands.cleanup.cleanup_dynamodb_env_locks")
    @patch("lablink_cli.commands.cleanup.cleanup_s3_env_state")
    @patch(
        "lablink_cli.commands.cleanup.resolve_bucket_name",
        return_value="lablink-tf-state-123456789012",
    )
    @patch("lablink_cli.commands.cleanup.cleanup_iam")
    @patch("lablink_cli.commands.cleanup.cleanup_elastic_ips")
    @patch("lablink_cli.commands.cleanup.cleanup_key_pairs")
    @patch("lablink_cli.commands.cleanup.cleanup_security_groups")
    @patch("lablink_cli.commands.cleanup.cleanup_ec2_instances")
    @patch("lablink_cli.commands.cleanup.check_credentials")
    @patch("lablink_cli.commands.cleanup._get_session")
    def test_dry_run(
        self,
        mock_session,
        mock_creds,
        mock_ec2,
        mock_sg,
        mock_kp,
        mock_eip,
        mock_iam,
        mock_resolve,
        mock_s3,
        mock_dynamo,
        mock_local,
        mock_cfg,
    ):
        session = MagicMock()
        sts = MagicMock()
        sts.get_caller_identity.return_value = {"Account": "123456789012"}
        ec2_client = MagicMock()
        session.client.side_effect = lambda svc, **kw: (
            sts if svc == "sts" else ec2_client
        )
        mock_session.return_value = session

        run_cleanup(mock_cfg, dry_run=True)

        mock_ec2.assert_called_once()
        mock_sg.assert_called_once()
        mock_kp.assert_called_once()
        mock_eip.assert_called_once()
        mock_iam.assert_called_once()
        mock_s3.assert_called_once()
        mock_dynamo.assert_called_once()
        mock_local.assert_called_once()
        # Verify dry_run passed through
        _, _, _, _, dry_run = mock_ec2.call_args[0]
        assert dry_run is True

    @patch("lablink_cli.commands.cleanup.cleanup_local")
    @patch("lablink_cli.commands.cleanup.cleanup_dynamodb_env_locks")
    @patch("lablink_cli.commands.cleanup.cleanup_s3_env_state")
    @patch(
        "lablink_cli.commands.cleanup.resolve_bucket_name",
        return_value="lablink-tf-state-123456789012",
    )
    @patch("lablink_cli.commands.cleanup.cleanup_iam")
    @patch("lablink_cli.commands.cleanup.cleanup_elastic_ips")
    @patch("lablink_cli.commands.cleanup.cleanup_key_pairs")
    @patch("lablink_cli.commands.cleanup.cleanup_security_groups")
    @patch("lablink_cli.commands.cleanup.cleanup_ec2_instances")
    @patch("lablink_cli.commands.cleanup.check_credentials")
    @patch("lablink_cli.commands.cleanup._get_session")
    def test_s3_and_dynamo_always_called(
        self,
        mock_session,
        mock_creds,
        mock_ec2,
        mock_sg,
        mock_kp,
        mock_eip,
        mock_iam,
        mock_resolve,
        mock_s3,
        mock_dynamo,
        mock_local,
        mock_cfg,
    ):
        session = MagicMock()
        sts = MagicMock()
        sts.get_caller_identity.return_value = {"Account": "123456789012"}
        ec2_client = MagicMock()
        session.client.side_effect = lambda svc, **kw: (
            sts if svc == "sts" else ec2_client
        )
        mock_session.return_value = session

        run_cleanup(mock_cfg, dry_run=False)

        mock_s3.assert_called_once_with(
            session, "mylab", "dev", "lablink-tf-state-123456789012", False
        )
        mock_dynamo.assert_called_once_with(
            session, "mylab", "dev", "lablink-tf-state-123456789012", False
        )
        mock_local.assert_called_once()
