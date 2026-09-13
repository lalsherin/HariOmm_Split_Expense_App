FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as a non-root user
RUN useradd --system --uid 1001 splitledger && chown -R splitledger /srv
USER splitledger

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD curl -fsS "http://localhost:${PORT:-8000}/health" || exit 1

# Managed hosts (Render, Railway, Fly, Cloud Run) hand the port in $PORT and
# route nothing to a container that listens somewhere else. Shell form so the
# variable is expanded; 8000 when nobody sets one.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
