# ============================================================================
# Email Microservice Dockerfile
# ============================================================================
# Multi-stage build for API and Worker services
#
# Usage:
#   docker build -t email-service:latest .
#   docker run -p 8000:8000 --env-file .env email-service:latest

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd -r emailservice && \
    useradd -r -g emailservice -u 1001 emailservice

WORKDIR /app

# ============================================================================
# Dependencies stage
# ============================================================================
FROM base AS dependencies

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ============================================================================
# Production stage
# ============================================================================
FROM base AS production

COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

COPY --chown=emailservice:emailservice . /app/email_service/

RUN mkdir -p /app/logs && \
    chown -R emailservice:emailservice /app

ENV PYTHONPATH=/app

USER emailservice

# Health check using Python (no hardcoded port)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from email_service.config.settings import EmailConfig; print('healthy')" || exit 1

# Default port (can be overridden by API_PORT env var)
EXPOSE ${API_PORT:-8000}

# Default: run API server (command can be overridden in docker-compose)
CMD ["python", "-m", "email_service.api.main"]
