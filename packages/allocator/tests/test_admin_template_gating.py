"""Admin template hides buttons whose capability is unsupported (D5)."""
from __future__ import annotations


def _make_fake_provider(*, can_provision: bool, can_destroy: bool, name: str):
    return type("FakeProvider", (), {
        "can_provision_hosts": can_provision,
        "can_destroy_hosts": can_destroy,
        "can_recover_hosts": can_provision,
        "name": name,
    })()


def test_aws_provider_shows_provision_destroy_hides_byo(
    client, admin_headers, monkeypatch,
):
    """AWS provider: provision + destroy + scheduled-destruction buttons
    visible; BYO Onboarding hidden."""
    from lablink_allocator_service import main
    monkeypatch.setitem(
        main.app.config, "LABLINK_PROVIDER",
        _make_fake_provider(
            can_provision=True, can_destroy=True, name="aws",
        ),
    )
    r = client.get("/admin", headers=admin_headers)
    body = r.get_data(as_text=True)
    assert "Create New VM Instance" in body
    assert "Delete VMs" in body
    assert "Schedule Destructions" in body
    assert "BYO Client Onboarding" not in body
    # View Current Instances is provider-agnostic; should always render.
    assert "View Current Instances" in body


def test_manual_provider_hides_provision_destroy_shows_byo(
    client, admin_headers, monkeypatch,
):
    """Manual provider: provision + destroy buttons hidden; BYO Onboarding
    visible."""
    from lablink_allocator_service import main
    monkeypatch.setitem(
        main.app.config, "LABLINK_PROVIDER",
        _make_fake_provider(
            can_provision=False, can_destroy=False, name="manual",
        ),
    )
    r = client.get("/admin", headers=admin_headers)
    body = r.get_data(as_text=True)
    assert "Create New VM Instance" not in body
    assert "Extract or Delete VM Data" not in body
    assert "Schedule Destructions" not in body
    assert "BYO Client Onboarding" in body
    assert "View Current Instances" in body
