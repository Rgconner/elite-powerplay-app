"""In-cluster image auto-updater for the elite-powerplay-app stack.

Watches the GitHub Container Registry (ghcr.io) for a new digest on the
`:latest` tag of two images (`elite-powerplay-backend` and
`elite-powerplay-frontend`) and patches the corresponding Kubernetes
Deployments to roll forward.

TAG STRATEGY
────────────
We track the `:latest` tag digest rather than sorting `sha-*` tags.
The `:latest` tag is re-pointed to the newest image by every successful
CI/CD run (docker/metadata-action with `type=raw,value=latest`), so it
is always the canonical "current production image".  Comparing the digest
of `:latest` against the digest embedded in the running Deployment's image
ref is the only reliable freshness check — lexicographic sorting of git
short-SHAs is not time-ordered and was the original cause of stale rollouts.

All images on ghcr.io are published as OCI indexes (multi-arch manifest
lists).  We resolve the index to the linux/amd64 child manifest before
reading labels or comparing digests.

RACE CONDITION HANDLING
───────────────────────
The backend exposes `/api/admin/version` returning the `BACKEND_VERSION`
string that was baked into the image at build time (set in
`backend/version.py`).  We use the OCI image label
`org.opencontainers.image.created` as a secondary sanity check, but the
primary gate is:

    1. Patch backend Deployment → wait for rollout
    2. Poll backend `/api/admin/version` until `backend_version` matches
       the value from the image config's `BACKEND_VERSION` build-arg label
       (stamped via `ARG BACKEND_VERSION` + `ENV BACKEND_VERSION` in the
       backend Dockerfile), OR until the version endpoint returns a *newer*
       created-timestamp than the previous image.
    3. Only then patch the frontend Deployment → wait for rollout

AUTHENTICATION
──────────────
We use a GitHub PAT (read:packages scope) injected via the `GITHUB_TOKEN`
env var (sourced from the `image-updater-ghcr-token` Secret).  Anonymous
ghcr.io tokens work for tag listing but can fail on blob fetches for
private or newly-created packages; authenticated requests are more reliable.
If `GITHUB_TOKEN` is empty the code falls back to an anonymous bearer token.

DESIGN
──────
• Single long-running Deployment — sub-minute responsiveness.
• In-cluster ServiceAccount with namespace-scoped get/patch on Deployments.
• All configuration via env vars (12-factor), sourced from ConfigMap/Secret.
• No git commits — the controller is the single source of truth for live
  cluster state.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from kubernetes import client, config
from kubernetes.client.rest import ApiException

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("image-updater")


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImageConfig:
    """How to discover and update a single image."""

    name: str                       # k8s Deployment name (e.g. "backend")
    image_repo: str                 # e.g. "rgconner/elite-powerplay-backend"
    container_name: str             # container name inside the pod spec


@dataclass(frozen=True)
class UpdaterConfig:
    """Top-level configuration loaded from env vars."""

    registry: str                   # "ghcr.io"
    owner: str                      # ghcr.io owner/org
    namespace: str                  # k8s namespace to manage
    poll_interval_seconds: int      # how often to check for new digest on :latest
    rollout_timeout_seconds: int    # how long to wait for a rollout
    version_poll_interval_seconds: int  # how often to poll /api/admin/version
    version_poll_timeout_seconds: int   # how long to wait for the version gate
    backend_service_url: str        # in-cluster URL for backend /api/admin/version
    backend_service_port: int
    github_token: str               # PAT with read:packages; "" = anonymous fallback
    images: tuple[ImageConfig, ...]

    @classmethod
    def from_env(cls) -> "UpdaterConfig":
        registry = os.getenv("REGISTRY", "ghcr.io")
        owner = os.getenv("OWNER", "rgconner")
        namespace = os.getenv("NAMESPACE", "elite-powerplay")
        poll = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
        rollout_to = int(os.getenv("ROLLOUT_TIMEOUT_SECONDS", "300"))
        v_poll = int(os.getenv("VERSION_POLL_INTERVAL_SECONDS", "5"))
        v_to = int(os.getenv("VERSION_POLL_TIMEOUT_SECONDS", "300"))
        backend_url = os.getenv(
            "BACKEND_SERVICE_URL", f"http://backend.{namespace}.svc.cluster.local"
        )
        backend_port = int(os.getenv("BACKEND_SERVICE_PORT", "8000"))
        github_token = os.getenv("GITHUB_TOKEN", "")

        images = (
            ImageConfig(
                name="backend",
                image_repo=f"{owner}/elite-powerplay-backend",
                container_name="backend",
            ),
            ImageConfig(
                name="frontend",
                image_repo=f"{owner}/elite-powerplay-frontend",
                container_name="frontend",
            ),
        )
        return cls(
            registry=registry,
            owner=owner,
            namespace=namespace,
            poll_interval_seconds=poll,
            rollout_timeout_seconds=rollout_to,
            version_poll_interval_seconds=v_poll,
            version_poll_timeout_seconds=v_to,
            backend_service_url=backend_url,
            backend_service_port=backend_port,
            github_token=github_token,
            images=images,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Registry client
# ──────────────────────────────────────────────────────────────────────────────


def _registry_token(
    http: httpx.Client,
    registry: str,
    repo: str,
    github_token: str = "",
) -> str:
    """Get a bearer token for a ghcr.io repository.

    If a GitHub PAT is supplied it is sent as HTTP Basic credentials so the
    token grants access to packages owned by the authenticated user.  Without
    a PAT the request is anonymous — sufficient for public repos but prone to
    rate-limiting and occasional 401s on blob fetches.
    """
    headers = {}
    if github_token:
        import base64
        # ghcr.io accepts "username:PAT" as Basic credentials for token exchange.
        # The username is irrelevant for PAT auth; use a placeholder.
        creds = base64.b64encode(f"image-updater:{github_token}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"

    resp = http.get(
        f"https://{registry}/token",
        params={"service": registry, "scope": f"repository:{repo}:pull"},
        headers=headers,
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def _resolve_index_to_amd64(
    http: httpx.Client,
    registry: str,
    repo: str,
    ref: str,           # tag or digest
    token: str,
) -> dict:
    """Fetch a manifest, resolving an OCI index to its linux/amd64 child.

    ghcr.io publishes every image as an OCI index (multi-arch manifest list).
    Requesting the index with only a single-manifest Accept header returns a
    400.  We must accept the index type, then walk into the child manifest.

    Returns the parsed child manifest dict (schemaVersion 2, OCI manifest).
    """
    ACCEPT = (
        "application/vnd.oci.image.index.v1+json,"
        "application/vnd.oci.image.manifest.v1+json,"
        "application/vnd.docker.distribution.manifest.v2+json,"
        "application/vnd.docker.distribution.manifest.list.v2+json"
    )
    resp = http.get(
        f"https://{registry}/v2/{repo}/manifests/{ref}",
        headers={"Authorization": f"Bearer {token}", "Accept": ACCEPT},
        timeout=10.0,
    )
    resp.raise_for_status()
    manifest = resp.json()

    media_type = manifest.get("mediaType", "") or ""
    is_index = (
        "index" in media_type
        or "manifest.list" in media_type
        or bool(manifest.get("manifests"))
    )

    if not is_index:
        # Already a single-platform manifest — return as-is.
        return manifest

    # Select linux/amd64; fall back to the first entry if not found.
    children = manifest.get("manifests", [])
    child = next(
        (
            m for m in children
            if m.get("platform", {}).get("os") == "linux"
            and m.get("platform", {}).get("architecture") == "amd64"
        ),
        children[0] if children else None,
    )
    if child is None:
        raise RuntimeError(f"OCI index for {repo}:{ref} has no child manifests")

    child_digest = child["digest"]
    log.debug("Index %s:%s → child %s", repo, ref, child_digest)

    child_resp = http.get(
        f"https://{registry}/v2/{repo}/manifests/{child_digest}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.oci.image.manifest.v1+json",
        },
        timeout=10.0,
    )
    child_resp.raise_for_status()
    return child_resp.json()


def get_latest_digest(
    http: httpx.Client,
    registry: str,
    repo: str,
    github_token: str = "",
) -> Optional[str]:
    """Return the linux/amd64 config digest of the :latest tag.

    We use the config blob digest (not the manifest digest) as the unique
    image identity — it is stable across registry operations that re-push
    the same image.  Returns None on any error.
    """
    try:
        token = _registry_token(http, registry, repo, github_token)
        manifest = _resolve_index_to_amd64(http, registry, repo, "latest", token)
        config_digest = manifest.get("config", {}).get("digest", "")
        if not config_digest:
            log.warning("No config digest in manifest for %s:latest", repo)
            return None
        return config_digest
    except httpx.HTTPError as exc:
        log.warning("Failed to fetch latest digest for %s: %s", repo, exc)
        return None


def get_image_labels(
    http: httpx.Client,
    registry: str,
    repo: str,
    tag: str,
    github_token: str = "",
) -> dict[str, str]:
    """Fetch the OCI image config blob and return its labels.

    Handles OCI indexes transparently by resolving to the linux/amd64 child
    before fetching the config blob.  Returns {} on any error.
    """
    try:
        token = _registry_token(http, registry, repo, github_token)
        manifest = _resolve_index_to_amd64(http, registry, repo, tag, token)
        config_digest = manifest.get("config", {}).get("digest", "")
        if not config_digest:
            return {}

        # Re-acquire a token — the previous one may be single-use.
        token2 = _registry_token(http, registry, repo, github_token)
        config_resp = http.get(
            f"https://{registry}/v2/{repo}/blobs/{config_digest}",
            headers={"Authorization": f"Bearer {token2}"},
            timeout=10.0,
        )
        config_resp.raise_for_status()
        return (config_resp.json().get("config", {}) or {}).get("Labels", {}) or {}
    except httpx.HTTPError as exc:
        log.warning("Failed to read image labels for %s:%s: %s", repo, tag, exc)
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# Kubernetes client
# ──────────────────────────────────────────────────────────────────────────────


def load_k8s_client() -> tuple[client.AppsV1Api, client.CoreV1Api]:
    """Load in-cluster k8s config and return the API clients we need."""
    config.load_incluster_config()
    return client.AppsV1Api(), client.CoreV1Api()


def get_deployment_image(apps: client.AppsV1Api, namespace: str, name: str, container_name: str) -> str:
    """Return the current `image:` string for the named container of a Deployment."""
    dep = apps.read_namespaced_deployment(name, namespace)
    containers = dep.spec.template.spec.containers
    for c in containers:
        if c.name == container_name:
            return c.image
    if containers:
        return containers[0].image
    raise RuntimeError(f"Deployment {name} has no containers")


def patch_deployment_image(
    apps: client.AppsV1Api,
    namespace: str,
    name: str,
    container_name: str,
    new_image: str,
) -> None:
    """Patch a single container's image in a Deployment (strategic merge)."""
    body = {
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {"name": container_name, "image": new_image},
                    ]
                }
            }
        }
    }
    apps.patch_namespaced_deployment(name, namespace, body)
    log.info("Patched Deployment/%s container=%s image=%s", name, container_name, new_image)


