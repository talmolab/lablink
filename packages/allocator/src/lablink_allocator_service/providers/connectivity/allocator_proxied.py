"""AWS connectivity: browser -> allocator nginx proxy -> client KasmVNC."""
from __future__ import annotations

from lablink_allocator_service.client_session import (
    BrowserSessionTarget,
    RotationFailed,
    prepare_browser_session,
)
from lablink_allocator_service.providers.protocol import ClientJoinMaterial
from lablink_allocator_service.get_config import get_config


def _aws_fallback_ip(hostname: str) -> str:
    """Resolve private IP by EC2 Name tag — AWS-specific fallback used by
    ``AllocatorProxiedClientConnectivity`` when no stored LAN IP is available.

    boto3 is imported lazily so that simply importing this module does not
    drag the AWS SDK into manual-mode startup.
    """
    from lablink_allocator_service.utils.aws_utils import (
        get_instance_id_by_name,
        get_instance_private_ip,
    )

    region = get_config().app.region
    instance_id = get_instance_id_by_name(hostname, region)
    if instance_id is None:
        raise RotationFailed(f"no EC2 instance found for hostname {hostname}")
    ip = get_instance_private_ip(instance_id, region)
    if ip is None:
        raise RotationFailed(
            f"no private IP for instance {instance_id} ({hostname})"
        )
    return ip


class AllocatorProxiedClientConnectivity:
    name = "allocator_proxied"

    def prepare_browser_session(self, **kwargs) -> BrowserSessionTarget:
        # Inject AWS EC2 fallback resolver so client_session.py remains
        # provider-agnostic (SR-F1).
        kwargs.setdefault("fallback_fn", _aws_fallback_ip)
        return prepare_browser_session(**kwargs)

    def make_join_material(
        self,
        *,
        allocator_url: str,
        client_image: str,
        register_token: str,
        hostname_hint: str | None = None,
    ) -> ClientJoinMaterial:
        return ClientJoinMaterial(
            register_token=register_token,
            allocator_url=allocator_url,
            connectivity=self.name,
            client_image=client_image,
        )
