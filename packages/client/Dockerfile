# Base image with GPU support
FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04

# https://askubuntu.com/questions/1402167/must-specify-the-user-name-option-when-running-as-root-chrome-remote-desktop
# Must be a non-root user to run Chrome Remote Desktop
ARG USERNAME="client"

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
    libgl1-mesa-glx \
    libglapi-mesa \
    libegl-mesa0 \
    libegl1 \
    libopengl0 \
    libglib2.0-0 \
    libfontconfig1 \
    libgssapi-krb5-2 \
    libdbus-1-3 \
    libx11-xcb1 \
    libxkbcommon-x11-0 \
    curl \
    # For media playback
    vlc \
    # For productivity and general use
    zip \
    unzip \
    # Base packages for compatibility with GCC-10 and other software
    gcc-10-base \
    libgcc-s1 \
    # XFCE4 desktop environment for lightweight graphical interface
    xfce4 \
    desktop-base \
    xfce4-terminal \
    xfce4-goodies \
    elementary-xfce-icon-theme \
    fonts-dejavu \
    fontconfig \
    # Required for session and screen management
    dbus-x11 \
    xscreensaver \
    xbase-clients \
    xvfb \
    # Provides process management utilities
    psmisc \
    # Dummy X server for headless environments
    xserver-xorg-video-dummy \
    # Supports session management and terminal multiplexers
    libutempter0 \  
    # Enables secure communication and package verification
    gnupg2 \
    # For Chrome Browser
    fonts-liberation \
    libasound2 \
    wget \
    xdg-utils \
    libvulkan1 \
    # Allows running commands as root
    sudo \
    # For cloning repositories and managing git
    libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 \
    libxcb-keysyms1 libxcb-render-util0 libxrender1 libxrandr2 \
    libxfixes3 libxi6 libxtst6 libxcomposite1 libxdamage1 \
    libdbus-1-3 libfontconfig1 libfreetype6 libgl1 \
    git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*


# Install Chrome Remote Desktop
RUN  curl https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /etc/apt/trusted.gpg.d/chrome-remote-desktop.gpg && \
    # Add the Chrome Remote Desktop repository
    echo "deb [arch=amd64] https://dl.google.com/linux/chrome-remote-desktop/deb stable main" > /etc/apt/sources.list.d/chrome-remote-desktop.list && \
    # Update package lists and install Chrome Remote Desktop
    apt-get update && apt-get install --assume-yes chrome-remote-desktop && \
    # Clean up to reduce image size
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Configure Chrome Remote Desktop to use Gnome by default
RUN echo "exec /etc/X11/Xsession /usr/bin/xfce4-session" > /etc/chrome-remote-desktop-session


# Because there is no display connected to your instance, disable the display manager service on your instance
RUN systemctl disable lightdm.service

# Install Chrome browser
RUN curl -L -o google-chrome-stable_current_amd64.deb \
    https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt install --assume-yes --fix-broken ./google-chrome-stable_current_amd64.deb && \
    rm google-chrome-stable_current_amd64.deb

# Configure Google Chrome to run without sandboxing
# This is necessary for Chrome Remote Desktop to work properly in a container environment.
# Create a directory for wrapper scripts
RUN rm -f /usr/bin/google-chrome && \
    echo '#!/bin/bash' > /usr/bin/google-chrome && \
    echo 'exec /opt/google/chrome/google-chrome --no-sandbox --disable-gpu --disable-software-rasterizer --disable-dev-shm-usage "$@"' >> /usr/bin/google-chrome && \
    chmod +x /usr/bin/google-chrome

# Do the same for the stable version of Google Chrome
RUN rm -f /usr/bin/google-chrome-stable && \
    echo '#!/bin/bash' > /usr/bin/google-chrome-stable && \
    echo 'exec /opt/google/chrome/google-chrome --no-sandbox --disable-gpu --disable-software-rasterizer --disable-dev-shm-usage "$@"' >> /usr/bin/google-chrome-stable && \
    chmod +x /usr/bin/google-chrome-stable

# Create the user USERNAME
RUN useradd -m -s /bin/bash ${USERNAME} && echo "${USERNAME}:password" | chpasswd && \
    echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/${USERNAME} && \
    chmod 0440 /etc/sudoers.d/${USERNAME} && \
    chown -R ${USERNAME}:${USERNAME} /home/${USERNAME}

# Add USERNAME to the chrome-remote-desktop group
RUN usermod -aG chrome-remote-desktop ${USERNAME}

# Ensure Chrome directories are accessible to the client user
RUN mkdir -p /home/${USERNAME}/.config/google-chrome && \
    chown -R ${USERNAME}:${USERNAME} /home/${USERNAME}/.config

# Switch to non-root user for Google Chrome Remote Desktop to work.
USER ${USERNAME}
WORKDIR /home/${USERNAME}

# Create scripts directory with miniforge, uv, and nvm installation scripts
COPY install_miniforge.sh install_nvm.sh /scripts/

# Make scripts executable and run them
RUN sudo chmod +x /scripts/*.sh && \
    /scripts/install_miniforge.sh && \
    /scripts/install_nvm.sh

# Build argument for package version
ARG PACKAGE_VERSION=0.0.8a0

# Create uv directories with correct ownership before any uv operations
# This prevents permission errors when uv tries to create these directories
RUN mkdir -p /home/client/.local/bin \
    /home/client/.local/share/uv/tools \
    /home/client/.local/share/uv/python \
    /home/client/.cache/uv

# Download the latest uv release from GitHub
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set UV environment variables to use user-owned directories
ENV UV_CACHE_DIR=/home/client/.cache/uv
ENV UV_TOOL_DIR=/home/client/.local/share/uv/tools
ENV UV_TOOL_BIN_DIR=/home/client/.local/bin
ENV UV_PYTHON_INSTALL_DIR=/home/client/.local/share/uv/python

# Add uv tool bin directory to PATH for tools installed via 'uv tool install'
ENV PATH="/home/client/.local/bin:${PATH}"

# Install client service package from PyPI in a virtual environment
RUN uv init --python 3.11 --no-readme \
    && uv venv /home/${USERNAME}/.venv && \
    uv add lablink-client-service==${PACKAGE_VERSION} --no-cache && \
    uv sync && \
    # Ensure correct ownership of all uv directories for runtime uv tool install
    # (some subdirectories may be created with unexpected permissions during build)
    chown -R client:client /home/client/.local/share/uv /home/client/.cache/uv

# Ensure PATH is available in interactive sessions (CRD, SSH, etc.)
# Docker ENV only affects processes started by Docker, not new login shells
RUN echo 'export PATH="/home/client/.local/bin:$PATH"' >> /home/client/.bashrc && \
    echo 'export PATH="/home/client/.local/bin:$PATH"' >> /home/client/.profile

# Copy the startup script
COPY start.sh /home/${USERNAME}/start.sh
RUN sudo chmod +x /home/${USERNAME}/start.sh

# Run the startup script
CMD ["/home/client/start.sh"]