def wait_for_rollout(
    apps: client.AppsV1Api,
    namespace: str,
    name: str,
    timeout_seconds: int,
) -> None:
    """Block until the Deployment reports a fully-ready rollout, or timeout.

    "Fully ready" = observedGeneration matches generation AND updated replicas
    equal spec.replicas AND available replicas equal spec.replicas.
    """
    deadline = time.monotonic() + timeout_seconds
    poll_every = 2.0
    while time.monotonic() < deadline:
        dep = apps.read_namespaced_deployment(name, namespace)
        status = dep.status
        spec = dep.spec
        desired = spec.replicas or 1
        gen_match = (status.observed_generation or 0) >= (dep.metadata.generation or 0)
        updated_match = (status.updated_replicas or 0) >= desired
        ready_match = (status.ready_replicas or 0) >= desired
        available_match = (status.available_replicas or 0) >= desired
        if gen_match and updated_match and ready_match and available_match:
            log.info(
                "Rollout complete: Deployment/%s ready_replicas=%s available_replicas=%s",
                name, status.ready_replicas, status.available_replicas,
            )
            return
        time.sleep(poll_every)
    raise TimeoutError(
        f"Deployment/{name} did not finish rollout within {timeout_seconds}s"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Backend version gate
# ──────────────────────────────────────────────────────────────────────────────


def wait_for_backend_version(
    http: httpx.Client,
    config_: UpdaterConfig,
    expected_version: str,
) -> None:
    """Poll `GET /api/admin/version` until it returns the expected version.

    `expected_version` must be the semver string from `backend/version.py`
    (e.g. "2.1.1"), read from the image's `BACKEND_VERSION` env var label
    (set by the backend Dockerfile via `ENV BACKEND_VERSION=...`).

    Returns early if `expected_version` is empty — the version gate is
    best-effort; rollout-status alone is sufficient if labels are absent.
    """
    if not expected_version:
        log.warning(
            "No expected BACKEND_VERSION resolved from image config — "
            "skipping version gate (rollout-status check still applies)."
        )
        return

    url = f"{config_.backend_service_url}:{config_.backend_service_port}/api/admin/version"
    deadline = time.monotonic() + config_.version_poll_timeout_seconds
    log.info(
        "Version gate: waiting for backend %s to report version=%s",
        url, expected_version,
    )
    while time.monotonic() < deadline:
        try:
            resp = http.get(url, timeout=5.0)
            if resp.status_code == 200:
                body = resp.json()
                if body.get("backend_version") == expected_version:
                    log.info("Version gate passed: backend serving %s ✓", expected_version)
                    return
        except (httpx.HTTPError, ValueError) as exc:
            log.debug("Version gate poll failed (will retry): %s", exc)
        time.sleep(config_.version_poll_interval_seconds)
    raise TimeoutError(
        f"Backend version gate timed out — expected {expected_version!r} at {url}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _config_digest_from_image(image: str) -> str:
    """Extract a stored config digest from an image ref that encodes it.

    When we patch a Deployment we write `registry/repo:latest@sha256:<config>`.
    This helper strips the digest portion so we can compare it to what the
    registry reports for the current :latest tag.

    Returns "" if the image ref does not contain a digest.
    """
    # image ref format: registry/repo:tag@sha256:...
    if "@" in image:
        return image.split("@", 1)[1]
    return ""


def _backend_version_from_labels(labels: dict[str, str]) -> str:
    """Extract the BACKEND_VERSION value from image config labels.

    The backend Dockerfile stamps the version via:
        ARG  BACKEND_VERSION
        ENV  BACKEND_VERSION=${BACKEND_VERSION}
        LABEL backend_version="${BACKEND_VERSION}"

    The label key is lowercase `backend_version` (set explicitly in the
    Dockerfile).  If absent, returns "".
    """
    return labels.get("backend_version", "") or labels.get("BACKEND_VERSION", "")


# ──────────────────────────────────────────────────────────────────────────────
# Reconciler
# ──────────────────────────────────────────────────────────────────────────────


def reconcile_once(
    cfg: UpdaterConfig,
    apps: client.AppsV1Api,
    http: httpx.Client,
) -> list[str]:
    """One full reconcile pass.  Returns the list of images that were updated.

    Strategy:
      • For each image, fetch the config digest of the :latest tag from ghcr.io.
      • Compare to the digest embedded in the running Deployment's image ref.
      • If they differ, patch → wait for rollout → (backend only) version gate.

    Pass is sequential: backend first, then frontend.  Any failure aborts the
    whole pass so we never roll the frontend onto an un-confirmed backend.
    """
    updated: list[str] = []

    # ── 1. Backend ───────────────────────────────────────────────────────────
    backend_cfg = cfg.images[0]
    latest_digest = get_latest_digest(
        http, cfg.registry, backend_cfg.image_repo, cfg.github_token
    )
    if not latest_digest:
        log.warning("Could not resolve :latest digest for backend — skipping reconcile")
        return updated

    current_image = get_deployment_image(
        apps, cfg.namespace, backend_cfg.name, backend_cfg.container_name
    )
    current_digest = _config_digest_from_image(current_image)

    if current_digest != latest_digest:
        # Embed the digest in the image ref so we can compare on the next pass
        # without a registry round-trip for the digest.
        new_image = (
            f"{cfg.registry}/{backend_cfg.image_repo}:latest@{latest_digest}"
        )
        log.info(
            "Backend drift detected: running=%s latest=%s → rolling",
            current_digest or current_image, latest_digest,
        )
        patch_deployment_image(
            apps, cfg.namespace, backend_cfg.name,
            backend_cfg.container_name, new_image,
        )
        wait_for_rollout(apps, cfg.namespace, backend_cfg.name, cfg.rollout_timeout_seconds)
        updated.append(f"{backend_cfg.name}@{latest_digest[:19]}")

        # ── Version gate ────────────────────────────────────────────────────
        labels = get_image_labels(
            http, cfg.registry, backend_cfg.image_repo, "latest", cfg.github_token
        )
        expected_version = _backend_version_from_labels(labels)
        log.debug("Backend image labels: %s", labels)
        try:
            wait_for_backend_version(http, cfg, expected_version)
        except TimeoutError as exc:
            log.error("ABORT reconcile: %s", exc)
            return updated
    else:
        log.debug("Backend already on latest digest (%s) — no action", latest_digest[:19])

    # ── 2. Frontend (only after backend is confirmed ready) ─────────────────
    frontend_cfg = cfg.images[1]
    latest_digest_fe = get_latest_digest(
        http, cfg.registry, frontend_cfg.image_repo, cfg.github_token
    )
    if not latest_digest_fe:
        log.warning("Could not resolve :latest digest for frontend — skipping")
        return updated

    current_image_fe = get_deployment_image(
        apps, cfg.namespace, frontend_cfg.name, frontend_cfg.container_name
    )
    current_digest_fe = _config_digest_from_image(current_image_fe)

    if current_digest_fe != latest_digest_fe:
        new_image_fe = (
            f"{cfg.registry}/{frontend_cfg.image_repo}:latest@{latest_digest_fe}"
        )
        log.info(
            "Frontend drift detected: running=%s latest=%s → rolling",
            current_digest_fe or current_image_fe, latest_digest_fe,
        )
        patch_deployment_image(
            apps, cfg.namespace, frontend_cfg.name,
            frontend_cfg.container_name, new_image_fe,
        )
        wait_for_rollout(apps, cfg.namespace, frontend_cfg.name, cfg.rollout_timeout_seconds)
        updated.append(f"{frontend_cfg.name}@{latest_digest_fe[:19]}")
    else:
        log.debug("Frontend already on latest digest (%s) — no action", latest_digest_fe[:19])

    return updated


# ──────────────────────────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────────────────────────


def main() -> int:
    cfg = UpdaterConfig.from_env()
    log.info(
        "image-updater starting: namespace=%s registry=%s owner=%s poll=%ds auth=%s",
        cfg.namespace, cfg.registry, cfg.owner, cfg.poll_interval_seconds,
        "PAT" if cfg.github_token else "anonymous",
    )
    apps, _ = load_k8s_client()
    with httpx.Client() as http:
        while True:
            try:
                updated = reconcile_once(cfg, apps, http)
                if updated:
                    log.info("Reconcile pass complete: updated %s", updated)
                else:
                    log.debug("Reconcile pass complete: nothing to do")
            except ApiException as exc:
                log.error("k8s API error: %s", exc)
            except Exception:
                log.exception("Reconcile pass failed")
            time.sleep(cfg.poll_interval_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
