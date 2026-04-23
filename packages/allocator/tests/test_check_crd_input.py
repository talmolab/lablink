"""Unit tests for check_crd_input — the input-validation gate that
prevents command injection via the /api/request_vm endpoint.

Regression test for the pre-fix vulnerability where the only check was
`"--code" in crd_command`, allowing arbitrary shell metacharacters to
reach the client VM's `subprocess.run(..., shell=True)` sink.
"""

import pytest


@pytest.fixture
def check_crd_input(monkeypatch, omega_config):
    """Import check_crd_input with the test config already patched in.

    Matches the conftest pattern of deferring `main` import so its
    module-level config validation sees the test OmegaConf.
    """
    monkeypatch.setattr(
        "lablink_allocator_service.get_config.get_config",
        lambda: omega_config,
        raising=True,
    )
    from lablink_allocator_service import main

    return main.check_crd_input


@pytest.mark.parametrize(
    "crd_command",
    [
        "DISPLAY= /opt/google/chrome-remote-desktop/start-host --code=4/abc123 --name=vm-1",
        "/opt/google/chrome-remote-desktop/start-host --code=test_code",
        "--code=4/0Aerz0j_I9c7gCgYIARAA-GBASNwF",
        "--code=a-b_c/d --name=vm",
        "--code 4/abc123",
        # Google's copy-pasteable command uses double-quoted values.
        'DISPLAY= /opt/google/chrome-remote-desktop/start-host '
        '--code="4/0Aci98E9mrctADxPTQEFDU-qmLdO3dCIwNP1YbdY9utWTgxXEpCZPezaNHr1OxHziFLmaTg" '
        '--redirect-url="https://remotedesktop.google.com/_/oauthredirect" '
        "--name=$(hostname)",
        # Single-quoted is also acceptable (equivalent paste style).
        "--code='4/abc123'",
    ],
)
def test_accepts_legitimate_commands(check_crd_input, crd_command):
    assert check_crd_input(crd_command) is True


@pytest.mark.parametrize(
    "crd_command",
    [
        # Shell metacharacters inside the --code token: these are the
        # classic injection payloads; they ride through argparse on the
        # client because there is no whitespace separating them.
        "--code=x;id",
        "--code=x|sh",
        "--code=$(id)",
        "--code=`whoami`",
        "--code=x${IFS}y",
        "--code=x&&id",
        "--code=x=y",
        # Metacharacters smuggled inside matched quotes — quote-strip
        # exposes the payload, allowlist catches it.
        "--code='x;id'",
        '--code="$(id)"',
        "--code='`whoami`'",
        # Unmatched / embedded quotes — allowlist rejects.
        "--code='abc",
        "--code=a'b",
        # Empty or quoted-empty.
        "--code=",
        "--code=''",
    ],
)
def test_rejects_metacharacter_payloads(check_crd_input, crd_command):
    assert check_crd_input(crd_command) is False


@pytest.mark.parametrize(
    "crd_command",
    [
        # Extra whitespace-separated tokens after --code do NOT cause
        # injection — the client's argparse sees them as unrelated args
        # and ignores them (parse_known_args). The extracted code value
        # is only the part before the space, and it satisfies the
        # allowlist here. We accept these rather than being overly
        # strict about surrounding tokens.
        "--code=abc extra_token",
        "--code=abc\nextra_token",
    ],
)
def test_accepts_when_trailing_tokens_are_harmless(check_crd_input, crd_command):
    assert check_crd_input(crd_command) is True


def test_rejects_missing_code(check_crd_input):
    assert check_crd_input("DISPLAY= /opt/google/chrome-remote-desktop/start-host") is False


def test_rejects_duplicate_code(check_crd_input):
    assert check_crd_input("--code=abc --code=def") is False


def test_rejects_none(check_crd_input):
    assert check_crd_input(None) is False
