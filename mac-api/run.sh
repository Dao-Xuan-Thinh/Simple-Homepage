#!/bin/bash
# Run the Mac Mini Stats API (HTTPS)
# =====================================
# First-time setup — run this ONCE to get a TLS certificate:
#
#   sudo tailscale cert my-biggest-beefsteak.tail437237.ts.net
#
# That saves .crt and .key files to the current directory.
# Move them to your home directory if needed:
#
#   mv my-biggest-beefsteak.tail437237.ts.net.* ~/
#
# Then start the server:
#   bash run.sh
#
# Background mode (survives SSH logout):
#   nohup bash run.sh > api.log 2>&1 &

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOSTNAME="my-biggest-beefsteak.tail437237.ts.net"

# Check for cert files
if [ ! -f "$HOME/$HOSTNAME.crt" ] || [ ! -f "$HOME/$HOSTNAME.key" ]; then
  echo "⚠️  TLS certificate not found!"
  echo "   Run:  sudo tailscale cert $HOSTNAME"
  echo "   Then: mv $HOSTNAME.* ~/"
  echo ""
  echo "   Without certs the API runs plain HTTP, which GitHub Pages will block."
  echo ""
fi

echo "Installing dependencies..."
pip3 install -r requirements.txt -q

echo "Starting Mac Mini Stats API..."
python3 server.py
