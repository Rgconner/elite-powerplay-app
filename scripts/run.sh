#!/usr/bin/env bash
# Visual Inspector — main run script.
#
# Picks the right Python interpreter, ensures the runtime config exists,
# ensures deps are present, and starts the daemon + web server.
#
# Environment variables:
#   VISINSP_ENV       "pi" | "wsl" | "auto" (default: auto)
#   VISINSP_CONFIG    path to config.json (default: ./config/config.json)
#   VISINSP_HOST      bind host (default: from config)
#   VISINSP_PORT      bind port (default: from config)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ---- Determine environment ----
if [[ "${VISINSP_ENV:-auto}" == "auto" ]]; then
    if grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null || [[ -f /proc/device-tree/model ]] && grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
        VISINSP_ENV="pi"
    elif uname -r | grep -qi "microsoft" 2>/dev/null; then
        VISINSP_ENV="wsl"
    elif [[ "$(uname -s)" == "Linux" ]]; then
        VISINSP_ENV="wsl"
    else
        VISINSP_ENV="wsl"
    fi
fi
echo "[run] environment: $VISINSP_ENV"

# ---- Pick the config ----
VISINSP_CONFIG="${VISINSP_CONFIG:-$PROJECT_ROOT/config/config.json}"
if [[ ! -f "$VISINSP_CONFIG" ]]; then
    if [[ -f "$PROJECT_ROOT/config/config.${VISINSP_ENV}.json" ]]; then
        echo "[run] No config.json found — copying preset config.${VISINSP_ENV}.json"
        cp "$PROJECT_ROOT/config/config.${VISINSP_ENV}.json" "$VISINSP_CONFIG"
    else
        cp "$PROJECT_ROOT/config/config.example.json" "$VISINSP_CONFIG"
    fi
fi

# ---- Pick Python ----
PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
    if command -v python3 >/dev/null 2>&1; then
        PY="python3"
    elif command -v python >/dev/null 2>&1; then
        PY="python"
    else
        echo "[run] ERROR: no python interpreter found" >&2
        exit 1
    fi
fi
echo "[run] using python: $($PY --version)"

# ---- Ensure deps (best-effort, don't fail) ----
if ! "$PY" -c "import flask, flask_socketio, cv2, numpy" >/dev/null 2>&1; then
    echo "[run] Python deps missing — installing requirements ($VISINSP_ENV)..."
    "$PY" -m pip install -r "$PROJECT_ROOT/requirements.txt"
    if [[ -f "$PROJECT_ROOT/requirements-${VISINSP_ENV}.txt" ]]; then
        "$PY" -m pip install -r "$PROJECT_ROOT/requirements-${VISINSP_ENV}.txt"
    fi
fi

# ---- Launch ----
export VISINSP_CONFIG
export VISINSP_ENV
exec "$PY" -m visinsp.services.cli run
