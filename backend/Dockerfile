FROM python:3.13-slim

# Build-time arguments.  These are injected by the docker-publish workflow:
#   BACKEND_VERSION      — read from backend/version.py
#   BACKEND_RELEASE_DATE — ISO 8601 release date from version.py
#   VCS_REF              — git SHA (also added by docker/metadata-action)
# They become OCI image labels that the image-updater reads to gate
# rollouts on the actual BACKEND_VERSION the running pod is serving.
ARG BACKEND_VERSION=unknown
ARG BACKEND_RELEASE_DATE=unknown
ARG VCS_REF=unknown

# Install OS packages needed by psycopg2, bcrypt, cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# OCI image labels — used by the in-cluster image-updater to confirm a
# new backend pod is actually serving the expected BACKEND_VERSION
# before the frontend is allowed to roll forward.
LABEL org.opencontainers.image.title="elite-powerplay-backend" \
      org.opencontainers.image.description="Elite Dangerous Power Play Analyzer — FastAPI backend" \
      org.opencontainers.image.source="https://github.com/Rgconner/elite-powerplay-app" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${BACKEND_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BACKEND_RELEASE_DATE}"

WORKDIR /app

# Install Python dependencies first so this layer is cached on code changes.
# Prefer the lockfile for byte-for-byte reproducibility in CI;
# fall back to requirements.txt (N-1 exact pins) so the first build
# doesn't fail before requirements.lock.txt has been generated.
COPY requirements.txt requirements.lock.txt* ./
RUN if [ -f requirements.lock.txt ]; then \
        pip install --no-cache-dir -r requirements.lock.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

# Copy application source
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
