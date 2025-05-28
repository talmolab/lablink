# lablink-client-base-image

## Description
This folder contains the Dockerfile (with the size of 10.1 GB) and configuration files for the base image used in the LabLink client. The image is designed to run on a Linux system with NVIDIA GPU support, specifically for use with Chrome Remote Desktop. This is the base image for the client side (VM instance) of the LabLink infrastructure. 

The base image used is [nvidia/cuda:11.6.1-cudnn8-devel-ubuntu20.04](https://hub.docker.com/layers/nvidia/cuda/11.3.1-cudnn8-runtime-ubuntu20.04/images/sha256-025a321d3131b688f4ac09d80e9af6221f2d1568b4f9ea6e45a698beebb439c0).

- The repo has CI set up in `.github/workflows` for building and pushing the image when making changes.
  - The workflow uses the linux/amd64 platform to build. 
- `./lablink-client-base/lablink-client-base-image/.devcontainer/devcontainer.json` is convenient for developing inside a container made with the DockerFile using Visual Studio Code.

## Installation

**Make sure to have Docker Daemon running first**

You can pull the image if you don't have it built locally, or need to update the latest, with

```bash
docker pull ghcr.io/talmolab/lablink-client-base-image:latest
```

## Usage
Then, to run the image with GPU interactively with the desired allocator host, you can use the following command:
```bash
docker run -e ALLOCATOR_HOST=<allocator_host> --gpus all -it ghcr.io/talmolab/lablink-client-base-image:latest
```

In the container, you can run GPU commands like
```bash
nvidia-smi
```

**Notes:**

- `-it` ensures that you get an interactive terminal. The `i` stands for interactive, and `t` allocates a pseudo-TTY, which is what allows you to interact with the bash shell inside the container.
- The `-v` or `--volume` option mounts the specified directory with the same level of access as the directory has on the host.
- The `--rm` flag in a docker run command automatically removes the container when it stops. This is useful for running temporary or one-time containers without cluttering your Docker environment with stopped containers.
- The `--gpus all` flag is used to enable GPU support in the container, allowing you to run GPU-accelerated applications.
- The `-e` flag is used to set environment variables in the container. In this case, it sets the `ALLOCATOR_HOST` variable to the specified host address.

## Build
To build and push via automated CI, just push changes to a branch.

- Pushes to `main` result in an image with the tag `latest`.
- Pushes to other branches have tags with `-test` appended.
- See `.github/workflows` for testing and production workflows.

To test `test` images locally use after pushing the `test` images via CI:

```bash
docker pull ghcr.io/talmolab/lablink-client-base-image:linux-amd64-test
```

then

```bash
docker run --gpus all -e ALLOCATOR_HOST=<allocator-host> -it ghcr.io/talmolab/lablink-client-base-image:linux-amd64-test
```

To build locally for testing you can use the command:
```bash
docker build --no-cache -t client-base-crd ./lablink-client-base/lablink-client-base-image
docker run --gpus all -e ALLOCATOR_HOST=<allocator-host> -it --rm --name client-base-crd client-base-crd
```

> Note: The local machine must have the NVIDIA Container Toolkit installed to use the `--gpus all` flag.