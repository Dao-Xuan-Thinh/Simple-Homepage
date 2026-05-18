#!/bin/bash
# Run the Mac Mini Stats API
# Usage: bash run.sh
#
# For background (persistent after SSH logout):
#   nohup bash run.sh > api.log 2>&1 &

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Installing dependencies..."
pip3 install -r requirements.txt -q

echo "Starting Mac Mini Stats API..."
python3 server.py
