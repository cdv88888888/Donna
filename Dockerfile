FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps kept minimal; wheels cover the rest.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY donna ./donna
COPY web ./web
COPY scripts ./scripts

# Persistent SQLite lives on a mounted volume in production (see docs).
ENV DATABASE_URL=sqlite:////data/donna.db

EXPOSE 8000
CMD ["python", "-m", "donna.main"]
