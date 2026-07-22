# Architecture

Visual Inspector is a **modular monolith**. It runs as a single Python
process on the Raspberry Pi, with clear internal boundaries so that any
of the three logical services can be split into its own process or host
later by changing only the transport at the boundary.

## Three logical services

| Service         | Responsibility                                                 | Must run on Pi? |
| --------------- | -------------------------------------------------------------- | --------------- |
| **Hardware**    | GPIO in/out, USB camera enumeration + capture                  | **Yes**         |
| **Inspection**  | Reference image + bbox compare, threshold, FP/FN/V feedback     | No              |
| **Web / UI**    | Flask + SocketIO API, Carbon-styled operator UI                | No              |

### Why one process on the Pi?

* The Pi Zero 2 W has only **512 MB of RAM**; running multiple Python
  interpreters eats into that headroom quickly.
* The hardware (USB cameras + GPIO) **only exists on the Pi**; the other
  services need a way to reach it. In-process is the lowest-latency,
  lowest-overhead option.
* Splitting later is straightforward: every cross-module call goes
  through one of the explicit boundaries (state store, event bus, or
  the `AppContext`). Replacing the in-process version with an HTTP /
  WebSocket client is a self-contained refactor.

### Why this is the right shape for future splits

The internal modules have deliberately narrow APIs:

* `core/state_store.py` — pure SQLite CRUD. No Flask, no GPIO. If you
  want to put the DB on a stronger box later, just point
  `paths.db_path` at an SMB / NFS share, or add an HTTP wrapper
  (`/api/...` already exists, so the SQLite file can become a server).
* `core/event_bus.py` — a 60-line synchronous pub/sub. Replace with
  Redis pub/sub, ZeroMQ, or a plain HTTP webhook later — every
  subscriber is a `(topic, payload) -> None` callable.
* `hardware/*` — the only module that imports OpenCV or RPi.GPIO.
  Trivially relocatable to a different host: just expose the same
  `CameraManager` and `GpioBackend` over a socket.

## Data flow on a trigger

```
  physical switch closes
        |
        v
  RpiGpio (or GpioMock) detects falling edge
        |
        v
  Daemon._handle_trigger(pin_id)
        |
        v
  for each enabled Trigger for pin_id:
        |
        v
  load Job + Reference + bounding boxes
        |
        v
  CameraManager.capture(camera_id)
        |
        v
  InspectionEngine.inspect(frame, reference, job)
        |   - per-bbox matchTemplate score
        |   - weighted mean
        v
  overall_score, passed = (score >= job.threshold)
        |
        v
  StateStore.record_inspection(...)
        |
        v
  bus.publish("inspection_complete", ...)
        |
        v
  AlertManager.raise_alert(...) if !passed
        |   - record AlertRecord
        |   - bus.publish("alert_new", ...)
        |   - fire actions_on_fail
        |       - GPIOAction: set output pin
        |       - SoundAction: beep
        |       - VisualAction: socketio.emit("visual_flash", ...)
        |       - NotificationAction: socketio.emit("notification", ...)
        v
  Web UI receives alert_new over WebSocket, flashes the screen,
  shows a toast, and lists it in the alerts table for dismissal.
        |
        v
  operator clicks Valid / FP / FN
        |
        v
  /api/alerts/<id>/dismiss (POST {verdict, notes})
        |
        v
  AlertManager.dismiss_alert(...)
        |   - if FP: job.threshold += step (clamped)
        |   - if FN: job.threshold -= step (clamped)
        |   - record to threshold_history
        v
  bus.publish("alert_resolved", ...)
```

## Module map

```
src/visinsp/
├── actions/        # Action handlers + registry (GPIO, sound, visual, notification)
├── api/            # Flask + SocketIO + JSON routes
├── core/           # State store, event bus, inspection, alerts, threshold, retention
├── hardware/       # GPIO backend (RPi + mock), camera manager
├── models/         # Dataclasses for Pin, Trigger, Reference, BoundingBox, Job, Action, ...
├── services/       # Runnable entrypoints (daemon, web_server, mock_hardware, cli)
└── web/            # Jinja templates + Carbon-styled static assets
```

## SQLite schema (v1)

Tables:

* `schema_version` — current schema version (used by future migrations)
* `pins` — BCM pin configuration
* `triggers` — pin_id + job_id + edge
* `references` — reference images (path, dims, name)
* `bboxes` — bounding boxes per reference
* `jobs` — reference_id, camera_id, threshold, threshold_step, actions (JSON)
* `inspections` — one row per trigger; per-box scores as JSON
* `alerts` — one row per failed inspection; verdict
* `threshold_history` — append-only log of every threshold change
* `settings` — singleton row for global tunables

Indices: `triggers(pin_id)`, `bboxes(reference_id)`, `inspections(job_id)`,
`alerts(job_id)`, `alerts(verdict)`, `threshold_history(job_id)`.

Migrations are additive; bump `SCHEMA_VERSION` and add a per-version
block to `StateStore.ensure_schema`.

## Threading model

| Thread                          | Owner        | Purpose                                            |
| ------------------------------- | ------------ | -------------------------------------------------- |
| Main                            | CLI / wsgi   | Flask + SocketIO request handling                  |
| `visinsp-gpio-watch`            | Daemon       | `gpio.wait_for_edge(...)` -> run_job               |
| `visinsp-pin-bcast`             | Daemon       | Publish `pin_state` over the bus every ~1s         |
| `visinsp-rpi-gpio-poll`         | RpiGpio      | Poll actual GPIO; debounce; fire events            |
| `visinsp-retention`             | RetentionWorker | Hourly sweep: prune old captures/alerts/history |
| Flask-SocketIO worker thread    | SocketIO     | Push events to connected browsers                  |

All cross-thread state access goes through `StateStore`'s internal
`RLock`, so SQLite operations are serialised per process.
