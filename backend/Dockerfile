# Production Dockerfile for Self-Healing SQL Backend
FROM python:3.12-slim AS runner

# Environment configuration
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install minimal system dependencies (curl for healthcheck, libpq for PostgreSQL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root application user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# Copy pyproject.toml and create minimal README.md for packaging
COPY pyproject.toml ./
RUN touch README.md

# Install python dependencies cleanly
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy backend application source code
COPY app/ ./app/

# Create data directory for SQLite persistence and grant ownership
RUN mkdir -p /app/data && chown -R appuser:appuser /app

# Run as non-root user
USER appuser

# Expose FastAPI service port
EXPOSE 8000

# Periodic health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Launch ASGI server with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
