# Visual Inspector

A camera-based manufacturing defect detection system that compares trigger-captured
images against a stored reference image, with operator-driven feedback to tune
the detection threshold over time.

Designed to run on a **Raspberry Pi Zero 2 W** (1 GHz quad-core, 512 MB RAM), with
a full **WSL mock mode** for local interface development and testing.

The UI follows the **IBM Design Language (Carbon Design System)** and is rendered
in the operator's browser — the Pi only serves a small Flask + SocketIO app.

---

## Features

- GPIO trigger inputs (physical switches, optical sensors, PLC outputs) drive
  image capture from any attached USB camera.
- A stored **reference image** per job, with one or more user-drawn
  **bounding boxes** defining the regions to be compared.
- Per-bounding-box template matching (OpenCV) aggregated to a single weighted
  confidence score, compared to a per-job threshold.
- On failure, configurable **actions** fire: GPIO output, sound, in-browser
  visual flash, on-screen notification.
- Operator can dismiss alerts as **Valid (true defect)**, **False Positive**,
  or **False Negative**; the threshold is auto-tuned up or down by a small,
  per-job step in response.
- WSL testing mode: simulate GPIO inputs from the dashboard, see simulated
  output pin state, feed sample images, no Pi required.
- Modular monolith architecture: hardware, inspection engine, and web UI are
  independent modules that can be split into separate processes or hosts
  later by changing the transport at their boundary.

---

## Project Structure

```
visual-inspector/
├── config/                 # environment-specific JSON configs
├── data/                   # gitignored runtime data (references, captures, db)
├── docs/                   # architecture, installation, configuration, UI design
├── scripts/                # install + run scripts per environment
├── src/visinsp/            # Python package
│   ├── actions/            # action handlers (GPIO, sound, visual, notification)
│   ├── api/                # Flask + SocketIO routes
│   ├── core/               # state store, event bus, inspection, alerts, threshold
│   ├── hardware/           # GPIO + camera backends (RPi + mock)
│   ├── models/             # dataclasses for Pin, Trigger, Job, Reference, ...
│   ├── services/           # runnable entrypoints (daemon, web server, CLI)
│   └── web/                # Jinja templates + Carbon-styled static assets
├── systemd/                # optional Pi autostart unit
└── tests/                  # unit tests + fixtures
```

---

## Quick Start

### On the Raspberry Pi

```bash
git clone <repo-url> visual-inspector
cd visual-inspector
git checkout pi          # thin release branch with Pi-only config + install
./scripts/install-pi.sh
cp config/config.pi.json config/config.json
./scripts/run.sh
# Open http://<pi-hostname>:5000 in a browser
```

### On WSL (Windows Subsystem for Linux)

```bash
git clone <repo-url> visual-inspector
cd visual-inspector
git checkout wsl
./scripts/install-wsl.sh
cp config/config.wsl.json config/config.json
python -m visinsp.cli seed    # create demo reference image
./scripts/run.sh
# Open http://localhost:5000
```

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — module boundaries, data flow, IPC.
- [`docs/installation.md`](docs/installation.md) — Pi and WSL install steps.
- [`docs/configuration.md`](docs/configuration.md) — config schema, environment toggles.
- [`docs/branching.md`](docs/branching.md) — how the `main` / `pi` / `wsl` branches relate.
- [`docs/wsl-mock-mode.md`](docs/wsl-mock-mode.md) — using the GPIO mock and sample data.
- [`docs/ui-design.md`](docs/ui-design.md) — IBM Design Language (Carbon) usage notes.

---

## License

MIT — see [`LICENSE`](LICENSE).
