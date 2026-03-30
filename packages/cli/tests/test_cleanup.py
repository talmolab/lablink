"""Tests for lablink_cli.commands.cleanup resource cleanup."""

from __future__ import annotations

import shutil
from unittest.mock import MagicMock, call, patch

import pytest
from botocore.exceptions import ClientError

from lablink_cli.commands.cleanup import (
    _delete_if_exists,
    cleanup_dynamodb,
    cleanup_ec2_instances,
    cleanup_elastic_ips,
    cleanup_key_pairs,
    cleanup_local,
    cleanup_s3_state,
    cleanup_security_groups,
)


# ------------------------------------------------------------------
# _delete_if_exists
# ------------------------------------------------------------------
class TestDeleteIfExists:
    def test_success(self):
        fn = MagicMock()
        result = _delete_if_exists("test action", fn, "arg1")
        assert result is True
        fn.assert_called_once_with("arg1")

    def test_not_found(self):
        fn = MagicMock()
        fn.side_effect = ClientError(
            {"Error": {"Code": "NotFoundException", "Message": ""}},
            "Delete",
        )
        result = _delete_if_exists("test action", fn, "arg1")
        assert result is False

    def test_other_error_raises(self):
        fn = MagicMock()
        fn.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": ""}},
            "Delete",
        )
        with pytest.raises(ClientError):
            _delete_if_exists("test action", fn, "arg1")


# ------------------------------------------------------------------
# cleanup_ec2_instances
# ------------------------------------------------------------------
class TestCleanupEc2Instances:
    def test_no_instances_found(self):
        ec2 = MagicMock()
        ec2.describe_instances.return_value = {"Reservations": []}

        cleanup_ec2_instances(ec2, "us-east-1", "mylab", "dev", dry_run=False)
        ec2.terminate_instances.assert_not_called()

    def test_dry_run_no_terminate(self):
        ec2 = MagicMock()
        ec2.describe_instances.return_value = {
            "Reservations": [
                {"Instances": [{"InstanceId": "i-123"}]}
            ]
        }

        cleanup_ec2_instances(ec2, "us-east-1", "mylab", "dev", dry_run=True)
        ec2.terminate_instances.assert_not_called()

    def test_terminate_instances(self):
        ec2 = MagicMock()
        ec2.describe_instances.return_value = {
            "Reservations": [
                {"Instances": [
                    {"InstanceId": "i-123"},
                    {"InstanceId": "i-456"},
                ]}
            ]
        }
        waiter = MagicMock()
        ec2.get_waiter.return_value = waiter

        cleanup_ec2_instances(ec2, "us-east-1", "mylab", "dev", dry_run=False)
        assert ec2.terminate_instances.call_count == 2
        waiter.wait.assert_called_once()


# ------------------------------------------------------------------
# cleanup_security_groups
# ------------------------------------------------------------------
class TestCleanupSecurityGroups:
    def test_no_groups_found(self):
        ec2 = MagicMock()
        ec2.describe_security_groups.return_value = {"SecurityGroups": []}

        cleanup_security_groups(ec2, "mylab", "dev", dry_run=False)

    def test_dry_run_no_delete(self):
        ec2 = MagicMock()
        ec2.describe_security_groups.side_effect = [
            {"SecurityGroups": [{"GroupName": "sg-1", "GroupId": "sg-123"}]},
            {"SecurityGroups": []},
            {"SecurityGroups": []},
        ]

        cleanup_security_groups(ec2, "mylab", "dev", dry_run=True)
        ec2.delete_security_group.assert_not_called()


# ------------------------------------------------------------------
# cleanup_key_pairs
# ------------------------------------------------------------------
class TestCleanupKeyPairs:
    def test_no_keypairs_found(self):
        ec2 = MagicMock()
        ec2.describe_key_pairs.side_effect = ClientError(
            {"Error": {"Code": "InvalidKeyPair.NotFound", "Message": ""}},
            "DescribeKeyPairs",
        )

        cleanup_key_pairs(ec2, "mylab", "dev", "sleap", dry_run=False)
        ec2.delete_key_pair.assert_not_called()

    def test_dry_run_no_delete(self):
        ec2 = MagicMock()
        ec2.describe_key_pairs.return_value = {"KeyPairs": [{"KeyName": "test"}]}

        cleanup_key_pairs(ec2, "mylab", "dev", "sleap", dry_run=True)
        ec2.delete_key_pair.assert_not_called()


