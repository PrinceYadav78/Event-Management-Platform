# Small, fast base image for Cloud Run
FROM python:3.12-slim

# Cleaner logs, no .pyc files
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first (Docker caches this layer unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# The SQLite mirror requires a single process — uvicorn runs one worker by default.
# Cloud Run routes traffic to $PORT (8080 by default); bind uvicorn to it.
# (sh -c so $PORT expands; JSON form keeps Docker's signal handling happy.)
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
