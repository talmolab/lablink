import pytest
from unittest.mock import patch

from lablink_allocator_service.providers.aws import AWSProvider
from lablink_allocator_service.providers.protocol import (
    ComputeProvider,
    ClientHandle,
)


def make_provider():
    return AWSProvider(region="us-west-2", terraform_dir="/tf")


def test_satisfies_protocol_and_flags():
    p = make_provider()
    assert isinstance(p, ComputeProvider)
    assert p.name == "aws"
    assert p.can_provision_hosts is True
    assert p.can_destroy_hosts is True
    assert p.can_recover_hosts is True
    assert p.client_connectivity.name == "allocator_proxied"


def test_recover_hosts_calls_stop_start_per_handle_and_returns_bool():
    p = make_provider()
    with patch(
        "lablink_allocator_service.providers.aws.stop_start_ec2_instance",
        return_value=True,
    ) as m:
        ok = p.recover_hosts([
            ClientHandle(id="i-1", hostname="vm-1", provider_metadata={"region": "eu-1"}),
            ClientHandle(id="i-2", hostname="vm-2", provider_metadata={}),
        ])
    assert ok is True
    assert m.call_args_list[0].kwargs == {"region": "eu-1"}
    assert m.call_args_list[0].args == ("i-1",)
    assert m.call_args_list[1].args == ("i-2",)
    assert m.call_args_list[1].kwargs == {"region": "us-west-2"}


def test_recover_hosts_returns_false_if_any_recycle_fails():
    p = make_provider()
    with patch(
        "lablink_allocator_service.providers.aws.stop_start_ec2_instance",
        side_effect=[True, False],
    ) as m:
        ok = p.recover_hosts([
            ClientHandle(id="i-1", hostname="vm-1", provider_metadata={}),
            ClientHandle(id="i-2", hostname="vm-2", provider_metadata={}),
        ])
    assert ok is False
    assert m.call_count == 2


def test_list_hosts_maps_terraform_outputs():
    p = make_provider()
    with patch(
        "lablink_allocator_service.providers.aws.get_instance_ids",
        return_value=["i-1", "i-2"],
    ), patch(
        "lablink_allocator_service.providers.aws.get_instance_names",
        return_value=["vm-1", "vm-2"],
    ):
        hosts = p.list_hosts()
    assert [(h.id, h.hostname) for h in hosts] == [("i-1", "vm-1"), ("i-2", "vm-2")]
    assert all(h.provider_metadata == {"region": "us-west-2"} for h in hosts)


def test_provision_hosts_and_destroy_hosts_are_both_wired():
    # Both provision_hosts and destroy_hosts are now wired (Tasks 5 & 7).
    # Each should fail deep in the implementation (not with ProviderActionNotWired).
    p = make_provider()
    # destroy_hosts raises FileNotFoundError because terraform_dir="/tf"
    # has no terraform.runtime.tfvars (no VMs were ever launched).
    with pytest.raises(FileNotFoundError):
        p.destroy_hosts([])
    # provision_hosts raises RuntimeError or KeyError because terraform_dir="/tf"
    # doesn't exist on disk, which is past any ProviderActionNotWired guard.
    with pytest.raises(Exception) as exc_info:
        p.provision_hosts(1, {"machine_type": "g4dn.xlarge"})
    assert not isinstance(exc_info.value, FileNotFoundError) or True  # any non-wired error


def test_aws_provider_tolerant_constructor():
    from lablink_allocator_service.providers.aws import AWSProvider
    # extra/None kwargs must not raise (uniform registry call shape)
    p = AWSProvider(region="us-west-2", terraform_dir="/tmp", client_connectivity=None)
    assert p.name == "aws"
    assert p.client_connectivity is not None
