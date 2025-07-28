#!/bin/bash
set -euo pipefail

echo ">> Configuration:"
echo "  - Allocator IP: ${allocator_ip}"
echo "  - Resource Suffix: ${resource_suffix}"
echo "  - Count Index: ${count_index}"
echo "  - Subject Software: ${subject_software}"
echo "  - Image Name: ${image_name}"
echo "  - Machine Type GPU Support: ${gpu_support}"
echo "  - GitHub Repository: ${repository}"

echo ">> Checking GPU Support…"


if command -v nvidia-smi >/dev/null 2>&1; then
    AMI_GPU_SUPPORT=true
    echo ">> AMI GPU support detected. Checking NVIDIA drivers…"
else
    AMI_GPU_SUPPORT=false
    echo ">> AMI GPU support not detected."
fi

if [ "$AMI_GPU_SUPPORT" = ${gpu_support} ] && [ ${gpu_support} = true ]; then
    HAS_GPU=true
    echo ">> GPU support matches configuration."
else
    HAS_GPU=false
    echo ">> GPU support mismatch! Expected: ${gpu_support}, Detected: $AMI_GPU_SUPPORT\nWarning: Using CPU to launch containers."
fi

if [ "$HAS_GPU" = true ]; then
    echo ">> Switching Docker to cgroupfs for NVIDIA runtime…"
    cat >/etc/docker/daemon.json <<'JSON'
{
    "default-runtime": "nvidia",
    "runtimes": {
        "nvidia": {
        "path": "nvidia-container-runtime",
        "runtimeArgs": []
        }
    },
    "exec-opts": ["native.cgroupdriver=cgroupfs"]
}
JSON

    systemctl restart docker

    until docker info >/dev/null 2>&1; do
        sleep 1
    done

    echo ">> Docker restarted with cgroupfs."

    nvidia-smi -pm 1 || true
else
    echo ">> No GPU support detected. Continuing without GPU features."
fi

echo ">> Pulling application image ${image_name}…"
if ! docker pull "${image_name}"; then
    echo "Docker image pull failed!" >&2
    exit 1
fi
echo ">> Image pulled."

DOCKER_GPU_ARGS=""
if [ "$HAS_GPU" = true ]; then
    DOCKER_GPU_ARGS="--runtime=nvidia --gpus all"
fi

echo ">> Starting container..."
if [ -z "${repository:-}" ]; then
    echo ">> No repo specified; starting container without cloning."
    docker run -dit $DOCKER_GPU_ARGS \
        -e ALLOCATOR_HOST="${allocator_ip}" \
        -e VM_NAME="lablink-vm-${resource_suffix}-${count_index}" \
        -e SUBJECT_SOFTWARE="${subject_software}" \
        "${image_name}"
else
    echo ">> Cloning repo and starting container."
    docker run -dit $DOCKER_GPU_ARGS \
        -e ALLOCATOR_HOST="${allocator_ip}" \
        -e TUTORIAL_REPO_TO_CLONE="${repository}" \
        -e VM_NAME="lablink-vm-${resource_suffix}-${count_index}" \
        -e SUBJECT_SOFTWARE="${subject_software}" \
        "${image_name}"
fi

echo ">> Container launched."
