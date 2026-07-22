FROM python:3.13-slim

# Install OS packages needed by psycopg2, bcrypt, cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

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
