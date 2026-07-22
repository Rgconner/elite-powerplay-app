# image-updater — auto-roll controller for the elite-powerplay-app stack

A small in-cluster Python controller that watches **GitHub Container Registry**
(`ghcr.io`) for new image tags and patches the two Kubernetes Deployments
(`backend` and `frontend`) to roll forward.

It is intentionally minimal: no GitOps framework, no CRDs, no
operator-sdk — just a 200-line Python loop with a namespace-scoped
ServiceAccount.  The whole point is to remove the manual `kubectl set
image` step after every CI run.

## Why not just use `:latest`?

We tried that.  The problem is timing: if the backend gets a new image
first, the new API contract is live before the frontend's UI catches up
— and vice versa.  Pinning to `sha-<short>` tags also gives us a real
audit trail (`kubectl rollout history` shows the exact git SHA that
each pod ran).

## How it works

```
┌──────────────────────────────────────────────────────────────┐
│  elite-powerplay namespace                                   │
│                                                              │
│  ┌─────────────────────┐   every 60s                          │
│  │ image-updater pod   │ ◀──── ghcr.io /tags/list (anonymous) │
│  │                     │                                       │
│  │ compare current SHA │   if drift detected:                  │
│  │ vs latest SHA tag   │                                       │
│  │                     │   1. patch backend Deployment         │
│  │                     │   2. wait for rollout complete        │
│  │                     │   3. GET /api/admin/version until it  │
│  │                     │      returns the OCI label version    │
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
   `backend_version` field matches the `org.opencontainers.image.version`
   label on the new image (read from the ghcr.io manifest).
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
`BACKEND_RELEASE_DATE` from `backend/version.py` and `FRONTEND_VERSION`
from the `.version` file at the repo root, then passes them to the
Dockerfiles as build-args.  Each Dockerfile stamps them as OCI image
labels:

```dockerfile
LABEL org.opencontainers.image.version="${BACKEND_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BACKEND_RELEASE_DATE}"
```

The image-updater reads these labels via the ghcr.io `/v2/.../manifests/<tag>`
endpoint — no GitHub PAT required, anonymous token works for public repos.

## Deploying

```bash
# Build & push the controller image (CI does this on push to main):
docker buildx build --push \
    -t ghcr.io/rgconner/elite-powerplay-image-updater:latest \
    -f image-updater/Dockerfile image-updater/

# Apply to the cluster:
kubectl apply -f k8s/image-updater.yaml

# Or via kustomize (already added to kustomization.yaml):
kubectl apply -k k8s/
```

After apply, watch the log:

```bash
kubectl -n elite-powerplay logs -f deploy/image-updater
```

You should see something like:

```
image-updater starting: namespace=elite-powerplay registry=ghcr.io owner=rgconner poll=60s
backend already on sha-5483e57 — no action
frontend already on sha-5483e57 — no action
```

When a new SHA is pushed, you'll see:

```
Rolling backend ghcr.io/.../backend:latest -> sha-a1b2c3d
Patched Deployment/backend container=backend image=ghcr.io/.../sha-a1b2c3d
Rollout complete: Deployment/backend ready_replicas=1 available_replicas=1
Version gate: waiting for backend http://backend.elite-powerplay.svc.cluster.local:8000/api/admin/version to report version=1.9.0
Version gate passed: backend serving 1.9.0 ✓
Rolling frontend ghcr.io/.../frontend:latest -> sha-a1b2c3d
Patched Deployment/frontend container=frontend image=ghcr.io/.../sha-a1b2c3d
Rollout complete: Deployment/frontend ready_replicas=1 available_replicas=1
Reconcile pass complete: updated ['backend=sha-a1b2c3d', 'frontend=sha-a1b2c3d']
```

## Configuration

All knobs live in the `image-updater-config` ConfigMap (see
`k8s/image-updater.yaml`):

| Env var                          | Default                                       | Purpose                                                                |
|----------------------------------|-----------------------------------------------|------------------------------------------------------------------------|
| `OWNER`                          | `rgconner`                                    | ghcr.io org / user                                                    |
| `REGISTRY`                       | `ghcr.io`                                     | OCI registry                                                           |
| `NAMESPACE`                      | `elite-powerplay`                             | k8s namespace the controller runs in / manages                        |
| `POLL_INTERVAL_SECONDS`          | `60`                                          | How often to check for new SHAs                                        |
| `ROLLOUT_TIMEOUT_SECONDS`        | `300`                                         | Max time to wait for a Deployment rollout                              |
| `VERSION_POLL_INTERVAL_SECONDS`  | `5`                                           | How often to poll `/api/admin/version` during the gate                |
| `VERSION_POLL_TIMEOUT_SECONDS`   | `300`                                         | Max time to wait for the backend version gate                         |
| `BACKEND_SERVICE_URL`            | `http://backend.elite-powerplay.svc.cluster.local` | In-cluster URL of the backend service                             |
| `BACKEND_SERVICE_PORT`           | `8000`                                        | Backend port                                                          |
| `LOG_LEVEL`                      | `INFO`                                        | `DEBUG` for verbose reconcile output                                   |

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
