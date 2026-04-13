#!/bin/bash
#
# Install Python dependencies on HPC for connectivity analysis
#

set -e

echo "Installing Python dependencies on HPC..."
echo "================================================================"

# Create virtual environment if it doesn't exist
if [ ! -d "$HOME/venv/connectivity" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$HOME/venv/connectivity"
fi

# Activate environment
source "$HOME/venv/connectivity/bin/activate"

# Upgrade pip
pip install --upgrade pip

# Install dependencies
echo "Installing packages..."
pip install nibabel nilearn pandas numpy scipy statsmodels matplotlib joblib

echo ""
echo "================================================================"
echo "Installation complete!"
echo "================================================================"
echo ""
echo "Installed packages:"
pip list | grep -E "(nibabel|nilearn|pandas|numpy|scipy|statsmodels|matplotlib|joblib)"
echo ""
echo "To use in future sessions:"
echo "  source ~/venv/connectivity/bin/activate"
