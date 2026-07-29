"""Both client Dockerfiles must install frpc.

The prod Dockerfile installs lablink-client-service from PyPI while
Dockerfile.dev COPYs local source, so only the dev image can run
unreleased client code -- which means a relay change verified against
the dev image alone proves nothing about prod, and vice versa. This
parity gap has already been missed once for the client image
(mesh-overlay's tailscale install) and once for the allocator's own
Dockerfile.dev during relay Plan 1, so it gets a test.
"""

from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]
DOCKERFILES = [PKG / "Dockerfile", PKG / "Dockerfile.dev"]


@pytest.mark.parametrize("path", DOCKERFILES, ids=lambda p: p.name)
def test_dockerfile_installs_frpc(path):
    text = path.read_text()
    assert "frp_${FRP_VERSION}_linux_amd64" in text, (
        f"{path.name} does not download the frp release tarball"
    )
    assert "/usr/local/bin/frpc" in text, (
        f"{path.name} does not install frpc to /usr/local/bin"
    )


def test_both_dockerfiles_pin_the_same_frp_version():
    """A version skew between the two images is a silent
    behaviour difference, so pin them together."""
    versions = set()
    for path in DOCKERFILES:
        for line in path.read_text().splitlines():
            if line.startswith("ARG FRP_VERSION="):
                versions.add(line.split("=", 1)[1].strip())
    assert len(versions) == 1, f"FRP_VERSION differs across images: {versions}"
