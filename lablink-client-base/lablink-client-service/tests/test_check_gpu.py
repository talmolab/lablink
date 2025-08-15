import subprocess
import pytest
from unittest.mock import patch, MagicMock

from lablink_client_service.check_gpu import check_gpu_health


@pytest.fixture
def mock_environment(monkeypatch):
    monkeypatch.setenv("VM_NAME", "vm-1")
    monkeypatch.setattr("lablink_client_service.check_gpu.time.sleep", lambda s: None)


@patch("lablink_client_service.check_gpu.requests.post")
@patch("lablink_client_service.check_gpu.subprocess.run")
def test_check_gpu_health_machine_with_no_gpu(mock_run, mock_post, mock_environment):
    """Test GPU health check with no GPU present"""
    mock_run.side_effect = [
        subprocess.CalledProcessError(127, "nvidia-smi", stderr="not found"),
    ]
    mock_post.return_value = MagicMock(status_code=200)

    check_gpu_health("localhost", 5000)

    assert mock_post.call_count == 1
    mock_post.assert_called_with(
        "http://localhost:5000/api/gpu_health",
        json={"hostname": "vm-1", "gpu_status": "N/A"},
    )


@patch("lablink_client_service.check_gpu.requests.post")
@patch("lablink_client_service.check_gpu.subprocess.run")
def test_check_gpu_health_machine_with_gpu(
    mock_run, mock_post, mock_environment, monkeypatch
):
    """Test GPU health check with a healthy GPU"""

    # Break the loop after the first iteration (after the post) to prevent infinte loop
    def stop_after_first_sleep(_):
        raise StopIteration

    monkeypatch.setattr(
        "lablink_client_service.check_gpu.time.sleep", stop_after_first_sleep
    )

    mock_run.side_effect = [
        subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=0, stdout="OK", stderr=""
        )
    ]
    mock_post.return_value = MagicMock(status_code=200)

    with pytest.raises(StopIteration):
        check_gpu_health("localhost", 5000)

    assert mock_post.call_count == 1
    mock_post.assert_called_with(
        "http://localhost:5000/api/gpu_health",
        json={"hostname": "vm-1", "gpu_status": "Healthy"},
    )


@patch("lablink_client_service.check_gpu.requests.post")
@patch("lablink_client_service.check_gpu.subprocess.run")
def test_check_gpu_health_machine_with_gpu_multiple(
    mock_run, mock_post, mock_environment, monkeypatch
):
    """Test multiple GPU health checks with no change in status"""

    # Break the loop after the first iteration (after the post) to prevent infinte loop
    def stop_after_first_sleep(_):
        raise StopIteration

    monkeypatch.setattr(
        "lablink_client_service.check_gpu.time.sleep", stop_after_first_sleep
    )

    mock_run.side_effect = [
        subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=0, stdout="OK", stderr=""
        ),
        subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=0, stdout="OK", stderr=""
        ),
        subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=0, stdout="OK", stderr=""
        ),
        subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=0, stdout="OK", stderr=""
        ),
        KeyboardInterrupt,
    ]
    mock_post.return_value = MagicMock(status_code=200)

    with pytest.raises(StopIteration):
        check_gpu_health(allocator_ip="localhost", allocator_port=5000, interval=10)

    assert mock_post.call_count == 1
    mock_post.assert_called_with(
        "http://localhost:5000/api/gpu_health",
        json={"hostname": "vm-1", "gpu_status": "Healthy"},
    )


@patch("lablink_client_service.check_gpu.requests.post")
@patch("lablink_client_service.check_gpu.subprocess.run")
def test_check_gpu_health_from_health_change(mock_run, mock_post, mock_environment):
    """Test multiple GPU health status changes"""
    mock_run.side_effect = [
        subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=0, stdout="OK", stderr=""
        ),
        subprocess.CalledProcessError(
            999, "nvidia-smi", stderr="Failed to initialize NVML: Unknown Error"
        ),
        subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=0, stdout="OK", stderr=""
        ),
        subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=0, stdout="OK", stderr=""
        ),
        KeyboardInterrupt,
    ]
    mock_post.return_value = MagicMock(status_code=200)

    with pytest.raises(KeyboardInterrupt):
        check_gpu_health("localhost", 5000)

    assert mock_post.call_count == 3

    first_call = mock_post.call_args_list[0]
    assert first_call.args[0] == "http://localhost:5000/api/gpu_health"
    assert first_call.kwargs["json"]["gpu_status"] == "Healthy"

    second_call = mock_post.call_args_list[1]
    assert second_call.args[0] == "http://localhost:5000/api/gpu_health"
    assert second_call.kwargs["json"]["gpu_status"] == "Unhealthy"

    third_call = mock_post.call_args_list[2]
    assert third_call.args[0] == "http://localhost:5000/api/gpu_health"
    assert third_call.kwargs["json"]["gpu_status"] == "Healthy"
