import uuid
import pytest
from importlib.metadata import entry_points as _eps
from unittest.mock import patch

from lablink_allocator_service.providers.registry import get_provider, DEFAULT_PROVIDER
from lablink_allocator_service.providers.aws import AWSProvider
from lablink_allocator_service.providers.protocol import ComputeProvider, BrowserSessionTarget


def test_default_is_aws():
    assert DEFAULT_PROVIDER == "aws"


def test_get_provider_aws_returns_constructed_instance():
    p = get_provider("aws", region="us-west-2", terraform_dir="/tf")
    assert isinstance(p, AWSProvider)
    assert isinstance(p, ComputeProvider)


def test_get_provider_default_when_none():
    p = get_provider(None, region="us-west-2", terraform_dir="/tf")
    assert isinstance(p, AWSProvider)


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="unknown provider 'gcp'"):
        get_provider("gcp", region="us-west-2", terraform_dir="/tf")


def test_aws_entry_point_is_registered():
    names = {ep.name for ep in _eps(group="lablink.providers")}
    assert "aws" in names


def test_provider_connectivity_round_trips_kwargs():
    p = get_provider("aws", region="us-west-2", terraform_dir="/tf")
    sid = uuid.uuid4()
    sentinel = BrowserSessionTarget(upstream="10.0.0.5:6080")
    with patch(
        "lablink_allocator_service.providers.connectivity.allocator_proxied."
        "prepare_browser_session",
        return_value=sentinel,
    ) as m:
        out = p.client_connectivity.prepare_browser_session(
            database="DB", hostname="vm-1", session_id=sid,
            browser_token="t", api_token="a",
        )
    assert out is sentinel
    assert m.call_args.kwargs["hostname"] == "vm-1"
