"""GPU sampler — nvidia-smi parsing + fallback."""

from unittest.mock import MagicMock, patch

from lablink_client_service.monitoring.samplers import gpu


def test_sample_parses_nvidia_smi_output():
    fake = MagicMock(returncode=0, stdout="97, 14210\n")
    with patch(
        "lablink_client_service.monitoring.samplers.gpu.subprocess.run",
        return_value=fake,
    ):
        util, vram = gpu.sample()
    assert util == 97
    assert vram == 14210


def test_sample_handles_extra_whitespace():
    fake = MagicMock(returncode=0, stdout="  35 ,   8042  \n")
    with patch(
        "lablink_client_service.monitoring.samplers.gpu.subprocess.run",
        return_value=fake,
    ):
        util, vram = gpu.sample()
    assert util == 35
    assert vram == 8042


def test_sample_returns_zero_when_nvidia_smi_missing():
    with patch(
        "lablink_client_service.monitoring.samplers.gpu.subprocess.run",
        side_effect=FileNotFoundError(),
    ):
        assert gpu.sample() == (0, 0)


def test_sample_returns_zero_on_nonzero_exit():
    fake = MagicMock(returncode=1, stdout="")
    with patch(
        "lablink_client_service.monitoring.samplers.gpu.subprocess.run",
        return_value=fake,
    ):
        assert gpu.sample() == (0, 0)
