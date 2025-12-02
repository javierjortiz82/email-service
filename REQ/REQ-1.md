# REQ-1: Email Microservice Specification

**Author:** Odiseo
**Version:** 1.0.0
**Status:** Implemented

---

## 1. Overview
This document defines the complete functional and technical specification for a production-ready **Email Sending Microservice**. The service exposes endpoints to send emails, check queue status, and validate service health. All emails—successful or failed—are stored in a PostgreSQL queue table and retried by a background worker.

The system follows strict software architecture principles:
- Modular architecture, small files (<280 lines)
- Pydantic v2 validation
- Python 3.11+ type hints
- Structured logging
- Robust error handling
- No hardcoded values (all configurable via environment)
- Up-to-date dependencies
- Clean, PEP8-compliant code

---

## 2. Functional Requirements

### 2.1 Endpoints
| Endpoint | Method | Description |
|---------|--------|-------------|
| `/health` | GET | Returns the health status of the service and its dependencies |
| `/emails` | POST | Receives a request to send an email. Persists email to DB and queues for delivery |
| `/queue/status` | GET | Returns counts of pending, scheduled, processing, sent, and failed emails |

Every endpoint must:
- Return structured JSON responses
- Include timestamps in responses
- Log every operation

---

## 3. Email Queue Table Specification
The queue table supports concurrency, retries, and worker-safe state transitions.

### 3.1 Status Values
```
PENDING = "pending"
SCHEDULED = "scheduled"
PROCESSING = "processing"
SENT = "sent"
FAILED = "failed"
```

### 3.2 SQL Schema
```sql
CREATE SCHEMA IF NOT EXISTS test;

CREATE TABLE IF NOT EXISTS test.email_queue (
    id BIGSERIAL PRIMARY KEY,
    client_message_id TEXT,

    -- Recipients
    to_addresses TEXT[] NOT NULL,
    cc_addresses TEXT[],
    bcc_addresses TEXT[],

    -- Content
    subject TEXT,
    body TEXT,
    template_id TEXT,
    template_vars JSONB,
    metadata JSONB,

    -- Email type and recipient info
    email_type TEXT NOT NULL DEFAULT 'transactional',
    recipient_email TEXT,
    recipient_name TEXT,
    body_html TEXT,
    body_text TEXT,
    booking_id BIGINT,
    template_context JSONB,
    priority INT NOT NULL DEFAULT 5,

    -- Status tracking
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 3,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    last_attempt_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    scheduled_for TIMESTAMPTZ DEFAULT now(),
    sent_at TIMESTAMPTZ,
    next_retry_at TIMESTAMPTZ,

    -- Error tracking
    last_error TEXT,
    provider_response JSONB
);

-- Indexes for Performance
CREATE INDEX idx_email_queue_status ON test.email_queue (status);
CREATE INDEX idx_email_queue_next_attempt ON test.email_queue (next_attempt_at);
CREATE INDEX idx_email_queue_scheduled_for ON test.email_queue (scheduled_for);
CREATE INDEX idx_email_queue_priority ON test.email_queue (priority);
```

---

## 4. Concurrency Handling
The worker ensures safe transitions between states:
- `pending` → `processing`
- `scheduled` → `processing`
- `processing` → (`sent` | `failed` | `scheduled`)

### 4.1 Database Functions
The system uses PostgreSQL stored procedures for atomic operations:

```sql
-- Get pending emails with FOR UPDATE SKIP LOCKED
CREATE FUNCTION test.get_pending_emails(p_limit INT)
RETURNS SETOF test.email_queue AS $$
BEGIN
    RETURN QUERY
    UPDATE test.email_queue
    SET status = 'processing', updated_at = now()
    WHERE id IN (
        SELECT id FROM test.email_queue
        WHERE status IN ('pending', 'scheduled')
        AND (scheduled_for IS NULL OR scheduled_for <= now())
        ORDER BY priority ASC, created_at ASC
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    RETURNING *;
END;
$$ LANGUAGE plpgsql;
```

### 4.2 Concurrency Techniques
- `SELECT ... FOR UPDATE SKIP LOCKED` for horizontal-scalable workers
- Atomic status transitions via stored procedures
- Batch pulling of tasks (configurable batch size)
- Priority-based processing

