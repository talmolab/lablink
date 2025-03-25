#!/bin/bash

# Install nvm
echo "Installing nvm..."
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash

echo "nvm installed successfully"

# Check nvm version
echo "Checking nvm version..."
echo "The directory for NVM: $NVM_DIR"
echo "The version of NVM: $(nvm --version)"