# ── Stage 1: build ───────────────────────────────────────────────────────────
FROM node:22-alpine AS build

# Build-time args for OCI image labels.  Set by the docker-publish workflow.
ARG FRONTEND_VERSION=unknown
ARG VCS_REF=unknown
ARG FRONTEND_BUILD_DATE=unknown

WORKDIR /app

# Install dependencies first (cached layer).
# Use 'npm ci' when a lockfile is present (reproducible, faster),
# fall back to 'npm install' otherwise so the first build doesn't fail
# before the lockfile has been committed to the repo.
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# Copy source and build
COPY . .
RUN npm run build

# ── Stage 2: serve ───────────────────────────────────────────────────────────
FROM nginx:1.27-alpine

# OCI image labels — purely informational for the frontend (the version
# gate only checks the backend); useful for `docker inspect` traceability.
ARG FRONTEND_VERSION=unknown
ARG VCS_REF=unknown
ARG FRONTEND_BUILD_DATE=unknown
LABEL org.opencontainers.image.title="elite-powerplay-frontend" \
      org.opencontainers.image.description="Elite Dangerous Power Play Analyzer — Vite + Nginx SPA" \
      org.opencontainers.image.source="https://github.com/Rgconner/elite-powerplay-app" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${FRONTEND_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${FRONTEND_BUILD_DATE}"

# Replace default nginx config with our SPA + proxy config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy the Vite build output
COPY --from=build /app/dist /usr/share/nginx/html

# Write a /version.json endpoint that the controller and humans can read
# to confirm which frontend build is live.  Nginx serves this as a static
# file at /version.json.  Useful as a debugging aid and for future
# frontend-side version-gate checks.
RUN printf '{"frontend_version":"%s","revision":"%s","build_date":"%s"}\n' \
        "${FRONTEND_VERSION}" "${VCS_REF}" "${FRONTEND_BUILD_DATE}" \
        > /usr/share/nginx/html/version.json

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
