"""Tests for lablink_cli.commands.setup AWS bootstrapping."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from lablink_cli.commands.setup import (
    check_credentials,
    create_dynamodb_table,
    create_route53_zone,
    create_s3_bucket,
    resolve_bucket_name,
)


# ------------------------------------------------------------------
# check_credentials
# ------------------------------------------------------------------
class TestCheckCredentials:
    def test_valid_credentials(self):
        session = MagicMock()
        sts = MagicMock()
        session.client.return_value = sts
        sts.get_caller_identity.return_value = {
            "Account": "123456789012",
            "Arn": "arn:aws:iam::123456789012:user/test",
            "UserId": "AIDA123",
        }

        result = check_credentials(session)

        assert result["account"] == "123456789012"
        assert "arn" in result
        assert "user_id" in result

    def test_invalid_credentials(self):
        session = MagicMock()
        sts = MagicMock()
        session.client.return_value = sts
        sts.get_caller_identity.side_effect = ClientError(
            {"Error": {"Code": "InvalidClientTokenId", "Message": "bad"}},
            "GetCallerIdentity",
        )

        with pytest.raises(SystemExit):
            check_credentials(session)


# ------------------------------------------------------------------
# resolve_bucket_name
# ------------------------------------------------------------------
class TestResolveBucketName:
    def test_format(self):
        assert resolve_bucket_name("123456789012") == "lablink-tf-state-123456789012"

    def test_different_accounts(self):
        assert resolve_bucket_name("111") != resolve_bucket_name("222")


# ------------------------------------------------------------------
# create_s3_bucket
# ------------------------------------------------------------------
class TestCreateS3Bucket:
    def test_bucket_already_exists(self):
        session = MagicMock()
        s3 = MagicMock()
        session.client.return_value = s3
        # head_bucket succeeds = bucket exists
        s3.head_bucket.return_value = {}

        result = create_s3_bucket(session, "my-bucket", "us-east-1")
        assert result is False
        s3.create_bucket.assert_not_called()

    def test_creates_bucket_us_east_1(self):
        session = MagicMock()
        s3 = MagicMock()
        session.client.return_value = s3
        s3.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}},
            "HeadBucket",
        )

        result = create_s3_bucket(session, "my-bucket", "us-east-1")
        assert result is True
        # us-east-1 should NOT have LocationConstraint
        s3.create_bucket.assert_called_once_with(Bucket="my-bucket")
        s3.put_bucket_versioning.assert_called_once()

    def test_creates_bucket_other_region(self):
        session = MagicMock()
        s3 = MagicMock()
        session.client.return_value = s3
        s3.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}},
            "HeadBucket",
        )

        result = create_s3_bucket(session, "my-bucket", "us-west-2")
        assert result is True
        call_kwargs = s3.create_bucket.call_args[1]
        assert call_kwargs["CreateBucketConfiguration"] == {
            "LocationConstraint": "us-west-2"
        }

    def test_bucket_already_owned(self):
        session = MagicMock()
        s3 = MagicMock()
        session.client.return_value = s3
        s3.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "403", "Message": "Forbidden"}},
            "HeadBucket",
        )
        s3.create_bucket.side_effect = ClientError(
            {"Error": {"Code": "BucketAlreadyOwnedByYou", "Message": ""}},
            "CreateBucket",
        )

        result = create_s3_bucket(session, "my-bucket", "us-east-1")
        assert result is False

    def test_bucket_taken_by_other(self):
        session = MagicMock()
        s3 = MagicMock()
        session.client.return_value = s3
        s3.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "403", "Message": "Forbidden"}},
            "HeadBucket",
        )
        s3.create_bucket.side_effect = ClientError(
            {"Error": {"Code": "BucketAlreadyExists", "Message": ""}},
            "CreateBucket",
        )

        with pytest.raises(SystemExit):
            create_s3_bucket(session, "my-bucket", "us-east-1")


# ------------------------------------------------------------------
# create_dynamodb_table
# ------------------------------------------------------------------
class TestCreateDynamoDBTable:
    def test_table_already_exists(self):
        session = MagicMock()
        dynamodb = MagicMock()
        session.client.return_value = dynamodb
        dynamodb.describe_table.return_value = {"Table": {}}

        result = create_dynamodb_table(session, "us-east-1")
        assert result is False
        dynamodb.create_table.assert_not_called()

    def test_creates_table(self):
        session = MagicMock()
        dynamodb = MagicMock()
        session.client.return_value = dynamodb

        # Simulate ResourceNotFoundException
        not_found = type(dynamodb).exceptions = MagicMock()
        not_found_exc = type("ResourceNotFoundException", (Exception,), {})
        dynamodb.exceptions.ResourceNotFoundException = not_found_exc
        dynamodb.describe_table.side_effect = not_found_exc()

        waiter = MagicMock()
        dynamodb.get_waiter.return_value = waiter

        result = create_dynamodb_table(session, "us-east-1")
        assert result is True
        dynamodb.create_table.assert_called_once()
        waiter.wait.assert_called_once()


# ------------------------------------------------------------------
# create_route53_zone
# ------------------------------------------------------------------
class TestCreateRoute53Zone:
    def test_existing_zone_found(self):
        session = MagicMock()
        route53 = MagicMock()
        session.client.return_value = route53
        route53.list_hosted_zones_by_name.return_value = {
            "HostedZones": [
                {"Name": "example.com.", "Id": "/hostedzone/Z123"}
            ]
        }

        result = create_route53_zone(session, "test.example.com")
        assert result == "Z123"

    def test_multiple_zones_returns_none(self):
        session = MagicMock()
        route53 = MagicMock()
        session.client.return_value = route53
        route53.list_hosted_zones_by_name.return_value = {
            "HostedZones": [
                {"Name": "example.com.", "Id": "/hostedzone/Z1"},
                {"Name": "example.com.", "Id": "/hostedzone/Z2"},
            ]
        }

        result = create_route53_zone(session, "test.example.com")
        assert result is None

    def test_creates_new_zone(self):
        session = MagicMock()
        route53 = MagicMock()
        session.client.return_value = route53
        route53.list_hosted_zones_by_name.return_value = {
            "HostedZones": []
        }
        route53.create_hosted_zone.return_value = {
            "HostedZone": {"Id": "/hostedzone/ZNEW"}
        }
        route53.get_hosted_zone.return_value = {
            "DelegationSet": {"NameServers": ["ns-1.example.com"]}
        }

        result = create_route53_zone(session, "test.example.com")
        assert result == "ZNEW"
        route53.create_hosted_zone.assert_called_once()
