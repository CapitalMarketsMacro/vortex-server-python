#!/usr/bin/env bash
# Start the Vortex Admin GUI (Flask)
#
# Usage:
#   scripts/start-admin.sh
#   VORTEX_ADMIN__VORTEX_URL=http://remote-host:8080 scripts/start-admin.sh

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f .venv/Scripts/activate ]]; then
        source .venv/Scripts/activate
    elif [[ -f .venv/bin/activate ]]; then
        source .venv/bin/activate
    fi
fi

echo "=== Vortex Admin GUI ==="
echo "  PID:       $$"
echo "  Dashboard: http://${VORTEX_ADMIN__HOST:-0.0.0.0}:${VORTEX_ADMIN__PORT:-8090}/"
echo "  Status:    http://${VORTEX_ADMIN__HOST:-0.0.0.0}:${VORTEX_ADMIN__PORT:-8090}/status"
echo "  Vortex:    ${VORTEX_ADMIN__VORTEX_URL:-http://localhost:8080}"
echo ""

exec python -m vortex.admin.app "$@"
