#!/usr/bin/env bash
# Visual Inspector — WSL / x86 install script.
#
# Sets up a Python venv, installs deps (no RPi.GPIO), seeds the WSL config,
# and creates the sample data dir.
#
# Usage:
#   ./scripts/install-wsl.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> Visual Inspector WSL install (project root: $PROJECT_ROOT)"

# ---- Detect Python ----
PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
    if command -v python3 >/dev/null 2>&1; then
        PY="python3"
    elif command -v python >/dev/null 2>&1; then
        PY="python"
    else
        echo "ERROR: no python3 in PATH. Install with: sudo apt install python3 python3-venv python3-pip" >&2
        exit 1
    fi
fi
echo "==> Using python: $($PY --version)"

# ---- System packages (best effort, don't fail if sudo isn't available) ----
if command -v apt-get >/dev/null 2>&1; then
    SUDO=""
    [[ $EUID -ne 0 ]] && SUDO="sudo"
    echo "==> Installing system packages (sudo may prompt)"
    $SUDO apt-get update || true
    $SUDO apt-get install -y --no-install-recommends \
        python3-venv \
        python3-pip \
        libjpeg-dev \
        libpng-dev \
        libtiff-dev \
        libavcodec-dev \
        libavformat-dev \
        libswscale-dev \
        libatlas-base-dev \
        v4l-utils \
        ca-certificates || true
fi

# ---- Venv ----
echo "==> Creating Python venv at .venv"
if [[ ! -d "$PROJECT_ROOT/.venv" ]]; then
    "$PY" -m venv "$PROJECT_ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$PROJECT_ROOT/.venv/bin/activate"

echo "==> Upgrading pip"
python -m pip install --upgrade pip wheel setuptools

echo "==> Installing Python dependencies"
pip install -r "$PROJECT_ROOT/requirements.txt"
pip install -r "$PROJECT_ROOT/requirements-wsl.txt"
pip install -e "$PROJECT_ROOT"

# ---- Seed WSL config + sample data ----
echo "==> Seeding WSL runtime config"
if [[ ! -f "$PROJECT_ROOT/config/config.json" ]]; then
    cp "$PROJECT_ROOT/config/config.wsl.json" "$PROJECT_ROOT/config/config.json"
    echo "    Copied config/config.wsl.json -> config/config.json"
else
    echo "    config/config.json already exists, leaving alone"
fi

echo "==> Creating data directories"
mkdir -p "$PROJECT_ROOT/data"/{references,captures,alerts,samples}

echo "==> Seeding sample reference images"
python -m visinsp.services.cli seed || echo "    (seed step failed — you can run it manually later)"

echo "==> WSL install complete."
echo "    Start with:   ./scripts/run.sh"
echo "    Open UI at:   http://localhost:5000"
