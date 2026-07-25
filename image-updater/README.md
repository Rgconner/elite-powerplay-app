# image-updater — auto-roll controller for the elite-powerplay-app stack

A small in-cluster Python controller that watches **GitHub Container Registry**
(`ghcr.io`) for a new image digest on the `:latest` tag and patches the two
Kubernetes Deployments (`backend` and `frontend`) to roll forward.

It is intentionally minimal: no GitOps framework, no CRDs, no
operator-sdk — just a ~400-line Python loop with a namespace-scoped
ServiceAccount.  The whole point is to remove the manual `kubectl set
image` step after every CI run.

## Tag strategy — why `:latest` and not `sha-*`

The original implementation sorted `sha-*` tags lexicographically on the hex
portion of the short SHA.  This is **not** time-ordered — `sha-fd8e0b1` sorts
higher than `sha-3fca1e9` (f > 3) but was built months earlier.  The controller
was therefore permanently stuck rolling to an old image.

`:latest` is re-pointed to the newest image by every successful CI run via
`docker/metadata-action` (`type=raw,value=latest`).  It is the canonical
"current production image".  We compare the **config blob digest** of `:latest`
against the digest embedded in the running Deployment's image ref — a
byte-for-byte equality check that cannot be fooled by tag moves.

## How it works

```
┌──────────────────────────────────────────────────────────────┐
│  elite-powerplay namespace                                   │
│                                                              │
│  ┌─────────────────────┐   every 60s                          │
│  │ image-updater pod   │ ◀── ghcr.io :latest digest (PAT)    │
│  │                     │                                       │
│  │ compare config      │   if digest differs:                  │
│  │ digest vs running   │                                       │
│  │                     │   1. patch backend Deployment         │
│  │                     │   2. wait for rollout complete        │
│  │                     │   3. GET /api/admin/version until it  │
│  │                     │      returns the `backend_version`    │
│  │                     │      label value from the new image   │
│  │                     │   4. patch frontend Deployment        │
│  │                     │   5. wait for rollout complete        │
│  └─────────────────────┘                                       │
│         │                                                     │
│         │ ServiceAccount: image-updater                       │
│         │   verbs: get,list,watch,patch  (Deployments, Pods) │
│         │   resourceNames: backend, frontend  (least-priv.)  │
└──────────────────────────────────────────────────────────────┘
```

### Race-condition handling

The user-visible problem: if the backend rolls to a new version with
breaking API changes, the frontend **must not** be allowed to update
to the new UI (which calls the new API) until the backend is actually
serving the new API.  Otherwise users see JS errors and broken pages
for 30-60 s during the rollout.

The fix is a version gate:

1. **Roll the backend** to the new image.
2. **Wait for rollout status**: `observed_generation == generation`,
   `updated_replicas == replicas`, `available_replicas == replicas`.
3. **Confirm the new version is live**: poll
   `GET http://backend:8000/api/admin/version` until the
   `backend_version` field matches the `backend_version` **label** on
   the new image (read from the ghcr.io config blob).  Note: this label
   is distinct from `org.opencontainers.image.version`, which is always
   overwritten to `"main"` by `docker/metadata-action`.
4. **Only then** roll the frontend.

If any step times out, the **whole reconcile aborts** and is retried
on the next 60-s tick.  We never roll just the frontend on its own
in the same pass — that would be the half-deployed state we're
trying to avoid.

## Files

| Path                                  | Purpose                                                                 |
|---------------------------------------|-------------------------------------------------------------------------|
| `image-updater/main.py`               | The controller loop — registry client, k8s client, reconciler          |
| `image-updater/requirements.txt`      | Pinned Python deps (httpx, kubernetes)                                  |
| `image-updater/Dockerfile`            | Multi-stage build, runs as non-root                                     |
| `k8s/image-updater.yaml`              | ServiceAccount + Role + RoleBinding + ConfigMap + Deployment           |
| `k8s/kustomization.yaml`              | Adds the image-updater to the `resources:` list                        |
| `.github/workflows/docker-publish.yml`| Adds the third build job (`build-image-updater`) + OCI label args      |
| `backend/Dockerfile`                  | New `ARG`s + `LABEL org.opencontainers.image.version=…`                |
| `frontend/Dockerfile`                 | New `ARG`s + `LABEL`s + writes a static `/version.json` at build time  |

## Build-time version labels

The docker-publish workflow extracts `BACKEND_VERSION` and
`BACKEND_RELEASE_DATE` from `backend/version.py` and passes them to the
backend Dockerfile as build-args.  The Dockerfile stamps `BACKEND_VERSION`
as a custom `backend_version` label (lowercase, app-scoped):

```dockerfile
LABEL org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BACKEND_RELEASE_DATE}" \
      backend_version="${BACKEND_VERSION}"
```

**Why not `org.opencontainers.image.version`?**  `docker/metadata-action`
unconditionally overwrites that label with the branch name (`"main"`), so it
can never carry the semver string.  The `backend_version` label is set by the
`LABEL` instruction *before* the workflow's `labels:` input takes effect — but
since OCI annotations from `metadata-action` also use the same key, the custom
label is used instead.

The image-updater fetches labels via the ghcr.io v2 API using a PAT
(`GITHUB_TOKEN` env var from the `image-updater-ghcr-token` Secret).
Anonymous tokens work for tag listing but are unreliable for OCI index and
blob fetches; the PAT prevents rate-limiting errors.

## Deploying

