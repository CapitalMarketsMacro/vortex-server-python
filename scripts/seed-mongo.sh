#!/usr/bin/env bash
# Seed the Vortex MongoDB with the initial transports and tables.
# Idempotent — safe to run multiple times (uses upsert).
#
# Usage:
#   scripts/seed-mongo.sh

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f .venv/Scripts/activate ]]; then
        source .venv/Scripts/activate
    elif [[ -f .venv/bin/activate ]]; then
        source .venv/bin/activate
    fi
fi

echo "=== Seeding Mongo (Vortex DB) ==="
python scripts/seed_mongo.py "$@"
echo "=== Done ==="
