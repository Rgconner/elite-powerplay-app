# WSL mock mode

WSL has no real GPIO, so Visual Inspector runs in **mock mode** for
local development. The mock backend is functionally complete — you
can develop, test, and demo the full application on a laptop with
no hardware attached.

## What's mocked

| Thing           | Mock behaviour                                                  |
| --------------- | --------------------------------------------------------------- |
| GPIO inputs     | Click **Toggle** on a pin card; pin state + edge event fire.   |
| GPIO outputs    | Use **HIGH / LOW** buttons; state changes live in the dashboard. |
| Cameras         | No real camera → sample images served in rotation from `data/samples/`. |
| Sound           | `winsound.Beep` on Windows; `paplay` / `aplay` on Linux; else terminal bell. |
| State           | Identical — SQLite file in `data/visinsp.db`.                  |

The `force_backend: "mock"` key in `config/config.wsl.json` forces
the GPIO factory to pick the mock backend. On a real Pi without that
override, the factory picks the RPi backend automatically.

## The pin dashboard

The **Dashboard → Pin State** card shows every configured pin with:

* A coloured LED dot (green = HIGH, grey = LOW, ring for inputs)
* The pin's BCM number, direction, edge
* For **input pins** (in mock mode): a **Toggle** button that flips
  the level and fires an edge. The daemon reacts just like a real
  switch.
* For **output pins**: **HIGH** and **LOW** buttons to drive the line.

Pin state is also broadcast over WebSocket (`pin_state` event) so
other open browser tabs stay in sync.

## Sample reference + capture images

The WSL install script and `python -m visinsp.services.cli seed` both
write a small set of synthetic images to:

* `data/references/reference_good.png` — clean part
* `data/references/reference_defect.png` — part with a missing rivet
* `data/samples/capture_00.png` ... `capture_04.png` — five
  slightly-noisy versions of the good part
* `data/samples/capture_defect_00.png` — a noisy version of the
  defective part

The synthetic generator is deterministic (seeded) so test runs are
reproducible. Re-run `python -m visinsp.services.cli seed` any time to
regenerate the files.

## End-to-end demo in WSL

A 30-second demo of the full flow:

1. Open the UI at <http://localhost:5000>.
2. **References → Capture & add reference** from `cam_0` (the
   sample-image backend). You'll be redirected to the editor.
3. In the editor, click **+ Add box** and draw one or two boxes on
   the part. Save.
4. **Jobs → New**: pick the new reference, camera `cam_0`, threshold
   `0.80`. Add an action: GPIO → pin `alert_lamp` mode `HIGH`. Save.
5. **Triggers → New**: pin `trigger_1` (mock input), job from step 4,
   edge `falling`. Save.
6. **Dashboard** (or **Triggers → Fire now**) — click **Toggle** on
   `trigger_1` in the pin state card. The daemon runs the job, scores
   the image, and (if it fails) fires the GPIO action, plays a beep,
   flashes the screen, and shows a toast.
7. **Alerts**: dismiss the alert with **False positive** and watch
   the threshold for the next run nudge up by the step size (default
   0.005).

## Troubleshooting

* **Pin toggle doesn't seem to do anything.** Check the daemon is
  running (`./scripts/run.sh`) and watch the logs in
  `data/visinsp.log`. If the toggle fires but the alert doesn't
  appear, the job may be disabled or the reference may have no
  bounding boxes.
* **`/api/pins/<id>/toggle` returns 400.** That endpoint only works
  on the mock backend. On a real Pi it will say
  `backend_does_not_support_toggle`.
* **No cameras are detected and the sample fallback isn't kicking
  in.** Confirm `camera.wsl_sample_fallback: true` is in your
  config, and that `data/samples/` contains at least one `.jpg` /
  `.png` file. Re-run `python -m visinsp.services.cli seed`.
* **The Carbon CSS isn't loading.** Check your browser's dev tools
  for failed requests to `1.www.s81c.com` / `cdn.socket.io` — those
  are CDN dependencies. The UI degrades gracefully (plain text) if
  they fail, but layout will look unstyled.
