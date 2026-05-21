#!/bin/bash
# Run the Mac Mini Stats API
# =====================================
#
# ── First-time setup ──────────────────────────────────────────────
#
# 1. Set the write token (one-time, add to ~/.zshrc to persist):
#
#   export HOMEPAGE_WRITE_TOKEN="your-secret-token"
#
#    Generate a token with:
#    python3 -c "import secrets; print(secrets.token_hex(24))"
#
# 2. Enable Tailscale Funnel on port 8443:
#
#   tailscale funnel --bg --https=8443 9000
#
#    This makes the API reachable at:
#    https://my-biggest-beefsteak.tail437237.ts.net:8443/api/stats?token=...
#
# ── Start the server ──────────────────────────────────────────────
#
# Normal:
#   bash run.sh
#
# Background (survives SSH logout):
#   nohup bash run.sh > api.log 2>&1 &

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOSTNAME="my-biggest-beefsteak.tail437237.ts.net"

if [ -z "$HOMEPAGE_WRITE_TOKEN" ]; then
  echo "⚠️  HOMEPAGE_WRITE_TOKEN is not set - settings saves will be rejected."
  echo "   Set it with:  export HOMEPAGE_WRITE_TOKEN=\"your-secret-token\""
  echo "   Add it to ~/.zshrc to persist across reboots."
  echo ""
fi

echo "Installing dependencies..."
pip3 install -r requirements.txt -q

echo "Starting Mac Mini Stats API..."
python3 server.py
