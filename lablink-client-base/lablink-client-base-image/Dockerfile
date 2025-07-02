# Base image with GPU support
FROM nvidia/cuda:11.6.1-cudnn8-devel-ubuntu20.04

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
    # Base packages for compatibility with GCC-10 and other software
    gcc-10-base \
    libgcc-s1 \
    # XFCE4 desktop environment for lightweight graphical interface
    xfce4 \
    desktop-base \
    xfce4-terminal \
    xfce4-goodies \
    # Required for session and screen management
    dbus-x11 \
    xscreensaver \
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
    # For Chrome Browser
    fonts-liberation \
    libasound2 \
    wget \
    xdg-utils \
    # Allows running commands as root
    sudo && \
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
    apt install --assume-yes --fix-broken ./google-chrome-stable_current_amd64.deb

# Create the user USERNAME
RUN useradd -m -s /bin/bash ${USERNAME} && echo "${USERNAME}:password" | chpasswd && \
    echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/${USERNAME} && \
    chmod 0440 /etc/sudoers.d/${USERNAME} && \
    chown -R ${USERNAME}:${USERNAME} /home/${USERNAME}

# Add USERNAME to the chrome-remote-desktop group
RUN usermod -aG chrome-remote-desktop ${USERNAME}

# Switch to non-root user for Google Chrome Remote Desktop to work.
USER ${USERNAME}
WORKDIR /home/${USERNAME}

# Create scripts directory with miniforge, uv, and nvm installation scripts
COPY install_miniforge.sh install_uv.sh install_nvm.sh /scripts/

# Make scripts executable and run them
RUN sudo chmod +x /scripts/*.sh && \
    /scripts/install_miniforge.sh && \
    /scripts/install_uv.sh && \
    /scripts/install_nvm.sh

# Activate conda environment and install client service package
RUN /home/${USERNAME}/miniforge3/bin/conda run -n base pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple lablink-client-service

# Copy the startup script
COPY start.sh /home/${USERNAME}/start.sh
RUN sudo chmod +x /home/${USERNAME}/start.sh

# Run the startup script
CMD ["/home/client/start.sh"]
