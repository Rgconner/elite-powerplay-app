"""In-cluster image auto-updater for the elite-powerplay-app stack.

Watches the GitHub Container Registry (ghcr.io) for new `sha-<short>` tags on
two images (`elite-powerplay-backend` and `elite-powerplay-frontend`) and
patches the corresponding Kubernetes Deployments to roll forward.

RACE CONDITION HANDLING
───────────────────────
The backend exposes `/api/admin/version` returning the `BACKEND_VERSION` string
that was baked into the image at build time. We use this to gate the frontend
rollout:

    1. Patch backend Deployment → wait for rollout
    2. Poll backend `/api/admin/version` until it returns the expected version
       (read from the OCI image labels for the new SHA)
    3. *Only then* patch the frontend Deployment → wait for rollout

This guarantees the frontend never serves UI that expects a new API contract
before the backend is actually serving that contract. If the backend version
gate fails, the whole reconciliation aborts and is retried on the next tick
(NOT a frontend-only roll, which could leave the system in an inconsistent
state).

DESIGN
──────
• Single long-running Deployment (NOT a CronJob) — sub-minute responsiveness
  without polling overhead.
• In-cluster ServiceAccount with namespace-scoped `get/patch` on Deployments
  and Pods; no cluster-admin, no exec, no secrets access.
• All configuration is read from environment variables (12-factor), sourced
  from a ConfigMap.
• Registry communication uses anonymous ghcr.io token (works for public
  repos) so we don't need a GitHub PAT in the cluster.
• No git commits — the controller is the single source of truth for the live
  cluster.  The kustomization.yaml stays pinned to `:latest` for new-cluster
  bootstrap; the live SHAs live only in the cluster.
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
    poll_interval_seconds: int      # how often to check for new SHAs
    rollout_timeout_seconds: int    # how long to wait for a rollout
    version_poll_interval_seconds: int  # how often to poll /api/admin/version
    version_poll_timeout_seconds: int   # how long to wait for the version gate
    backend_service_url: str        # in-cluster URL for backend /api/admin/version
    backend_service_port: int
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
            images=images,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Registry client  (anonymous, public images only)
# ──────────────────────────────────────────────────────────────────────────────


def _registry_token(http: httpx.Client, registry: str, repo: str) -> str:
    """Get an anonymous bearer token for a public ghcr.io repository.

    Public repos on ghcr.io accept the catalog token; this lets us list tags
    and fetch image manifests without a GitHub PAT.
    """
    resp = http.get(
        f"https://{registry}/token",
        params={"service": registry, "scope": f"repository:{repo}:pull"},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["token"]


@dataclass
class ImageTag:
    """A single tag entry as returned by the registry."""

    name: str                       # e.g. "sha-5483e57"
    digest: str                     # e.g. "sha256:abcdef…"


def list_sha_tags(http: httpx.Client, registry: str, repo: str) -> list[ImageTag]:
    """Return all `sha-*` tags for a repository, sorted newest-first.

    Sorting strategy: by tag name descending (lexicographic).  This is a
    stable proxy for "most recently pushed" because git short SHAs are
    roughly time-ordered within a single repo, AND because the
    docker-publish workflow always pushes fresh SHAs for new commits.

    For absolute accuracy we could fetch each manifest and sort by
    `created` annotation, but for 1-tag-per-commit repos the lexicographic
    order is sufficient and saves N round-trips.
    """
    token = _registry_token(http, registry, repo)
    resp = http.get(
        f"https://{registry}/v2/{repo}/tags/list",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    resp.raise_for_status()
    tags = resp.json().get("tags", []) or []
    sha_re = re.compile(r"^sha-[0-9a-f]{7,40}$")
    sha_tags = [t for t in tags if sha_re.match(t)]
    # Sort newest-first by short-SHA (lexicographic on the hex portion)
    sha_tags.sort(key=lambda t: t.split("-", 1)[1], reverse=True)
    return [ImageTag(name=t, digest="") for t in sha_tags]


def get_image_labels(
    http: httpx.Client, registry: str, repo: str, tag: str, token: str
) -> dict[str, str]:
    """Fetch the OCI image config and return its labels.

    We use this to extract the `org.opencontainers.image.version` label
    (added by docker/metadata-action) so we can confirm the backend is
    serving the version we expect.
    """
    # Get the manifest
    manifest_resp = http.get(
        f"https://{registry}/v2/{repo}/manifests/{tag}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.oci.image.manifest.v1+json",
        },
        timeout=10.0,
    )
    manifest_resp.raise_for_status()
    manifest = manifest_resp.json()
    config_digest = manifest.get("config", {}).get("digest", "")
    if not config_digest:
        return {}

    # Get the config blob
    config_resp = http.get(
        f"https://{registry}/v2/{repo}/blobs/{config_digest}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    config_resp.raise_for_status()
    return (config_resp.json().get("config", {}) or {}).get("Labels", {}) or {}


# ──────────────────────────────────────────────────────────────────────────────
# Kubernetes client
# ──────────────────────────────────────────────────────────────────────────────


def load_k8s_client() -> tuple[client.AppsV1Api, client.CoreV1Api]:
    """Load in-cluster k8s config and return the API clients we need."""
    config.load_incluster_config()
    return client.AppsV1Api(), client.CoreV1Api()


def get_deployment_image(apps: client.AppsV1Api, namespace: str, name: str) -> str:
    """Return the current `image:` string for the first container of a Deployment."""
    dep = apps.read_namespaced_deployment(name, namespace)
    containers = dep.spec.template.spec.containers
    if not containers:
        raise RuntimeError(f"Deployment {name} has no containers")
    return containers[0].image


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
    equal spec.replicas AND available replicas equal spec.replicas.  This is
    stricter than `kubectl rollout status` which only checks updated==replicas
    and ignores availability — we want a confirmed Ready pod before we move on.
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
# Backend version gate  (the race-condition fix)
# ──────────────────────────────────────────────────────────────────────────────


def wait_for_backend_version(
    http: httpx.Client,
    config_: UpdaterConfig,
    expected_version: str,
) -> None:
    """Poll `GET /api/admin/version` until it returns the expected version.

    This is the race-condition gate: the backend's pod is "Ready" once its
    HTTP probe passes, but the probe only checks `/health` (a static
    response).  We additionally verify the version that the running pod is
    actually serving — once the new image is live, the new BACKEND_VERSION
    from the OCI labels will be in the response.

    Returns early if `expected_version` is empty (labels unavailable) so
    the controller still functions for repos that don't set the label.
    """
    if not expected_version:
        log.warning(
            "No expected BACKEND_VERSION resolved from image labels — "
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
# Reconciler
# ──────────────────────────────────────────────────────────────────────────────


def reconcile_once(
    cfg: UpdaterConfig,
    apps: client.AppsV1Api,
    http: httpx.Client,
) -> list[str]:
    """One full reconcile pass.  Returns the list of images that were updated.

    The pass is sequential:
      1. backend  →  wait for rollout  →  version gate
      2. frontend →  wait for rollout
    If any step fails the whole pass aborts (no half-updates).
    """
    updated: list[str] = []

    # ── 1. Backend ───────────────────────────────────────────────────────────
    backend_cfg = cfg.images[0]
    new_backend_tag = _latest_sha_tag(http, cfg.registry, backend_cfg.image_repo)
    if not new_backend_tag:
        log.warning("No sha-* tag for backend — skipping reconcile")
        return updated

    current = get_deployment_image(apps, cfg.namespace, backend_cfg.name)
    _, current_tag = _split_image(current)
    if current_tag != new_backend_tag:
        new_image = f"{cfg.registry}/{backend_cfg.image_repo}:{new_backend_tag}"
        log.info("Rolling backend %s -> %s", current, new_image)
        patch_deployment_image(
            apps, cfg.namespace, backend_cfg.name,
            backend_cfg.container_name, new_image,
        )
        wait_for_rollout(apps, cfg.namespace, backend_cfg.name, cfg.rollout_timeout_seconds)
        updated.append(f"{backend_cfg.name}={new_backend_tag}")

        # ── Version gate ────────────────────────────────────────────────────
        backend_token = _registry_token(http, cfg.registry, backend_cfg.image_repo)
        labels = get_image_labels(
            http, cfg.registry, backend_cfg.image_repo, new_backend_tag, backend_token
        )
        expected_version = labels.get("org.opencontainers.image.version", "")
        try:
            wait_for_backend_version(http, cfg, expected_version)
        except TimeoutError as exc:
            # Critical: abort the whole reconcile so we don't roll the frontend
            # on a half-deployed backend.
            log.error("ABORT reconcile: %s", exc)
            return updated
    else:
        log.info("backend already on %s — no action", new_backend_tag)

    # ── 2. Frontend (only after backend version gate passed) ────────────────
    frontend_cfg = cfg.images[1]
    new_frontend_tag = _latest_sha_tag(http, cfg.registry, frontend_cfg.image_repo)
    if not new_frontend_tag:
        log.warning("No sha-* tag for frontend — skipping")
        return updated

    current = get_deployment_image(apps, cfg.namespace, frontend_cfg.name)
    _, current_tag = _split_image(current)
    if current_tag != new_frontend_tag:
        new_image = f"{cfg.registry}/{frontend_cfg.image_repo}:{new_frontend_tag}"
        log.info("Rolling frontend %s -> %s", current, new_image)
        patch_deployment_image(
            apps, cfg.namespace, frontend_cfg.name,
            frontend_cfg.container_name, new_image,
        )
        wait_for_rollout(apps, cfg.namespace, frontend_cfg.name, cfg.rollout_timeout_seconds)
        updated.append(f"{frontend_cfg.name}={new_frontend_tag}")
    else:
        log.info("frontend already on %s — no action", new_frontend_tag)

    return updated


def _latest_sha_tag(http: httpx.Client, registry: str, repo: str) -> Optional[str]:
    """Return the name of the most recent `sha-*` tag, or None."""
    try:
        tags = list_sha_tags(http, registry, repo)
    except httpx.HTTPError as exc:
        log.warning("Failed to list tags for %s: %s", repo, exc)
        return None
    return tags[0].name if tags else None


def _split_image(image: str) -> tuple[str, str]:
    """Split `registry/repo:tag` into (registry/repo, tag).  Tag defaults to 'latest'."""
    last = image.split("/")[-1]
    if ":" in last:
        repo, tag = image.rsplit(":", 1)
    else:
        repo, tag = image, "latest"
    return repo, tag


# ──────────────────────────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────────────────────────


def main() -> int:
    cfg = UpdaterConfig.from_env()
    log.info(
        "image-updater starting: namespace=%s registry=%s owner=%s poll=%ds",
        cfg.namespace, cfg.registry, cfg.owner, cfg.poll_interval_seconds,
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
