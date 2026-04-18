#!/usr/bin/env bash
# Start the Vortex data server (Perspective + connectors)
#
# Usage:
#   scripts/start-server.sh              # defaults
#   VORTEX_LOG_LEVEL=DEBUG scripts/start-server.sh

set -euo pipefail
cd "$(dirname "$0")/.."

# Activate venv if not already active
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f .venv/Scripts/activate ]]; then
        source .venv/Scripts/activate       # Windows / Git Bash
    elif [[ -f .venv/bin/activate ]]; then
        source .venv/bin/activate           # Linux / macOS
    fi
fi

echo "=== Vortex Server ==="
echo "  PID:       $$"
echo "  WebSocket: ws://${VORTEX_HOST:-0.0.0.0}:${VORTEX_PORT:-8080}/websocket"
echo "  Health:    http://${VORTEX_HOST:-0.0.0.0}:${VORTEX_PORT:-8080}/health/ready"
echo "  Metrics:   http://${VORTEX_HOST:-0.0.0.0}:${VORTEX_PORT:-8080}/metrics"
echo "  Status:    http://${VORTEX_HOST:-0.0.0.0}:${VORTEX_PORT:-8080}/api/status"
echo ""

exec python -m vortex.server "$@"