---

## 5. Retry Logic
- Exponential backoff with jitter: `backoff_seconds * 2^retry_count`
- Configurable via environment variables:
  - `EMAIL_RETRY_MAX_ATTEMPTS` (default: 3)
  - `EMAIL_RETRY_BACKOFF_SECONDS` (default: 300)
- Retry only if `retry_count < max_retries`
- On success: status → `sent`
- On final failure: status → `failed`

---

## 6. Background Worker
The background worker uses an asyncio loop with polling:

### 6.1 Worker Configuration
| Variable | Default | Description |
|----------|---------|-------------|
| `EMAIL_WORKER_POLL_INTERVAL` | 10 | Seconds between queue polls |
| `EMAIL_WORKER_BATCH_SIZE` | 50 | Max emails per batch |
| `EMAIL_RETRY_MAX_ATTEMPTS` | 3 | Maximum retry attempts |
| `EMAIL_RETRY_BACKOFF_SECONDS` | 300 | Initial backoff duration |

### 6.2 Worker Behavior
1. Poll queue for `pending` or `scheduled` emails
2. Atomically move to `processing` with database locks
3. Attempt to send email via SMTP provider
4. Update status: `sent` on success, `scheduled` for retry, `failed` on max retries
5. Log every step with structured logging

---

## 7. API Specifications

### 7.1 POST `/emails`
**Behavior:**
- Validate request using Pydantic v2
- Persist item to DB with `pending` status
- Worker picks up and sends asynchronously

**Request Body**
```json
{
  "client_message_id": "optional-uuid",
  "to": ["user@example.com"],
  "subject": "Hello",
  "body": "<p>Hello world</p>",
  "template_id": null,
  "template_vars": {}
}
```

**Response (202 Accepted)**
```json
{
  "status": "accepted",
  "queued": true,
  "message_id": "uuid",
  "detail": "Email stored in queue",
  "timestamp": "2025-12-02T05:07:15.918469"
}
```

### 7.2 GET `/queue/status`
Returns counts for each state:
```json
{
  "pending": 0,
  "scheduled": 0,
  "processing": 0,
  "sent": 23,
  "failed": 0,
  "timestamp": "2025-12-02T05:07:56.869278"
}
```

### 7.3 GET `/health`
```json
{
  "status": "ok",
  "db": "ok",
  "email_provider": "ok",
  "version": "1.0.0",
  "timestamp": "2025-12-02T05:06:28.463917"
}
```

---

## 8. Docker Environment

### 8.1 Dockerfile
- Multi-stage build with Python 3.11-slim base
- Non-root user (emailservice:1001)
- Copies to `/app/email_service/`
- Health check via Python import
- No hardcoded secrets

### 8.2 docker-compose.yml
Services:
- **api**: FastAPI application on port 8001
- **worker**: Background email processor

Network:
- Uses external `docker-config` network
- Connects to existing `mcp-postgres` container

Volumes:
- `./logs:/app/logs` for log persistence

### 8.3 Environment Variables
```bash
# Service
SERVICE_NAME=email-service
SERVICE_VERSION=1.0.0
API_HOST=0.0.0.0
API_PORT=8001

# Database
DATABASE_URL=postgresql://user:pass@mcp-postgres:5432/mcpdb
SCHEMA_NAME=test

# SMTP
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=noreply@odiseo.io
SMTP_FROM_NAME=Odiseo
SMTP_USE_TLS=true

# Worker
EMAIL_WORKER_POLL_INTERVAL=10
EMAIL_WORKER_BATCH_SIZE=50
EMAIL_RETRY_MAX_ATTEMPTS=3
EMAIL_RETRY_BACKOFF_SECONDS=300

# Logging
LOG_LEVEL=INFO
LOG_TO_FILE=true
LOG_DIR=/app/logs
```

### 8.4 .dockerignore
Excludes:
- `__pycache__/`, `*.pyc`
- `.pytest_cache/`, `.mypy_cache/`
- `.env`, `.env.local`
- `logs/`, `*.log`
- `venv/`, `.venv/`
- `.git/`, `.idea/`, `.vscode/`

---

