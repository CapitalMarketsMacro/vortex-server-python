#!/usr/bin/env bash
# Start the simulated upstream WebSocket price feed server
# VortexServer's WSSourceConnector connects to this as a client.
#
# Usage:
#   scripts/start-sim-ws-feed.sh
# Default listens on ws://localhost:9000

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f .venv/Scripts/activate ]]; then
        source .venv/Scripts/activate
    elif [[ -f .venv/bin/activate ]]; then
        source .venv/bin/activate
    fi
fi

echo "=== Simulated WS Price Feed ==="
echo "  PID:    $$"
echo "  Listen: ws://localhost:9000"
echo ""

exec python scripts/sim_ws_feed.py "$@"
