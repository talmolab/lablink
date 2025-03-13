#!/bin/bash
set -e  # Exit on error

# Define Miniforge installer filename manually to avoid `uname` inconsistencies
INSTALLER="Miniforge3-Linux-x86_64.sh"

# Download the Miniforge installer script
echo "Downloading Miniforge installer..."
curl -L -O "https://github.com/conda-forge/miniforge/releases/latest/download/${INSTALLER}"

# Run the installer script non-interactively in a standard location
echo "Installing Miniforge..."
bash "${INSTALLER}" -b -p "$HOME/miniforge3"

# Ensure the installation directory is correctly exported
export PATH="$HOME/miniforge3/bin:$PATH"

# Initialize conda for the current shell
echo "Initializing Conda..."
conda init bash

# Source the profile file to apply conda init changes immediately
source "$HOME/.bashrc" || source "$HOME/.profile"

# Disable automatic activation of the base environment
echo "Disabling auto-activation of base environment..."
conda config --set auto_activate_base false

# Verify Miniforge installation
echo "Verifying Miniforge installation..."
which conda && conda --version || echo "ERROR: Miniforge is not found in PATH"
echo "PATH is set to: $PATH"
conda env list

echo "Miniforge and Mamba are set up successfully!"
exec "$@"
