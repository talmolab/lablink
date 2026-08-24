#!/bin/bash
set -euo pipefail

# Install nvm
echo "Installing nvm..."
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash

# nvm is a shell function, not a binary: it only exists after sourcing
# nvm.sh, which the installer wires into .bashrc for interactive shells.
# Source it here so the version check below verifies the install for real.
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

echo "The directory for NVM: $NVM_DIR"
echo "The version of NVM: $(nvm --version)"
echo "nvm installed successfully"
