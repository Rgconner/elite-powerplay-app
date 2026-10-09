# Build context is the repo root (see .github/workflows/docker-publish.yml) so
# the listener can share backend/services/decay.py instead of duplicating it.
FROM python:3.13-slim

WORKDIR /app

# Install OS packages needed by psycopg3 and pyzmq
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libzmq3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY eddn-listener/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY backend/services/decay.py ./
COPY eddn-listener/main.py ./

CMD ["python", "main.py"]
