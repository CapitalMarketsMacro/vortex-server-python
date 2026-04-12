#!/usr/bin/env bash
# Create a virtual environment and install all dependencies.
#
# Usage:
#   scripts/install.sh              # production + dev deps
#   scripts/install.sh --prod       # production deps only

set -euo pipefail
cd "$(dirname "$0")/.."

EXTRAS="dev"
for arg in "$@"; do
    case "$arg" in
        --prod) EXTRAS="" ;;
    esac
done

# Detect Python — prefer 3.11+ explicitly, fall back to python3 / python
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        major="${ver%%.*}"
        minor="${ver##*.}"
        if [[ "$major" -ge 3 && "$minor" -ge 11 ]]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "ERROR: Python 3.11+ is required but not found on PATH."
    echo "       Install Python 3.11+ and try again."
    exit 1
fi

echo "=== Vortex Install ==="
echo "  Python:  $PYTHON ($($PYTHON --version 2>&1))"
echo "  Extras:  ${EXTRAS:-none}"
echo ""

# Create venv if it doesn't exist
if [[ ! -d .venv ]]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv .venv
fi

# Activate
if [[ -f .venv/Scripts/activate ]]; then
    source .venv/Scripts/activate       # Windows / Git Bash
elif [[ -f .venv/bin/activate ]]; then
    source .venv/bin/activate           # Linux / macOS
fi

# Upgrade pip
echo "Upgrading pip..."
python -m pip install --upgrade pip --quiet

# Install
if [[ -n "$EXTRAS" ]]; then
    echo "Installing vortex-server-python with [$EXTRAS] extras..."
    pip install -e ".[$EXTRAS]" --quiet
else
    echo "Installing vortex-server-python (production only)..."
    pip install -e . --quiet
fi

echo ""
echo "=== Install complete ==="
echo "  Activate with:  source .venv/bin/activate  (or .venv\\Scripts\\activate on Windows)"
echo "  Run tests:      pytest tests/ -v"
echo "  Seed Mongo:     scripts/seed-mongo.sh"
echo "  Start all:      scripts/start-all.sh"
