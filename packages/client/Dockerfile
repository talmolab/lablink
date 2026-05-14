# Base image with GPU support
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04

# Run as a non-root user; KasmVNC and the agent both run as this user.
ARG USERNAME="client"

# Set non-interactive mode
ENV DEBIAN_FRONTEND=noninteractive

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
    libgssapi-krb5-2 \
    libx11-xcb1 \
    ca-certificates \
    curl \
    wget \
    # For media playback
    vlc \
    # Audio support for desktop apps (VLC, terminal bells, notifications)
    libasound2 \
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
    fonts-liberation \
    fontconfig \
    # Desktop file-to-application routing (xdg-open, xdg-mime)
    xdg-utils \
    # Required for session and screen management
    dbus-x11 \
    xscreensaver \
    xbase-clients \
    xvfb \
    # xterm is pinned as a permanent X client by start.sh so that the
    # "last X client exited" path never fires, which otherwise tears
    # Xvnc down when xfce4 components race on dbus name ownership.
    xterm \
    # Provides process management utilities
    psmisc \
    # Dummy X server for headless environments
    xserver-xorg-video-dummy \
    # Supports session management and terminal multiplexers
    libutempter0 \
    # Enables secure communication and package verification
    gnupg2 \
    # Allows running commands as root
    sudo \
    # For cloning repositories and managing git
    libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 \
    libxcb-keysyms1 libxcb-render-util0 libxrender1 libxrandr2 \
    libxfixes3 libxi6 libxtst6 libxcomposite1 libxdamage1 \
    libdbus-1-3 libfontconfig1 libfreetype6 libgl1 \
    # Runtime dep for Google Chrome (rasterization backend)
    libvulkan1 \
    git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*


# KasmVNC standalone VNC server. Pin to a current stable release;
# bump alongside client image releases.
ARG KASMVNC_VERSION=1.4.0
RUN curl -L -o /tmp/kasmvncserver.deb \
      "https://github.com/kasmtech/KasmVNC/releases/download/v${KASMVNC_VERSION}/kasmvncserver_jammy_${KASMVNC_VERSION}_amd64.deb" && \
    apt-get update && \
    apt-get install -y --no-install-recommends /tmp/kasmvncserver.deb && \
    rm /tmp/kasmvncserver.deb && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

EXPOSE 6080 7070

# lightdm conflicts with headless VNC; disable it so KasmVNC can own the session.
RUN systemctl disable lightdm.service || true

# Google Chrome browser. Installed inside the remote desktop so students can
# open tutorial URLs, Jupyter, etc. from within their VNC session. (This is
# the browser, distinct from Chrome Remote Desktop which this PR removed.)
RUN curl -L -o /tmp/google-chrome-stable_current_amd64.deb \
        https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get install --assume-yes --fix-broken /tmp/google-chrome-stable_current_amd64.deb && \
    rm /tmp/google-chrome-stable_current_amd64.deb && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Wrap google-chrome (and the google-chrome-stable alias the .deb installs)
# with flags that make it work inside a container: no sandbox (containers
# already isolate; the default sandbox needs user namespaces we don't grant),
# no GPU (no graphics device on the EC2 host), and no /dev/shm reliance
# (Docker's default 64 MiB tmpfs is too small for Chrome's IPC).
RUN for bin in google-chrome google-chrome-stable; do \
        rm -f /usr/bin/$bin && \
        printf '%s\n' \
            '#!/bin/bash' \
            'exec /opt/google/chrome/google-chrome --no-sandbox --disable-gpu --disable-software-rasterizer --disable-dev-shm-usage "$@"' \
            > /usr/bin/$bin && \
        chmod +x /usr/bin/$bin; \
    done

# Create the user USERNAME
RUN useradd -m -s /bin/bash ${USERNAME} && echo "${USERNAME}:password" | chpasswd && \
    echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/${USERNAME} && \
    chmod 0440 /etc/sudoers.d/${USERNAME} && \
    chown -R ${USERNAME}:${USERNAME} /home/${USERNAME}

# Switch to non-root user; KasmVNC and the agent both run as this user.
# Align USER/LOGNAME/HOME with the runtime uid. Docker's USER directive
# only changes the effective uid; $USER / $LOGNAME / $HOME are left
# untouched and would otherwise inherit stale values from the build
# stage. Keeping them wrong pollutes every tool that reads them, and
# anything that looks at $HOME or $USER sees the wrong value and makes
# debugging harder.
USER ${USERNAME}
ENV USER=${USERNAME} \
    LOGNAME=${USERNAME} \
    HOME=/home/${USERNAME}
WORKDIR /home/${USERNAME}

# Create scripts directory with miniforge, uv, and nvm installation scripts
COPY install_miniforge.sh install_nvm.sh /scripts/

# Make scripts executable and run them
RUN sudo chmod +x /scripts/*.sh && \
    /scripts/install_miniforge.sh && \
    /scripts/install_nvm.sh

# Build argument for package version
ARG PACKAGE_VERSION=0.0.8a0

# Ensure target directory exists before COPY (--chown may not apply to auto-created parents)
RUN mkdir -p /home/client/.local/bin

# Install uv under client user (not root) to avoid permission issues
COPY --chown=client:client --from=ghcr.io/astral-sh/uv:0.10 /uv /uvx /home/client/.local/bin/

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
    uv add lablink-client-service==${PACKAGE_VERSION} --no-cache

# Ensure PATH is available in interactive sessions (KasmVNC, SSH, etc.)
# Docker ENV only affects processes started by Docker, not new login shells
RUN echo 'export PATH="/home/client/.local/bin:$PATH"' >> /home/client/.bashrc && \
    echo 'export PATH="/home/client/.local/bin:$PATH"' >> /home/client/.profile

# Copy the startup script
COPY start.sh /home/${USERNAME}/start.sh
RUN sudo chmod +x /home/${USERNAME}/start.sh

# Run the startup script
CMD ["/home/client/start.sh"]
