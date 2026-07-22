# Configuration

Visual Inspector reads its config from `config/config.json`. If that
file doesn't exist, the per-environment preset (`config/config.pi.json`
or `config/config.wsl.json`) is used as a fallback.

You can override the location entirely with the `VISINSP_CONFIG`
environment variable:

```bash
VISINSP_CONFIG=/etc/visual-inspector.json ./scripts/run.sh
```

## Top-level keys

| Key            | Description                                                       |
| -------------- | ----------------------------------------------------------------- |
| `app`          | App name, version, environment, host, port, secret_key, theme     |
| `paths`        | Filesystem layout (data dir, references, captures, db, log)      |
| `environment`  | `force_backend`: `"pi"` \| `"mock"` \| `null` (auto)             |
| `logging`      | Log level, file/console output, rotation                          |
| `gpio`         | GPIO mode (BCM), default debounce, cleanup policy                 |
| `camera`       | Probe max index, capture timeout, WSL sample fallback             |
| `inspection`   | Match method, secondary metric, max image dimension, save policy  |
| `threshold`    | Default, step, min, max, history retention                        |
| `alerts`       | Retention days, auto-dismiss hours                                |
| `pins`         | Array of pin definitions                                          |
| `cameras`      | Array of camera definitions                                       |

## Pin definition

```json
{
  "id": "trigger_1",
  "name": "Station A Trigger",
  "bcm": 17,
  "direction": "input",      // "input" | "output"
  "pull": "up",              // "up" | "down" | null
  "active_low": true,        // invert logic for falling-edge sensors
  "debounce_ms": 200,        // per-pin debounce (overrides gpio.default_debounce_ms)
  "edge": "falling",         // "rising" | "falling" | "both" | "none"
  "enabled": true
}
```

* `direction=input` + `edge != none` makes the pin a trigger source.
* `direction=output` pins are used as action targets (e.g. driving a
  buzzer or stack light).

## Camera definition

```json
{
  "id": "cam_0",
  "name": "Station A Camera",
  "device_index": 0          // /dev/videoN
}
```

On WSL, if `wsl_sample_fallback: true` and no cameras are detected, the
`SampleImageCameraBackend` cycles through `data/samples/*.png` for
each capture.

## Inspection method

`inspection.match_method` is one of OpenCV's `matchTemplate` modes:

* `TM_CCOEFF_NORMED` (default, recommended)
* `TM_CCOEFF`
* `TM_CCORR_NORMED`
* `TM_CCORR`
* `TM_SQDIFF_NORMED`
* `TM_SQDIFF`

`inspection.secondary_metric` adds a secondary check (none, `MSE`, or
`SSIM` if `scikit-image` is installed) and is reported per box in the
inspection result, but does not affect the pass/fail decision.

## Threshold semantics

The threshold is a probability in `[0, 1]`. The inspection engine
computes a per-box score and a weighted-mean overall score; the
inspection passes if `overall >= job.threshold`.

Operator feedback moves the threshold:

| Verdict          | Effect on `job.threshold`     |
| ---------------- | ----------------------------- |
| `valid`          | no change                     |
| `false_positive` | `+ job.threshold_step` (clamp) |
| `false_negative` | `- job.threshold_step` (clamp) |

Each change is recorded in the `threshold_history` table for audit
and tuning.

## Runtime-mutable settings

These are stored in the `settings` table and can be changed at
runtime via the API (no daemon restart required):

* `default_threshold`
* `default_threshold_step`
* `min_threshold` / `max_threshold`
* `retention_days` (alerts)
* `history_retention_days` (threshold history)
* `theme` (`g100` or `white`)
* `auto_dismiss_after_hours`

The `PUT /api/settings` endpoint accepts any subset; the response
includes the full updated settings dict.

## Environment variable overrides

| Variable               | Effect                                       |
| ---------------------- | -------------------------------------------- |
| `VISINSP_CONFIG`       | Path to the JSON config file                  |
| `VISINSP_ENV`          | `pi` / `wsl` / `auto` (affects auto-detect)   |
| `VISINSP_HOST`         | Bind address for the web server               |
| `VISINSP_PORT`         | Bind port                                     |
| `VISINSP_PROJECT_ROOT` | Override the project root for path resolution |
