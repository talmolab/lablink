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
Then, to run the image with GPU interactively, 
```bash
docker run --gpus all -it ghcr.io/talmolab/lablink-client-base-image:latest
```

In the container, you can run GPU commands like
```bash
nvidia-smi
```

**Notes:**

- `-it` ensures that you get an interactive terminal. The `i` stands for interactive, and `t` allocates a pseudo-TTY, which is what allows you to interact with the bash shell inside the container.
- The `-v` or `--volume` option mounts the specified directory with the same level of access as the directory has on the host.
- The `--rm` flag in a docker run command automatically removes the container when it stops. This is useful for running temporary or one-time containers without cluttering your Docker environment with stopped containers.


## Connecting to Chrome Remote Desktop

This guide explains how to connect to the Chrome Remote Desktop server running in the container to access the desktop environment.

### Prerequisites
1. **Google Account**: You need a Google account to use Chrome Remote Desktop.
2. **Chrome Browser**: You need to have the Chrome browser installed on your local machine.
3. **Docker Setup**:
   - Ensure Docker is installed and running on your system.

### Steps to Connect

### 1. Start the Docker Container

Start the Docker container with the Chrome Remote Desktop server running in it.

```bash
docker run --rm -it --gpus=all <your-container-name>
```

### 2. Connect to the Chrome Remote Desktop

1. On your local machine, go to [https://remotedesktop.google.com/access](https://remotedesktop.google.com/access) in your Chrome browser.

2. Sign in with your Google account.

3. Then, click "Set up via SSH" on the left and follow the provided steps.
- This will provide the command in this form: 
  ```bash
  DISPLAY= /opt/google/chrome-remote-desktop/start-host \
    --code="4/xxxxxxxxxxxxxxxxxxxxxxxx" \
    --redirect-url="https://remotedesktop.google.com/_/oauthredirect" \
    --name=$(hostname)
  ```

1. Run the provided command in your remote machine's terminal with Docker container running. Make sure to refresh the website. 

2. When prompted, enter 6-digit PIN. This number will be used for additional authorization when you connect later.

### 3. Run Chrome Remote Desktop

1. Go to [https://remotedesktop.google.com/access](https://remotedesktop.google.com/access) in your Chrome browser.

2. Sign in with your Google account.

3. Then, click "Remote Access" to check the status of your remote desktop (make sure to refresh the page).

4. If you see the status as "Online", click on the remote desktop to connect and enter the 6-digit PIN you set earlier.

### 4. Access the GUI

Once connected to the remote machine, open a terminal and type the Nvidia commands like `nvidia-smi`. The GUI should be displayed in your chrome remote desktop display environment on your local machine.

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
docker run --gpus all -it ghcr.io/talmolab/lablink-client-base-image:linux-amd64-test
```

To build locally for testing you can use the command:
```bash
docker build --no-cache -t sleap-crd ./lablink-client-base/lablink-client-base-image
docker run --gpus all -it --rm --name sleap-crd sleap-crd
```