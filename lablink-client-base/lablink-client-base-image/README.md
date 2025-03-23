# sleap-chrome-remote-desktop

## Description
This folder of the repo contains a DockerFile for a lightweight container (~9.75 GB) with the PyPI installation of SLEAP and all of its dependencies and a Chrome Remote Desktop server.

The base image used is [nvidia/cuda:11.6.1-cudnn8-devel-ubuntu20.04](https://hub.docker.com/layers/nvidia/cuda/11.3.1-cudnn8-runtime-ubuntu20.04/images/sha256-025a321d3131b688f4ac09d80e9af6221f2d1568b4f9ea6e45a698beebb439c0).

- The repo has CI set up in `.github/workflows` for building and pushing the image when making changes.
  - The workflow uses the linux/amd64 platform to build. 
- `./sleap_chrome_remote_desktop/.devcontainer/devcontainer.json` is convenient for developing inside a container made with the DockerFile using Visual Studio Code.

## Installation

**Make sure to have Docker Daemon running first**


You can pull the image if you don't have it built locally, or need to update the latest, with

```bash
docker pull ghcr.io/talmolab/lablink-client-base-image:linux-amd64
```

## Usage