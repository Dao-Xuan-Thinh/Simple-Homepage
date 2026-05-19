#!/bin/bash
# Run the Mac Mini Stats API
# =====================================
#
# ── First-time setup ──────────────────────────────────────────────
#
# 1. Enable Tailscale Funnel (exposes port 9000 to the public internet):
#
#   tailscale funnel 9000
#
#    This makes the API reachable at:
#    https://my-biggest-beefsteak.tail437237.ts.net/api/stats?token=...
#    (No port number needed — Funnel routes :443 → :9000 automatically)
#
#    To disable public access later:
#    tailscale funnel --bg off
#
# 2. (Optional) TLS cert for direct Tailscale-IP access — not needed
#    if you only use Funnel (Funnel handles TLS automatically):
#
#   sudo tailscale cert my-biggest-beefsteak.tail437237.ts.net
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

# Check Funnel status
if ! tailscale funnel status 2>/dev/null | grep -q "9000"; then
  echo "⚠️  Tailscale Funnel is not active on port 9000."
  echo "   Run:  tailscale funnel 9000"
  echo "   Then restart this script."
  echo ""
fi

echo "Installing dependencies..."
pip3 install -r requirements.txt -q

echo "Starting Mac Mini Stats API..."
python3 server.py
