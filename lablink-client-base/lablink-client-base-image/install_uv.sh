#!/bin/bash

# Download UV installer
echo "Downloading UV installer..."
curl -LsSf https://astral.sh/uv/install.sh | bash

# Ensure UV is in the PATH
export PATH="$HOME/.local/bin:$PATH"

# Verify UV installation
which uv && uv --version || echo "ERROR: UV is not found in PATH"
echo "PATH is set to: $PATH"

# Self update
echo "Self updating UV..."
uv self update