## 9. Logging Requirements
- Structured logging with Python's logging module
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Rotating file handler (10MB, 5 backups)
- Log format: `YYYY-MM-DD HH:MM:SS - LEVEL - message`
- Worker logs include email ID and recipient

---

## 10. Project Structure
```
email-service/
├── api/
│   ├── __init__.py
│   ├── main.py          # FastAPI app, endpoints
│   └── schemas.py       # Pydantic request/response models
├── clients/
│   ├── __init__.py
│   └── smtp.py          # SMTP client wrapper
├── config/
│   ├── __init__.py
│   └── settings.py      # Pydantic Settings configuration
├── core/
│   ├── __init__.py
│   ├── exceptions.py    # Custom exceptions
│   └── logger.py        # Logging configuration
├── database/
│   ├── __init__.py
│   └── queue.py         # EmailQueueManager
├── models/
│   ├── __init__.py
│   ├── email.py         # Email models and enums
│   ├── smtp_config.py   # SMTP configuration model
│   └── ...
├── templates/
│   ├── __init__.py
│   ├── renderer.py      # Jinja2 template renderer
│   └── *.html           # Email templates
├── worker/
│   ├── __init__.py
│   ├── __main__.py      # Worker entry point
│   └── processor.py     # EmailWorker class
├── sql/
│   └── init.sql         # Database schema
├── tests/
│   └── ...
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## 11. Mermaid Diagrams

### 11.1 Architecture
```mermaid
graph TD;
    Client --> API[FastAPI :8001];
    API --> DB[(PostgreSQL)];
    Worker --> DB;
    Worker --> SMTP[SMTP Provider];
    API --> Logs((Logs));
    Worker --> Logs;
```

### 11.2 Sequence Diagram
```mermaid
sequenceDiagram
    Client->>API: POST /emails
    API->>DB: Insert queue entry (pending)
    API-->>Client: 202 Accepted
    loop Every 10s
        Worker->>DB: get_pending_emails(50) FOR UPDATE SKIP LOCKED
        Worker->>DB: status = processing
        Worker->>SMTP: Send email
        alt Success
            Worker->>DB: status = sent
        else Failure (retries left)
            Worker->>DB: status = scheduled, next_retry_at
        else Failure (no retries)
            Worker->>DB: status = failed
        end
    end
```

### 11.3 State Diagram
```mermaid
stateDiagram-v2
    [*] --> pending: Email created
    pending --> processing: Worker picks up
    scheduled --> processing: Retry time reached
    processing --> sent: Success
    processing --> scheduled: Retry (attempts < max)
    processing --> failed: Max retries exceeded
    sent --> [*]
    failed --> [*]
```

---

## 12. Requirements Compliance

| Requirement | Status |
|-------------|--------|
| Modular architecture | ✅ |
| Max 280 lines per file | ✅ |
| Python 3.11+ | ✅ |
| Pydantic v2 | ✅ |
| No legacy code | ✅ |
| No hardcoded values | ✅ |
| Updated dependencies | ✅ |
| Clean code & PEP8 | ✅ |
| FOR UPDATE SKIP LOCKED | ✅ |
| Exponential backoff | ✅ |
| Docker multi-stage build | ✅ |
| Structured logging | ✅ |

---

## 13. Deployment

### 13.1 Quick Start
```bash
# Start services (uses existing mcp-postgres)
docker-compose up -d

# Check status
docker ps --filter "name=email-service"

# View logs
docker logs email-service-api
docker logs email-service-worker
```

### 13.2 Test Email
```bash
curl -X POST http://localhost:8001/emails \
  -H "Content-Type: application/json" \
  -d '{"to": ["test@example.com"], "subject": "Test", "body": "<h1>Hello</h1>"}'
```

### 13.3 Health Check
```bash
curl http://localhost:8001/health
```

---

## 14. Final Notes
This specification defines the complete blueprint for the Odiseo Email Microservice. The implementation is production-ready with:
- Async worker with configurable polling
- SMTP integration (Gmail, SendGrid, AWS SES compatible)
- PostgreSQL queue with atomic operations
- Exponential backoff retry logic
- Docker containerization
- Comprehensive logging

**Copyright (c) 2025 Odiseo**
