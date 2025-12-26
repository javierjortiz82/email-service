# Email Service - Cloud Run Deployment Guide

## Overview

This guide covers deploying the Email Service to Google Cloud Run with:
- **IAM + Service Account** authentication (no public access)
- **Secret Manager** for sensitive credentials
- **Cloud SQL** connection via Unix socket
- **Orchestrator pattern** for service-to-service calls

## Architecture

```
                                    +------------------+
                                    |   orchestrator   |
                                    |   (Cloud Run)    |
                                    +--------+---------+
                                             |
                                    IAM Token (Identity)
                                             |
                                             v
+------------------+              +------------------+              +------------------+
|  Secret Manager  |<------------|  email-service   |------------->|    Cloud SQL     |
|                  |   Secrets   |   (Cloud Run)    |  Unix Socket |   (PostgreSQL)   |
+------------------+              +------------------+              +------------------+
        |                                  |
        |                                  v
        |                         +------------------+
        +------------------------>|   SMTP Server    |
          SMTP Credentials        |  (Gmail/etc)     |
                                  +------------------+
```

## Prerequisites

1. **Google Cloud SDK** installed and authenticated
2. **Docker** installed for local builds
3. **GCP Project** with billing enabled
4. **Cloud SQL instance** running (shared: `demo-db`)

## Quick Start

### 1. Initial GCP Setup (One-time)

```bash
# Make setup script executable
chmod +x deploy/setup-gcp.sh

# Run setup (creates service account, secrets, artifact registry)
./deploy/setup-gcp.sh
```

### 2. Configure Secrets

The email-service uses **centralized** and **service-specific** secrets:

| Secret | Type | Description |
|--------|------|-------------|
| `database-url` | Centralized | Shared PostgreSQL connection string |
| `email-smtp-user` | Service-specific | SMTP username for email sending |
| `email-smtp-password` | Service-specific | SMTP password (App Password) |

**Note:** The `database-url` secret is centralized and shared across services. Only update SMTP secrets during setup.

```bash
# SMTP Username (service-specific)
printf '%s' 'your-email@gmail.com' | \
  gcloud secrets versions add email-smtp-user --data-file=-

# SMTP Password - App Password for Gmail (service-specific)
printf '%s' 'your-16-char-app-password' | \
  gcloud secrets versions add email-smtp-password --data-file=-

# Note: database-url is centralized and already exists
# Only update if needed:
# printf '%s' 'postgresql://demo_user:YOUR_DB_PASSWORD@/demodb?host=/cloudsql/gen-lang-client-0329024102:us-central1:demo-db' | \
#   gcloud secrets versions add database-url --data-file=-
```

### 3. Deploy

**Option A: Using Cloud Build (Recommended)**
```bash
gcloud builds submit --config=cloudbuild.yaml
```

**Option B: Manual Deployment**
```bash
chmod +x deploy/deploy-manual.sh
./deploy/deploy-manual.sh
```

### 4. Post-Deployment Setup

After deployment, run the post-deploy script to:
- Initialize database schema (if new deployment)
- Grant access to orchestrator-sa and demo-service-sa
- Create Cloud Scheduler job for queue processing

```bash
chmod +x deploy/post-deploy.sh
./deploy/post-deploy.sh
```

Or manually:

```bash
# Grant orchestrator access
gcloud run services add-iam-policy-binding email-service \
  --region=us-central1 \
  --member='serviceAccount:orchestrator-sa@gen-lang-client-0329024102.iam.gserviceaccount.com' \
  --role='roles/run.invoker'

# Grant demo-service access
gcloud run services add-iam-policy-binding email-service \
  --region=us-central1 \
  --member='serviceAccount:demo-service-sa@gen-lang-client-0329024102.iam.gserviceaccount.com' \
  --role='roles/run.invoker'

# Create Cloud Scheduler job
SERVICE_URL=$(gcloud run services describe email-service --region=us-central1 --format='value(status.url)')
gcloud scheduler jobs create http email-queue-processor \
  --location=us-central1 \
  --schedule="* * * * *" \
  --uri="${SERVICE_URL}/queue/process" \
  --http-method=POST \
  --oidc-service-account-email=orchestrator-sa@gen-lang-client-0329024102.iam.gserviceaccount.com \
  --oidc-token-audience="${SERVICE_URL}"
```

## Security Configuration

### Service Account Roles

The `email-service-sa` has minimal roles:

| Role | Purpose |
|------|---------|
| `roles/logging.logWriter` | Write logs to Cloud Logging |
| `roles/monitoring.metricWriter` | Write metrics to Cloud Monitoring |
| `roles/cloudsql.client` | Connect to Cloud SQL |
| `roles/secretmanager.secretAccessor` | Access secrets |

