# ─────────────────────────────────────────────────────────────────────────────
# image-updater Dockerfile
#
# Multi-stage build kept deliberately small:
#   • builder   — installs dependencies into a venv
#   • runtime   — copies the venv + source, runs as non-root
#
# Image is published to ghcr.io/<owner>/elite-powerplay-image-updater
# and is consumed by the k8s Deployment in k8s/image-updater.yaml.
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# Install dependencies into a venv so the runtime image can copy just
# the site-packages over without dragging pip / setuptools along.
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.13-slim

# Run as a dedicated non-root user.
RUN groupadd --system --gid 1001 imageupdater \
    && useradd  --system --uid 1001 --gid imageupdater --home-dir /app --shell /sbin/nologin imageupdater

WORKDIR /app

# Copy venv from builder.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Copy source.
COPY main.py ./

USER imageupdater

# Liveness / readiness — the controller exposes no HTTP port today, so we
# rely on the k8s API being able to read the Pod.  Future versions may
# expose /metrics on 9100 for Prometheus.
EXPOSE 9100

ENTRYPOINT ["python", "main.py"]
