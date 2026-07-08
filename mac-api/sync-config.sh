#!/usr/bin/env bash
#
# sync-config.sh — copy the LIVE config.json (the one the running server reads and
# the settings modal writes to) into this repo's committed copy, so the two never
# silently drift apart.
#
# The live config lives outside the repo on the Mac mini. Point at it via, in order
# of precedence:
#   1. first argument:            ./sync-config.sh /path/to/live/config.json
#   2. $HOMEPAGE_LIVE_CONFIG env var
#   3. default: ~/Projects/API for Homepage Server/config.json
#
# Usage:
#   cd mac-api && ./sync-config.sh          # then: git diff -- mac-api/config.json
#
set -euo pipefail

LIVE="${1:-${HOMEPAGE_LIVE_CONFIG:-$HOME/Projects/API for Homepage Server/config.json}}"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="$REPO_DIR/config.json"

if [[ ! -f "$LIVE" ]]; then
  echo "ERROR: live config not found: $LIVE" >&2
  echo "  Pass the path as an argument or set HOMEPAGE_LIVE_CONFIG." >&2
  exit 1
fi

# Refuse to copy a broken config into the repo.
python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$LIVE"

if cmp -s "$LIVE" "$DEST"; then
  echo "Already in sync: $DEST"
  exit 0
fi

cp "$LIVE" "$DEST"
echo "Synced live config -> $DEST"
echo "Review with: git diff -- mac-api/config.json"