### IAM Authentication

The service uses `--no-allow-unauthenticated`, requiring IAM authentication:

```bash
# Get identity token for testing
TOKEN=$(gcloud auth print-identity-token)

# Call the service
curl -H "Authorization: Bearer $TOKEN" \
  https://email-service-XXXXX.us-central1.run.app/health
```

### Service-to-Service Calls

The orchestrator uses `internal_service_client.py` from `shared-libs`:

```python
from internal_service_client import InternalServiceClient

client = InternalServiceClient(
    email_service_url="https://email-service-XXXXX.us-central1.run.app"
)

# The client automatically obtains IAM identity tokens
result = await client.call_email_service(...)
```

## Environment Variables

### Non-Sensitive (in cloudbuild.yaml)

| Variable | Value | Description |
|----------|-------|-------------|
| `SERVICE_NAME` | email-service | Service identifier |
| `SERVICE_VERSION` | 2.0.0 | Version string |
| `ENVIRONMENT` | production | Environment name |
| `API_PORT` | 8080 | Server port (Cloud Run standard) |
| `SCHEMA_NAME` | test | PostgreSQL schema |
| `SMTP_HOST` | smtp.gmail.com | SMTP server |
| `SMTP_PORT` | 587 | SMTP port |
| `LOG_LEVEL` | INFO | Logging level |

### Sensitive (from Secret Manager)

| Secret Name | Environment Variable | Type | Description |
|-------------|---------------------|------|-------------|
| `database-url` | `DATABASE_URL` | Centralized | PostgreSQL connection string (shared) |
| `email-smtp-user` | `SMTP_USER` | Service-specific | SMTP username |
| `email-smtp-password` | `SMTP_PASSWORD` | Service-specific | SMTP password |

## Updating the Internal Service Client

Add email service support to `shared-libs/internal_service_client.py`:

```python
class InternalServiceClient:
    def __init__(
        self,
        # ... existing services ...
        email_service_url: str | None = None,
    ):
        # ... existing init ...
        self.email_url = email_service_url or os.getenv(
            "EMAIL_SERVICE_URL",
            "https://email-service-69054835734.us-central1.run.app"
        )

    async def call_email_service(
        self,
        to: list[str],
        subject: str,
        body: str,
        template_id: str | None = None,
        template_vars: dict | None = None,
    ) -> dict[str, Any]:
        """Send email via the email service.

        Args:
            to: List of recipient email addresses
            subject: Email subject
            body: HTML body content
            template_id: Optional template name
            template_vars: Template variables

        Returns:
            Response with message_id and status
        """
        headers = self._get_auth_headers(self.email_url)
        payload = {
            "to": to,
            "subject": subject,
            "body": body,
        }
        if template_id:
            payload["template_id"] = template_id
        if template_vars:
            payload["template_vars"] = template_vars

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.email_url}/emails",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()
```

## Testing in Production

### Health Check
```bash
TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer $TOKEN" \
  https://email-service-XXXXX.us-central1.run.app/health
```

Expected response:
```json
{
  "status": "ok",
  "db": "ok",
  "email_provider": "ok",
  "version": "2.0.0",
  "timestamp": "2025-12-26T..."
}
```

### Send Test Email
```bash
TOKEN=$(gcloud auth print-identity-token)
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  https://email-service-XXXXX.us-central1.run.app/emails \
  -d '{
    "to": ["test@example.com"],
    "subject": "Test from Cloud Run",
    "body": "<h1>Hello!</h1><p>Email service is working.</p>"
  }'
```

### Queue Status
```bash
TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer $TOKEN" \
  https://email-service-XXXXX.us-central1.run.app/queue/status
```

## Monitoring

### Logs
```bash
# View logs in Cloud Console
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=email-service" \
  --limit=50 --format="table(timestamp,textPayload)"
```

### Metrics
- Cloud Run metrics in Cloud Console
- Custom metrics via `roles/monitoring.metricWriter`

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| 403 Forbidden | Check IAM permissions for caller |
| Secret access error | Verify service account has `secretAccessor` role |
| Database connection failed | Check Cloud SQL instance and socket path |
| SMTP authentication failed | Verify secrets are updated with correct values |

### Debug Commands

```bash
# Check service status
gcloud run services describe email-service --region=us-central1

# View recent logs
gcloud run services logs read email-service --region=us-central1 --limit=20

# Check IAM policy
gcloud run services get-iam-policy email-service --region=us-central1

# List secret versions
gcloud secrets versions list database-url
```

## Rollback

```bash
# List revisions
gcloud run revisions list --service=email-service --region=us-central1

# Route traffic to previous revision
gcloud run services update-traffic email-service \
  --region=us-central1 \
  --to-revisions=email-service-XXXXX=100
```