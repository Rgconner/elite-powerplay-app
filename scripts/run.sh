#!/usr/bin/env bash
# Visual Inspector — main run script.
#
# Picks the right Python interpreter, ensures a project-local venv
# exists at .venv/, installs deps into the venv (NOT the system Python,
# which is blocked by PEP 668 on Debian 12+ / Ubuntu 23.04+), and then
# starts the daemon + web server.
#
# Environment variables:
#   VISINSP_ENV       "pi" | "wsl" | "auto" (default: auto)
#   VISINSP_CONFIG    path to config.json (default: ./config/config.json)
#   VISINSP_HOST      bind host (default: from config)
#   VISINSP_PORT      bind port (default: from config)
#   PYTHON            override the python interpreter used to bootstrap

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ---- Determine environment ----
if [[ "${VISINSP_ENV:-auto}" == "auto" ]]; then
    if grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null \
            || { [[ -f /proc/device-tree/model ]] \
                 && grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; }; then
        VISINSP_ENV="pi"
    elif uname -r 2>/dev/null | grep -qi "microsoft"; then
        VISINSP_ENV="wsl"
    elif [[ "$(uname -s)" == "Linux" ]]; then
        VISINSP_ENV="wsl"
    elif [[ "$(uname -s)" == "Darwin" ]]; then
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
        echo "[run] No preset config found — copying config.example.json"
        cp "$PROJECT_ROOT/config/config.example.json" "$VISINSP_CONFIG"
    fi
fi

# ---- Pick a bootstrap Python (used only to create the venv if needed) ----
BOOT_PY="${PYTHON:-}"
if [[ -z "$BOOT_PY" ]]; then
    if command -v python3 >/dev/null 2>&1; then
        BOOT_PY="python3"
    elif command -v python >/dev/null 2>&1; then
        BOOT_PY="python"
    else
        echo "[run] ERROR: no python interpreter found on PATH" >&2
        exit 1
    fi
fi
echo "[run] using bootstrap python: $($BOOT_PY --version)"

# ---- Locate / create a project-local venv ----
# We always use a venv to avoid PEP 668 "externally-managed-environment"
# errors on modern Debian / Ubuntu (and the same trend on Fedora / RHEL).
VENV="$PROJECT_ROOT/.venv"
if [[ -x "$VENV/bin/python3" ]]; then
    echo "[run] using existing venv: $VENV"
    PY="$VENV/bin/python3"
elif "$BOOT_PY" -m venv "$VENV" >/dev/null 2>&1; then
    echo "[run] created venv at $VENV"
    PY="$VENV/bin/python3"
else
    echo "[run] WARN: could not create venv at $VENV; falling back to system interpreter."
    echo "[run] WARN: pip may fail with 'externally-managed-environment' (PEP 668)."
    PY="$BOOT_PY"
fi

# ---- Ensure the active Python has the project deps ----
if ! "$PY" -c "import flask, flask_socketio, cv2, numpy" >/dev/null 2>&1; then
    echo "[run] Python deps missing — installing requirements ($VISINSP_ENV) into the venv..."
    # Only fall back to --break-system-packages if we're using the
    # system interpreter (the venv has no such restriction).
    PIP_FLAGS=()
    if [[ "$PY" != "$BOOT_PY" ]] || [[ -d "$VENV" && "$PY" -ef "$VENV/bin/python3" ]]; then
        :  # in-venv: no flag needed
    else
        PIP_FLAGS+=(--break-system-packages)
    fi
    "$PY" -m pip install "${PIP_FLAGS[@]}" -q --upgrade pip || true
    "$PY" -m pip install "${PIP_FLAGS[@]}" -q -r "$PROJECT_ROOT/requirements.txt" || {
        echo "[run] ERROR: pip install of common requirements failed." >&2
        echo "[run]        Please run ./scripts/install-${VISINSP_ENV}.sh manually." >&2
        exit 1
    }
    if [[ -f "$PROJECT_ROOT/requirements-${VISINSP_ENV}.txt" ]]; then
        "$PY" -m pip install "${PIP_FLAGS[@]}" -q -r "$PROJECT_ROOT/requirements-${VISINSP_ENV}.txt" || \
            echo "[run] WARN: platform-specific requirements failed (non-fatal)."
    fi
    # Make our own package importable as `visinsp`.
    "$PY" -m pip install "${PIP_FLAGS[@]}" -q -e "$PROJECT_ROOT" || \
        echo "[run] WARN: editable install of the package failed (non-fatal)."
fi

# ---- Launch ----
export VISINSP_CONFIG
export VISINSP_ENV
exec "$PY" -m visinsp.services.cli run
