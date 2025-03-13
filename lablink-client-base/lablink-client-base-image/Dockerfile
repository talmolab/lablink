# Base image with GPU support
FROM nvidia/cuda:11.6.1-cudnn8-devel-ubuntu20.04

# Set non-interactive mode
ENV DEBIAN_FRONTEND=noninteractive

# Set user
ENV USER=root

# Set NVIDIA driver capabilities
ENV NVIDIA_DRIVER_CAPABILITIES=all

# Install dependencies
# opencv requires opengl https://github.com/conda-forge/opencv-feedstock/issues/401
# Default python3 is 3.8 in ubuntu 20.04 https://wiki.ubuntu.com/FocalFossa/ReleaseNotes#Python3_by_default
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libfontconfig1 \
    libgssapi-krb5-2 \
    libdbus-1-3 \
    libx11-xcb1 \
    libxkbcommon-x11-0 \
    curl \
    # Base packages for compatibility with GCC-10 and other software
    gcc-10-base \
    libgcc-s1 \
    # XFCE4 desktop environment for lightweight graphical interface
    xfce4 \
    desktop-base \
    # Required for session and screen management
    dbus-x11 \
    xscreensaver \
    xbase-clients \
    xvfb \
    # Miscellaneous dependencies
    # Provides process management utilities
    psmisc \
    # Dummy X server for headless environments
    xserver-xorg-video-dummy \
    # Supports session management and terminal multiplexers
    libutempter0 \  
    # Enables secure communication and package verification
    gnupg2 \             
    # Allows running commands as root
    sudo && \               
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Copy install script into container
COPY install_miniforge.sh /scripts/install_miniforge.sh

# Make script executable
RUN chmod +x /scripts/install_miniforge.sh

# Run script during build to install Miniforge
RUN bash /scripts/install_miniforge.sh

# Copy install script into container
COPY install_uv.sh /scripts/install_uv.sh

# Make script executable
RUN chmod +x /scripts/install_uv.sh

# Run script during build to install Miniforge
RUN bash /scripts/install_uv.sh