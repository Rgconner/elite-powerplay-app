# Installation

Visual Inspector runs on two target environments:

* **Raspberry Pi Zero 2 W** (production)
* **WSL on Windows / x86 Linux** (development + UI testing)

Both share the same Python source; the difference is the dependency
set, the default config, and the GPIO backend.

---

## Quick start

### 1. Clone the repository

```bash
git clone <your-repo-url> visual-inspector
cd visual-inspector
```

### 2. Pick the branch for your environment

```bash
git checkout pi     # if you're on a Raspberry Pi
# or
git checkout wsl    # if you're on WSL / x86 Linux
```

The branches are **thin release branches** that only carry the
platform-specific config + install script; the code itself lives on
`main` (see [`branching.md`](branching.md)).

### 3. Install

On a Raspberry Pi:

```bash
./scripts/install-pi.sh                # full install, no systemd
./scripts/install-pi.sh --systemd      # also install + enable systemd
./scripts/install-pi.sh --no-deps      # skip apt step (offline install)
```

On WSL / x86 Linux:

```bash
./scripts/install-wsl.sh
```

The install scripts will:

* Create a Python 3 venv at `.venv/`
* Install the common requirements from `requirements.txt`
* Install the platform-specific requirements from `requirements-pi.txt`
  or `requirements-wsl.txt`
* Install the package itself in editable mode (`pip install -e .`)
* Seed `config/config.json` from the matching preset
* Create the `data/` directory tree

### 4. Run

```bash
./scripts/run.sh
# or, equivalently:
.venv/bin/python -m visinsp.services.cli run
```

Open the UI at <http://localhost:5000> (WSL) or
<http://<pi-hostname>:5000> (Pi).

---

## Raspberry Pi specifics

### System packages

The Pi install script installs:

| Package         | Why                                           |
| --------------- | --------------------------------------------- |
| `python3`       | Interpreter                                   |
| `python3-venv`  | Virtual environments                          |
| `python3-pip`   | Package manager                               |
| `libatlas-base-dev` | NumPy / OpenCV optimisation               |
| `libjpeg-dev`, `libpng-dev`, `libtiff-dev` | OpenCV image codecs |
| `libavcodec-dev`, `libavformat-dev`, `libswscale-dev` | OpenCV FFmpeg support |
| `libv4l-dev`, `v4l-utils` | USB camera support (Video4Linux)   |
| `alsa-utils`, `pulseaudio` | Audio out for the SoundAction     |

### GPIO access

`RPi.GPIO` requires the process to be in the `gpio` group, **or** to
be run as root. The install script does **not** add your user to the
`gpio` group automatically (that's a sysadmin policy decision); run
the daemon as root, or add yourself with:

```bash
sudo usermod -aG gpio $USER
# log out and back in for the group change to take effect
```

### systemd unit

`./scripts/install-pi.sh --systemd` installs `systemd/visinsp.service`
as `/etc/systemd/system/visinsp.service`, with paths rewritten to your
install location. Manage it with:

```bash
sudo systemctl status visinsp
sudo systemctl restart visinsp
sudo journalctl -u visinsp -f
```

The unit runs the process as the user who invoked the install script.

### Camera

Any USB UVC webcam will work. Plug it in before starting the daemon;
`v4l2-ctl --list-devices` should show it under `/dev/videoN`. The
`/api/cameras/refresh` endpoint re-probes the device list at runtime.

### Hardware GPIO wiring (input)

The example config expects:

```
  switch ----+----- GPIO 17 (BCM)
             |
          GND
```

Configure the pin as `pull: "up"`, `active_low: true`, `edge: "falling"`
in `config/config.json` to match a normally-open switch to ground.

### Hardware GPIO wiring (output)

```
  GPIO 27 (BCM) ----[ 1kΩ ]----[ LED ]---- GND
```

Outputs are driven by `RPi.GPIO.output(pin, GPIO.HIGH/LOW)`. For
relays / buzzers, use a transistor or driver board.

---

## WSL specifics

WSL has no real GPIO. The mock GPIO backend is used automatically:

* `force_backend: "mock"` is set in `config/config.wsl.json`
* The pin dashboard shows a **Toggle** button next to each input pin
* The WebSocket layer reflects the simulated edges in real time
* Sample reference images + sample captures are seeded by the install
  script so the UI has something to show

### Camera

* If you have a USB webcam passed through to WSL2 (via `usbipd-win`),
  the OpenCV backend picks it up automatically.
* Otherwise the sample-image fallback serves rotating synthetic images
  from `data/samples/`.

### Sound

* Windows: `winsound.Beep` is used.
* Linux: `paplay` (PulseAudio) or `aplay` (ALSA) — at least one should
  be present on a typical WSL Ubuntu image. If not, the action falls
  back to a terminal bell.
