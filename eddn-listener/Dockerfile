FROM python:3.13-slim

WORKDIR /app

# Install OS packages needed by psycopg2 and pyzmq
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        build-essential \
        libzmq3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY main.py ./

CMD ["python", "main.py"]