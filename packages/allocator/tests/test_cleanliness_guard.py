"""Spec §7 invariant: the allocator core must not branch on connectivity
or provider *type*. Fails on a type discriminator in the core modules."""
import re
from pathlib import Path

CORE = [
    "src/lablink_allocator_service/routes/desktop.py",
    "src/lablink_allocator_service/routes/internal_proxy_auth.py",
    "src/lablink_allocator_service/main.py",
]
# type discriminators (NOT data-attribute / capability-flag conditionals)
BANNED = [
    re.compile(r'\bconnectivity\s*==\s*["\']'),
    re.compile(r'\bprovider\s*==\s*["\']'),
    re.compile(r'isinstance\([^)]*(Provider|Connectivity)\)'),
]


def test_core_has_no_connectivity_or_provider_type_branch():
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for rel in CORE:
        text = (root / rel).read_text()
        for pat in BANNED:
            for m in pat.finditer(text):
                offenders.append(f"{rel}: {m.group(0)}")
    assert not offenders, "connectivity/provider type-branch in core: " + "; ".join(offenders)
