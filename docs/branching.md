# Branching

Visual Inspector uses a small, deliberate branch model:

```
main              platform-agnostic core — all feature work lands here
├── pi            Pi release branch (RPi.GPIO dep, Pi config, install script)
└── wsl           WSL release branch (mock GPIO, sample data, no RPi dep)
```

## Why this shape

* **One trunk, two thin release branches.** The application code lives
  on `main`. The two release branches are mostly empty — they only
  carry the platform-specific config preset, the matching
  `requirements-*.txt`, and the install scripts that target that
  environment. This avoids the "two diverging codebases" problem
  while still giving each environment a clean checkout command.
* **A single command per environment.** On the Pi you do
  `git checkout pi && ./scripts/install-pi.sh`; on WSL,
  `git checkout wsl && ./scripts/install-wsl.sh`. You never need to
  remember which Python deps to install or which config file to copy.

## Day-to-day workflow

### On WSL (most of the work)

```bash
git checkout main
# ... edit code, run tests, run the app in mock mode ...
git commit -m "Add a new feature"
git push origin main
```

### On a Pi (deploy)

```bash
git fetch
git checkout main
git merge origin/main          # optional: fold in latest
git checkout pi                # thin release branch
git merge --ff-only main        # bring the new code in
./scripts/install-pi.sh        # re-run if deps changed
./scripts/run.sh
```

If a Pi-specific config or install change is needed, edit on `pi`,
commit, and push from the Pi. The CI on `main` doesn't run on `pi`
or `wsl` today (the unit test suite is the same on both), but you
can add it later.

## What lives where

| Path                                    | `main` | `pi` | `wsl` |
| --------------------------------------- | :----: | :--: | :---: |
| `src/visinsp/**`                        | ✓      |      |       |
| `tests/**`                              | ✓      |      |       |
| `docs/**`                               | ✓      |      |       |
| `config/config.example.json`            | ✓      |      |       |
| `scripts/run.sh`, `seed-sample-data.py` | ✓      |      |       |
| `pyproject.toml`, `requirements.txt`    | ✓      |      |       |
| `requirements-dev.txt`                  | ✓      |      |       |
| `config/config.pi.json`                 |        |  ✓   |       |
| `scripts/install-pi.sh`                 |        |  ✓   |       |
| `systemd/visinsp.service`               |        |  ✓   |       |
| `requirements-pi.txt`                   |        |  ✓   |       |
| `config/config.wsl.json`                |        |      |  ✓    |
| `scripts/install-wsl.sh`                |        |      |  ✓    |
| `requirements-wsl.txt`                  |        |      |  ✓    |

The install / run scripts on `main` auto-detect the platform if
`VISINSP_ENV=auto`, so they work on both Pi and WSL. The per-env
presets just choose a different default config + the right
requirements file.
