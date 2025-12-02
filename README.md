# Odiseo Email Service

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

**Production-ready email microservice with queue management, retry logic, and SMTP integration.**

[Quick Start](#-quick-start) •
[API Reference](#-api-reference) •
[Configuration](#%EF%B8%8F-configuration) •
[Architecture](#-architecture)

</div>

---

## Overview

Odiseo Email Service is a robust, scalable email sending microservice designed for production environments. It provides:

- **Async Queue Processing** - Emails are queued and processed by background workers
- **Automatic Retries** - Exponential backoff with configurable retry attempts
- **SMTP Integration** - Compatible with Gmail, SendGrid, AWS SES, and any SMTP provider
- **RESTful API** - Simple JSON API for sending emails and monitoring queue status
- **PostgreSQL Storage** - Reliable persistence with atomic operations
- **Docker Ready** - Multi-stage build with health checks

---

## Features

| Feature | Description |
|---------|-------------|
| **Queue-based Processing** | Emails are stored in PostgreSQL and processed asynchronously |
| **Retry with Backoff** | Failed emails retry with exponential backoff (2^n × base_seconds) |
| **Concurrency Safe** | Uses `FOR UPDATE SKIP LOCKED` for horizontal scaling |
| **Template Support** | Jinja2 HTML email templates |
| **Health Monitoring** | `/health` endpoint for load balancer checks |
| **Structured Logging** | Rotating log files with configurable levels |

---

## Quick Start

### Prerequisites
- Docker and Docker Compose
- PostgreSQL (or use existing `mcp-postgres` container)
- SMTP credentials (Gmail, SendGrid, etc.)

### 1. Clone and Configure

```bash
# Clone repository
git clone https://github.com/odiseo/email-service.git
cd email-service

# Configure environment
cp .env.example .env
# Edit .env with your SMTP credentials
```

### 2. Start Services

```bash
# Start API and Worker
docker-compose up -d

# Check status
docker ps --filter "name=email-service"
```

### 3. Send a Test Email

```bash
curl -X POST http://localhost:8001/emails \
  -H "Content-Type: application/json" \
  -d '{
    "to": ["recipient@example.com"],
    "subject": "Hello from Odiseo",
    "body": "<h1>Welcome!</h1><p>Your email service is working.</p>"
  }'
```

### 4. Check Health

```bash
curl http://localhost:8001/health
```

---

## Architecture

### System Overview

```mermaid
flowchart TB
    subgraph Client["🌐 Client"]
        C[HTTP Request]
    end

    subgraph API["⚡ FastAPI Service"]
        direction TB
        A["/emails"]
        B["/health"]
        D["/queue/status"]
    end

    subgraph Database["🗄️ PostgreSQL"]
        DB[(email_queue)]
    end

    subgraph Worker["⚙️ Background Worker"]
        W[Email Processor]
    end

    subgraph SMTP["📧 SMTP Provider"]
        S[Gmail / SendGrid / SES]
    end

    C --> A
    C --> B
    C --> D
    A -->|INSERT| DB
    B -->|SELECT 1| DB
    D -->|COUNT| DB
    W -->|FOR UPDATE SKIP LOCKED| DB
    W -->|Send Email| S
    S -->|Response| W
    W -->|UPDATE status| DB

    style Client fill:#e1f5fe,stroke:#01579b,color:#01579b
    style API fill:#e8f5e9,stroke:#2e7d32,color:#2e7d32
    style Database fill:#fff3e0,stroke:#e65100,color:#e65100
    style Worker fill:#f3e5f5,stroke:#7b1fa2,color:#7b1fa2
    style SMTP fill:#fce4ec,stroke:#c2185b,color:#c2185b
```

### Request Flow

```mermaid
sequenceDiagram
    autonumber
    participant C as 🌐 Client
    participant A as ⚡ API
    participant DB as 🗄️ PostgreSQL
    participant W as ⚙️ Worker
    participant S as 📧 SMTP

    rect rgb(225, 245, 254)
        Note over C,A: Email Submission
        C->>+A: POST /emails
        A->>DB: INSERT (status=pending)
        A-->>-C: 202 Accepted
    end

    rect rgb(243, 229, 245)
        Note over W,S: Background Processing
        loop Every 10 seconds
            W->>DB: SELECT FOR UPDATE SKIP LOCKED
            DB-->>W: Pending emails
            W->>DB: UPDATE status=processing
            W->>+S: Send via SMTP
            S-->>-W: Success/Failure
            alt Success
                W->>DB: UPDATE status=sent
            else Failure (retries left)
                W->>DB: UPDATE status=scheduled
            else Max retries exceeded
                W->>DB: UPDATE status=failed
            end
        end
    end
```

### Email State Machine

```mermaid
stateDiagram-v2
    [*] --> pending: Email Created

    pending --> processing: Worker picks up
    scheduled --> processing: Retry time reached

    processing --> sent: ✅ Success
    processing --> scheduled: 🔄 Retry
    processing --> failed: ❌ Max retries

    sent --> [*]
    failed --> [*]

    note right of pending: New email in queue
    note right of processing: Being sent now
    note right of scheduled: Waiting for retry
    note right of sent: Delivered successfully
    note right of failed: Permanent failure
```

### Container Architecture

```mermaid
flowchart LR
    subgraph Docker["🐳 Docker Network"]
        direction TB

        subgraph Services["Email Service Containers"]
            API["📡 email-service-api<br/>Port: 8001"]
            WORKER["⚙️ email-service-worker<br/>Background Process"]
        end

        subgraph External["External Services"]
            PG["🐘 mcp-postgres<br/>Port: 5432"]
        end
    end

    subgraph Internet["☁️ Internet"]
        SMTP["📧 SMTP Server"]
    end

    API <--> PG
    WORKER <--> PG
    WORKER --> SMTP

    style API fill:#4caf50,stroke:#2e7d32,color:#fff
    style WORKER fill:#2196f3,stroke:#1565c0,color:#fff
    style PG fill:#ff9800,stroke:#e65100,color:#fff
    style SMTP fill:#e91e63,stroke:#ad1457,color:#fff
```

---

## API Reference

### POST /emails

Send an email (queued for async delivery).

**Request:**
```json
{
  "to": ["user@example.com"],
  "subject": "Hello World",
  "body": "<h1>Welcome!</h1>",
  "client_message_id": "optional-uuid",
  "template_id": null,
  "template_vars": {}
}
```

**Response (202 Accepted):**
```json
{
  "status": "accepted",
  "queued": true,
  "message_id": "5a377f3a-abeb-4e60-a59e-2a706e6021f8",
  "detail": "Email stored in queue",
  "timestamp": "2025-12-02T05:07:15.918469"
}
```

---

### GET /queue/status

Get email queue statistics.

**Response:**
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

---

### GET /health

Check service health.

**Response:**
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

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| **Service** |||
| `SERVICE_NAME` | email-service | Service identifier |
| `SERVICE_VERSION` | 1.0.0 | Version string |
| `API_PORT` | 8001 | API server port |
| **Database** |||
| `DATABASE_URL` | - | PostgreSQL connection string |
| `SCHEMA_NAME` | test | Database schema name |
| **SMTP** |||
| `SMTP_HOST` | smtp.gmail.com | SMTP server hostname |
| `SMTP_PORT` | 587 | SMTP server port |
| `SMTP_USER` | - | SMTP username |
| `SMTP_PASSWORD` | - | SMTP password |
| `SMTP_FROM_EMAIL` | noreply@odiseo.io | Sender email |
| `SMTP_FROM_NAME` | Odiseo | Sender display name |
| `SMTP_USE_TLS` | true | Enable TLS |
| **Worker** |||
| `EMAIL_WORKER_POLL_INTERVAL` | 10 | Queue poll interval (seconds) |
| `EMAIL_WORKER_BATCH_SIZE` | 50 | Max emails per batch |
| `EMAIL_RETRY_MAX_ATTEMPTS` | 3 | Maximum retry attempts |
| `EMAIL_RETRY_BACKOFF_SECONDS` | 300 | Initial backoff (seconds) |
| **Logging** |||
| `LOG_LEVEL` | INFO | Log level |
| `LOG_TO_FILE` | true | Enable file logging |
| `LOG_DIR` | ./logs | Log directory |

### Gmail Configuration

1. Enable 2-Factor Authentication on your Google account
2. Generate an App Password at https://myaccount.google.com/apppasswords
3. Configure `.env`:

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=your-email@gmail.com
SMTP_FROM_NAME=Odiseo
SMTP_USE_TLS=true
```

---

## Project Structure

```
email-service/
├── api/
│   ├── main.py              # FastAPI endpoints
│   └── schemas.py           # Pydantic models
├── clients/
│   └── smtp.py              # SMTP client
├── config/
│   └── settings.py          # Configuration
├── core/
│   ├── exceptions.py        # Custom exceptions
│   └── logger.py            # Logging setup
├── database/
│   └── queue.py             # Queue manager
├── models/
│   ├── email.py             # Email models
│   └── smtp_config.py       # SMTP config model
├── templates/
│   ├── renderer.py          # Jinja2 renderer
│   └── *.html               # Email templates
├── worker/
│   ├── __main__.py          # Entry point
│   └── processor.py         # Email worker
├── sql/
│   └── init.sql             # Database schema
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Docker Commands

```bash
# Start services
docker-compose up -d

# View logs
docker logs -f email-service-api
docker logs -f email-service-worker

# Stop services
docker-compose down

# Rebuild after changes
docker-compose up -d --build

# Check container status
docker ps --filter "name=email-service"
```

---

## Database Schema

The service uses a PostgreSQL queue table with the following key fields:

```sql
CREATE TABLE test.email_queue (
    id BIGSERIAL PRIMARY KEY,
    recipient_email TEXT,
    subject TEXT,
    body_html TEXT,
    status TEXT DEFAULT 'pending',  -- pending|scheduled|processing|sent|failed
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    created_at TIMESTAMPTZ DEFAULT now(),
    sent_at TIMESTAMPTZ,
    last_error TEXT
);
```

### Concurrency

The worker uses `FOR UPDATE SKIP LOCKED` for safe concurrent processing:

```sql
SELECT * FROM email_queue
WHERE status IN ('pending', 'scheduled')
ORDER BY priority, created_at
LIMIT 50
FOR UPDATE SKIP LOCKED;
```

---

## Retry Logic

```mermaid
flowchart TD
    A[Email Failed] --> B{Retry Count < Max?}
    B -->|Yes| C[Calculate Backoff]
    C --> D["Wait: base × 2^retry_count"]
    D --> E[Retry Send]
    E --> F{Success?}
    F -->|Yes| G[✅ Mark as Sent]
    F -->|No| A
    B -->|No| H[❌ Mark as Failed]

    style A fill:#ffcdd2,stroke:#c62828,color:#c62828
    style G fill:#c8e6c9,stroke:#2e7d32,color:#2e7d32
    style H fill:#ffcdd2,stroke:#c62828,color:#c62828
    style C fill:#fff9c4,stroke:#f9a825,color:#f9a825
    style D fill:#fff9c4,stroke:#f9a825,color:#f9a825
```

**Backoff Formula:** `backoff_seconds × 2^retry_count`

| Retry | Wait Time (base=300s) |
|-------|----------------------|
| 1st   | 5 minutes |
| 2nd   | 10 minutes |
| 3rd   | 20 minutes |

---

## Monitoring

### Health Check

```bash
# Check if service is healthy
curl -f http://localhost:8001/health || echo "Service unhealthy"
```

### Queue Status

```bash
# Monitor queue
watch -n 5 'curl -s http://localhost:8001/queue/status | jq'
```

### Logs

```bash
# API logs
docker logs -f email-service-api

# Worker logs
docker logs -f email-service-worker

# Log files (if LOG_TO_FILE=true)
tail -f logs/email_service.log
```

---

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Port 8001 in use | Change `API_PORT` in `.env` |
| SMTP connection failed | Verify credentials and enable App Passwords for Gmail |
| Database connection error | Ensure PostgreSQL is running and accessible |
| Emails stuck in pending | Check worker logs: `docker logs email-service-worker` |

### Debug Mode

```bash
# Run with debug logging
LOG_LEVEL=DEBUG docker-compose up
```

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

This project is licensed under the MIT License.

```
MIT License

Copyright (c) 2025 Odiseo

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software.
```

---

<div align="center">

**Odiseo Email Service** • Built with FastAPI & PostgreSQL

[Report Bug](https://github.com/odiseo/email-service/issues) •
[Request Feature](https://github.com/odiseo/email-service/issues)

</div>
