#!/usr/bin/env bash
# Visual Inspector — Raspberry Pi install script.
#
# Installs system deps, sets up a Python venv, installs the package in dev mode,
# seeds the config, and (optionally) installs the systemd unit.
#
# Usage:
#   ./scripts/install-pi.sh                # full install, no systemd
#   ./scripts/install-pi.sh --systemd      # also install + enable systemd service
#   ./scripts/install-pi.sh --no-deps      # skip apt step (e.g. offline install)
#
# Tested on Raspberry Pi OS Bookworm (Debian 12).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

WITH_SYSTEMD=0
SKIP_DEPS=0
for arg in "$@"; do
    case "$arg" in
        --systemd) WITH_SYSTEMD=1 ;;
        --no-deps)  SKIP_DEPS=1 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

echo "==> Visual Inspector Pi install (project root: $PROJECT_ROOT)"

if [[ $SKIP_DEPS -eq 0 ]]; then
    echo "==> Installing system packages"
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        libatlas-base-dev \
        libjpeg-dev \
        libpng-dev \
        libtiff-dev \
        libavcodec-dev \
        libavformat-dev \
        libswscale-dev \
        libv4l-dev \
        v4l-utils \
        alsa-utils \
        pulseaudio \
        ca-certificates
fi

echo "==> Creating Python venv at .venv"
if [[ ! -d "$PROJECT_ROOT/.venv" ]]; then
    "$PROJECT_ROOT/scripts/run.sh" 2>/dev/null || true
    python3 -m venv "$PROJECT_ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$PROJECT_ROOT/.venv/bin/activate"

echo "==> Upgrading pip"
python -m pip install --upgrade pip wheel setuptools

echo "==> Installing Python dependencies"
pip install -r "$PROJECT_ROOT/requirements.txt"
pip install -r "$PROJECT_ROOT/requirements-pi.txt"
pip install -e "$PROJECT_ROOT"

echo "==> Seeding runtime config"
if [[ ! -f "$PROJECT_ROOT/config/config.json" ]]; then
    cp "$PROJECT_ROOT/config/config.pi.json" "$PROJECT_ROOT/config/config.json"
    echo "    Copied config/config.pi.json -> config/config.json"
else
    echo "    config/config.json already exists, leaving alone"
fi

echo "==> Creating data directories"
mkdir -p "$PROJECT_ROOT/data"/{references,captures,alerts,samples}

# Make sure non-root user can access GPIO (Pi specific)
if [[ $WITH_SYSTEMD -eq 1 ]]; then
    echo "==> Installing systemd service"
    sudo cp "$PROJECT_ROOT/systemd/visinsp.service" /etc/systemd/system/visinsp.service
    sudo sed -i "s|/opt/visual-inspector|$PROJECT_ROOT|g" /etc/systemd/system/visinsp.service
    sudo sed -i "s|User=pi|User=$(whoami)|g" /etc/systemd/system/visinsp.service
    sudo systemctl daemon-reload
    sudo systemctl enable visinsp.service
    sudo systemctl start  visinsp.service
    echo "    Service installed and started. Check: sudo systemctl status visinsp"
fi

echo "==> Pi install complete."
echo "    Start manually with:  ./scripts/run.sh"
echo "    Open the UI at:       http://$(hostname -I | awk '{print $1}'):5000"
