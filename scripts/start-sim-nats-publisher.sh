#!/usr/bin/env bash
# Start the simulated NATS UST trade publisher
# Publishes to rates.ust.trades.sim on nats://montunoblenumbat2404:8821
#
# Usage:
#   scripts/start-sim-nats-publisher.sh

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f .venv/Scripts/activate ]]; then
        source .venv/Scripts/activate
    elif [[ -f .venv/bin/activate ]]; then
        source .venv/bin/activate
    fi
fi

echo "=== Simulated NATS Trade Publisher ==="
echo "  PID:     $$"
echo "  Target:  nats://montunoblenumbat2404:8821"
echo "  Subject: rates.ust.trades.sim"
echo ""

exec python scripts/sim_nats_publisher.py "$@"
