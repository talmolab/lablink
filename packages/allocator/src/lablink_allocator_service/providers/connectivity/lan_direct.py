"""LAN-direct connectivity: student browser opens the KasmVNC WS straight
to the client's LAN IP. No allocator proxy in the byte path."""
from __future__ import annotations

import secrets
import uuid

from lablink_allocator_service import client_session
from lablink_allocator_service.client_session import (
    BrowserSessionTarget,
    RotationFailed,
)
from lablink_allocator_service.providers.protocol import ClientJoinMaterial


class LANDirectClientConnectivity:
    name = "lan_direct"

    def make_join_material(
        self, *, allocator_url: str, client_image: str,
        register_token: str, hostname_hint: str | None = None,
    ) -> ClientJoinMaterial:
        return ClientJoinMaterial(
            register_token=register_token,
            allocator_url=allocator_url,
            connectivity=self.name,
            client_image=client_image,
        )

    def prepare_browser_session(
        self, *, database, hostname: str, session_id: uuid.UUID,
        browser_token: str, agent_token: str,
    ) -> BrowserSessionTarget:
        lan_ip = database.get_lan_ip(hostname)
        if not lan_ip:
            raise RotationFailed(
                f"no LAN IP recorded for manual client {hostname}"
            )
        # RFB VncAuth keys are exactly 8 bytes — KasmVNC truncates
        # anything longer to the first 8 chars. token_urlsafe(6) yields
        # an 8-char base64 string ⇒ ~48 bits of entropy, rotated per
        # session, with KasmVNC's brute_force_protection (5 fails →
        # blacklist) gating online guessing.
        password = secrets.token_urlsafe(6)
        ws_url = f"ws://{lan_ip}:6080"

        client_session._post_rotate(
            f"http://{lan_ip}:7070/api/session/start",
            {"password": password},
            bearer=agent_token,
        )

        with database._cursor as cursor:
            cursor.execute(
                f"UPDATE {database.table_name} "
                f"SET sessionid = %s, browsertoken = %s, "
                f"    browser_ws_url = %s, browser_credential = %s, "
                f"    sessionstartedat = NOW() "
                f"WHERE hostname = %s",
                (str(session_id), browser_token, ws_url, password, hostname),
            )
        return BrowserSessionTarget(ws_url=ws_url, browser_credential=password)