# ------------------------------------------------------------------
# cleanup_elastic_ips
# ------------------------------------------------------------------
class TestCleanupElasticIps:
    def test_no_ips_found(self):
        ec2 = MagicMock()
        ec2.describe_addresses.return_value = {"Addresses": []}

        cleanup_elastic_ips(ec2, "mylab", "dev", dry_run=False)
        ec2.release_address.assert_not_called()

    def test_release_ip(self):
        ec2 = MagicMock()
        ec2.describe_addresses.return_value = {
            "Addresses": [
                {"AllocationId": "eipalloc-123", "PublicIp": "1.2.3.4"}
            ]
        }

        cleanup_elastic_ips(ec2, "mylab", "dev", dry_run=False)
        ec2.release_address.assert_called_once_with(AllocationId="eipalloc-123")

    def test_disassociate_before_release(self):
        ec2 = MagicMock()
        ec2.describe_addresses.return_value = {
            "Addresses": [
                {
                    "AllocationId": "eipalloc-123",
                    "PublicIp": "1.2.3.4",
                    "AssociationId": "eipassoc-456",
                }
            ]
        }

        cleanup_elastic_ips(ec2, "mylab", "dev", dry_run=False)
        ec2.disassociate_address.assert_called_once_with(
            AssociationId="eipassoc-456"
        )
        ec2.release_address.assert_called_once()


# ------------------------------------------------------------------
# cleanup_s3_state
# ------------------------------------------------------------------
class TestCleanupS3State:
    def test_bucket_not_found(self):
        session = MagicMock()
        sts = MagicMock()
        s3 = MagicMock()
        session.client.side_effect = lambda svc, **kw: sts if svc == "sts" else s3
        sts.get_caller_identity.return_value = {"Account": "123456789012"}
        s3.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": ""}},
            "HeadBucket",
        )

        cleanup_s3_state(session, dry_run=False)
        s3.delete_bucket.assert_not_called()

    def test_dry_run_no_delete(self):
        session = MagicMock()
        sts = MagicMock()
        s3 = MagicMock()
        session.client.side_effect = lambda svc, **kw: sts if svc == "sts" else s3
        sts.get_caller_identity.return_value = {"Account": "123456789012"}
        s3.head_bucket.return_value = {}
        s3.list_object_versions.return_value = {
            "Versions": [{"Key": "state.tf", "VersionId": "v1"}],
            "DeleteMarkers": [],
        }

        cleanup_s3_state(session, dry_run=True)
        s3.delete_object.assert_not_called()
        s3.delete_bucket.assert_not_called()


# ------------------------------------------------------------------
# cleanup_dynamodb
# ------------------------------------------------------------------
class TestCleanupDynamodb:
    def test_table_not_found(self):
        session = MagicMock()
        dynamodb = MagicMock()
        session.client.return_value = dynamodb

        not_found_exc = type("ResourceNotFoundException", (Exception,), {})
        dynamodb.exceptions.ResourceNotFoundException = not_found_exc
        dynamodb.describe_table.side_effect = not_found_exc()

        cleanup_dynamodb(session, dry_run=False)
        dynamodb.delete_table.assert_not_called()

    def test_delete_table(self):
        session = MagicMock()
        dynamodb = MagicMock()
        session.client.return_value = dynamodb
        dynamodb.describe_table.return_value = {"Table": {}}

        cleanup_dynamodb(session, dry_run=False)
        dynamodb.delete_table.assert_called_once_with(TableName="lock-table")

    def test_dry_run_no_delete(self):
        session = MagicMock()
        dynamodb = MagicMock()
        session.client.return_value = dynamodb
        dynamodb.describe_table.return_value = {"Table": {}}

        cleanup_dynamodb(session, dry_run=True)
        dynamodb.delete_table.assert_not_called()


# ------------------------------------------------------------------
# cleanup_local
# ------------------------------------------------------------------
class TestCleanupLocal:
    @patch("lablink_cli.commands.cleanup._get_deploy_dir")
    def test_dir_not_found(self, mock_deploy_dir, mock_cfg, tmp_path):
        mock_deploy_dir.return_value = tmp_path / "nonexistent"

        cleanup_local(mock_cfg, dry_run=False)
        # Should not raise

    @patch("lablink_cli.commands.cleanup._get_deploy_dir")
    def test_delete_dir(self, mock_deploy_dir, mock_cfg, tmp_path):
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        (deploy_dir / "main.tf").write_text("test")
        mock_deploy_dir.return_value = deploy_dir

        cleanup_local(mock_cfg, dry_run=False)
        assert not deploy_dir.exists()

    @patch("lablink_cli.commands.cleanup._get_deploy_dir")
    def test_dry_run_keeps_dir(self, mock_deploy_dir, mock_cfg, tmp_path):
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        mock_deploy_dir.return_value = deploy_dir

        cleanup_local(mock_cfg, dry_run=True)
        assert deploy_dir.exists()