```bash
# 1. Create the PAT secret (one-time, before first apply):
kubectl create secret generic image-updater-ghcr-token \
  --namespace elite-powerplay \
  --from-literal=GITHUB_TOKEN=<PAT-with-read:packages>

# 2. Build & push the controller image (CI does this on push to main):
docker buildx build --push \
    -t ghcr.io/rgconner/elite-powerplay-image-updater:latest \
    -f image-updater/Dockerfile image-updater/

# 3. Apply to the cluster:
kubectl apply -f k8s/base/image-updater.yaml

# Or via kustomize (already added to kustomization.yaml):
kubectl apply -k k8s/
```

After apply, watch the log:

```bash
kubectl -n elite-powerplay logs -f deploy/image-updater
```

You should see something like:

```
image-updater starting: namespace=elite-powerplay registry=ghcr.io owner=rgconner poll=60s auth=PAT
Backend already on latest digest (sha256:5f099e031d00d77b) — no action
Frontend already on latest digest (sha256:32a202dd20417b8b) — no action
```

When a new image is pushed to `:latest`, you'll see:

```
Backend drift detected: running=sha256:abc... latest=sha256:def... → rolling
Patched Deployment/backend container=backend image=ghcr.io/.../backend:latest@sha256:def...
Rollout complete: Deployment/backend ready_replicas=1 available_replicas=1
Version gate: waiting for backend http://...svc.cluster.local:8000/api/admin/version to report version=2.2.0
Version gate passed: backend serving 2.2.0 ✓
Frontend drift detected: running=sha256:abc... latest=sha256:fed... → rolling
Patched Deployment/frontend container=frontend image=ghcr.io/.../frontend:latest@sha256:fed...
Rollout complete: Deployment/frontend ready_replicas=1 available_replicas=1
Reconcile pass complete: updated ['backend@sha256:def...', 'frontend@sha256:fed...']
```

## Configuration

All knobs live in the `image-updater-config` ConfigMap (see
`k8s/image-updater.yaml`):

| Env var                          | Source        | Default                                       | Purpose                                                                |
|----------------------------------|---------------|-----------------------------------------------|------------------------------------------------------------------------|
| `OWNER`                          | ConfigMap     | `rgconner`                                    | ghcr.io org / user                                                    |
| `REGISTRY`                       | ConfigMap     | `ghcr.io`                                     | OCI registry                                                           |
| `NAMESPACE`                      | ConfigMap     | `elite-powerplay`                             | k8s namespace the controller runs in / manages                        |
| `POLL_INTERVAL_SECONDS`          | ConfigMap     | `60`                                          | How often to check `:latest` digest for drift                          |
| `ROLLOUT_TIMEOUT_SECONDS`        | ConfigMap     | `300`                                         | Max time to wait for a Deployment rollout                              |
| `VERSION_POLL_INTERVAL_SECONDS`  | ConfigMap     | `5`                                           | How often to poll `/api/admin/version` during the gate                |
| `VERSION_POLL_TIMEOUT_SECONDS`   | ConfigMap     | `300`                                         | Max time to wait for the backend version gate                         |
| `BACKEND_SERVICE_URL`            | ConfigMap     | `http://backend.elite-powerplay.svc.cluster.local` | In-cluster URL of the backend service                             |
| `BACKEND_SERVICE_PORT`           | ConfigMap     | `8000`                                        | Backend port                                                          |
| `LOG_LEVEL`                      | ConfigMap     | `INFO`                                        | `DEBUG` for verbose reconcile output                                   |
| `GITHUB_TOKEN`                   | **Secret**    | `""`                                          | PAT (`read:packages`) for authenticated ghcr.io token exchange        |

## Security model

The controller runs as a dedicated `ServiceAccount` with a tightly
scoped `Role`:

```yaml
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    resourceNames: [backend, frontend]    # ← only these two
    verbs: [get, list, watch, patch]
  - apiGroups: [""]
    resources: [pods]
    verbs: [get, list, watch]              # read-only
  - apiGroups: [""]
    resources: [events]
    verbs: [create, patch, update]         # for log correlation
```

No cluster-admin.  No secrets.  No ConfigMap writes.  No exec into
pods.  No node access.  If the controller's token leaks, the attacker
can only change the image of the two app deployments — they cannot
read the database password, the JWT signing key, or the AI API key.

## Manual override

To pin to a specific SHA outside the auto-updater (e.g. for testing):

```bash
kubectl set image deploy/backend  backend=ghcr.io/.../elite-powerplay-backend:sha-deadbeef -n elite-powerplay
kubectl set image deploy/frontend frontend=ghcr.io/.../elite-powerplay-frontend:sha-deadbeef -n elite-powerplay
```

The next reconcile pass will see these match the registry's `sha-deadbeef`
tag and will be a no-op.  If you pin to a SHA that the registry no
longer has, the controller will eventually try to roll forward to the
newest available SHA on the next drift — but only if the new SHA
actually exists in the registry.

To stop auto-updates entirely, scale the controller to zero:

```bash
kubectl scale deploy/image-updater --replicas=0 -n elite-powerplay
```

## What this isn't

- **Not a full GitOps pipeline.**  The cluster state diverges from git
  intentionally — the controller is the single source of truth for
  what images are running.  If you want a strict GitOps model, swap
  this for [Flux ImageUpdateAutomation][flux] or [Argo CD Image
  Updater][argo]; the version-gate pattern translates directly.

[flux]: https://fluxcd.io/flux/components/image/imagerepositories/
[argo]: https://argocd-image-updater.readthedocs.io/

## Future work

- **Metrics endpoint** on `:9100/metrics` for Prometheus scraping
  (reconciles_total, reconcile_duration_seconds, drift_detected_total).
- **Slack/Discord webhook** on failed version gates.
- **Rollback automation**: if a backend health check fails within
  5 min of a rollout, auto-rollback to the previous SHA.
- **Support for non-ghcr registries** (Docker Hub, ECR, GCR) via a
  per-image credential Secret.
