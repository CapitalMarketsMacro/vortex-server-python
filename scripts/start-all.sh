#!/usr/bin/env bash
# Launch all Vortex processes in the correct order.
# Each runs in the background; Ctrl-C sends SIGINT to the group.
#
# Order:
#   1. Seed Mongo (foreground, must finish before server starts)
#   2. Simulated WS feed server  (background)
#   3. Simulated NATS publisher   (background)
#   4. Vortex data server          (background)
#   5. Vortex admin GUI            (background)
#
# Usage:
#   scripts/start-all.sh                # all processes
#   scripts/start-all.sh --no-sims      # server + admin only (no simulators)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

NO_SIMS=false
for arg in "$@"; do
    case "$arg" in
        --no-sims) NO_SIMS=true ;;
    esac
done

# Activate venv once for all child processes
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f .venv/Scripts/activate ]]; then
        source .venv/Scripts/activate
    elif [[ -f .venv/bin/activate ]]; then
        source .venv/bin/activate
    fi
fi

PIDS=()

cleanup() {
    echo ""
    echo "=== Shutting down all Vortex processes ==="
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Stopping PID $pid"
            kill "$pid" 2>/dev/null || true
        fi
    done
    # Give them a few seconds to drain
    sleep 2
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Force-killing PID $pid"
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
    echo "=== All stopped ==="
}
trap cleanup EXIT INT TERM

# ── 1. Seed Mongo ──────────────────────────────────────────────────────────
echo "=== Step 1: Seed Mongo ==="
python scripts/seed_mongo.py
echo ""

# ── 2. Simulated WS feed ──────────────────────────────────────────────────
if [[ "$NO_SIMS" == "false" ]]; then
    echo "=== Step 2: Starting simulated WS feed ==="
    python scripts/sim_ws_feed.py &
    PIDS+=($!)
    echo "  PID: ${PIDS[-1]}"
    sleep 1

    # ── 3. Simulated NATS publisher ────────────────────────────────────────
    echo "=== Step 3: Starting simulated NATS publisher ==="
    python scripts/sim_nats_publisher.py &
    PIDS+=($!)
    echo "  PID: ${PIDS[-1]}"
    sleep 1
fi

# ── 4. Vortex data server ─────────────────────────────────────────────────
echo "=== Step 4: Starting Vortex server ==="
python -m vortex.server &
PIDS+=($!)
echo "  PID: ${PIDS[-1]}"
sleep 2

# ── 5. Vortex admin GUI ───────────────────────────────────────────────────
echo "=== Step 5: Starting Vortex admin GUI ==="
python -m vortex.admin.app &
PIDS+=($!)
echo "  PID: ${PIDS[-1]}"

echo ""
echo "============================================="
echo "  All Vortex processes running."
echo ""
echo "  Data server:    ws://0.0.0.0:8080/websocket"
echo "  Health:         http://0.0.0.0:8080/health/ready"
echo "  Metrics:        http://0.0.0.0:8080/metrics"
echo "  Admin GUI:      http://0.0.0.0:8090/"
echo "  Live status:    http://0.0.0.0:8090/status"
echo ""
echo "  Press Ctrl-C to stop all."
echo "============================================="
echo ""

# Wait for any child to exit (or for Ctrl-C)
wait
