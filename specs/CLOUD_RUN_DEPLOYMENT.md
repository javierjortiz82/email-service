# Email Service - Cloud Run Deployment Specification

## Version
- **Document Version:** 1.0.0
- **Service Version:** 2.0.0
- **Last Updated:** 2025-12-26

## Overview

This document specifies the Cloud Run deployment configuration and production test scenarios for the Email Service.

## Deployment Configuration

### Service Identity

| Component | Value |
|-----------|-------|
| **Service Name** | email-service |
| **Region** | us-central1 |
| **Project ID** | gen-lang-client-0329024102 |
| **Service Account** | email-service-sa@gen-lang-client-0329024102.iam.gserviceaccount.com |

### IAM Roles for Service Account

| Role | Purpose |
|------|---------|
| `roles/logging.logWriter` | Write logs to Cloud Logging |
| `roles/monitoring.metricWriter` | Write metrics to Cloud Monitoring |
| `roles/cloudsql.client` | Connect to Cloud SQL via Unix socket |
| `roles/secretmanager.secretAccessor` | Access secrets from Secret Manager |

### Secrets in Secret Manager

| Secret Name | Environment Variable | Description |
|-------------|---------------------|-------------|
| `email-service-db-url` | `DATABASE_URL` | PostgreSQL connection string with Cloud SQL socket |
| `email-smtp-user` | `SMTP_USER` | SMTP username (email address) |
| `email-smtp-password` | `SMTP_PASSWORD` | SMTP password (app password) |

### Cloud SQL Configuration

| Setting | Value |
|---------|-------|
| **Instance** | demo-db |
| **Connection Name** | gen-lang-client-0329024102:us-central1:demo-db |
| **Socket Path** | /cloudsql/gen-lang-client-0329024102:us-central1:demo-db |
| **Schema** | test |

### Cloud Run Settings

| Setting | Value |
|---------|-------|
| **Port** | 8080 |
| **Memory** | 512Mi |
| **CPU** | 1 |
| **Min Instances** | 0 |
| **Max Instances** | 10 |
| **Timeout** | 120s |
| **Concurrency** | 80 |
| **Authentication** | IAM (--no-allow-unauthenticated) |

---

## Production Test Scenarios

### Prerequisites

```bash
# Set environment variables
export PROJECT_ID="gen-lang-client-0329024102"
export REGION="us-central1"
export SERVICE_NAME="email-service"

# Get service URL
export SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
  --region=$REGION --format='value(status.url)')

# Get identity token
export TOKEN=$(gcloud auth print-identity-token)
```

---

### Scenario 1: Health Check

**Objective:** Verify service is healthy and database connection works.

**Command:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$SERVICE_URL/health" | jq
```

**Expected Response (200 OK):**
```json
{
  "status": "ok",
  "db": "ok",
  "email_provider": "ok",
  "version": "2.0.0",
  "timestamp": "2025-12-26T10:00:00.000000"
}
```

**Verification:**
- [ ] `status` is "ok"
- [ ] `db` is "ok" (Cloud SQL connected)
- [ ] `email_provider` is "ok" (SMTP configured)
- [ ] `version` matches deployed version

---

### Scenario 2: Unauthorized Access

**Objective:** Verify IAM authentication is enforced.

**Command:**
```bash
curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL/health"
```

**Expected Response:** `403` (Forbidden)

**Verification:**
- [ ] Returns 403 without Authorization header
- [ ] No sensitive data leaked in response

---

### Scenario 3: Send Simple Email

**Objective:** Queue an email for delivery.

**Command:**
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$SERVICE_URL/emails" \
  -d '{
    "to": ["test@example.com"],
    "subject": "Cloud Run Test",
    "body": "<h1>Hello!</h1><p>Email from Cloud Run deployment.</p>"
  }' | jq
```

**Expected Response (202 Accepted):**
```json
{
  "status": "accepted",
  "queued": true,
  "message_id": "uuid-here",
  "detail": "Email stored in queue",
  "timestamp": "2025-12-26T10:01:00.000000"
}
```

**Verification:**
- [ ] HTTP status is 202
- [ ] `queued` is true
- [ ] `message_id` is a valid UUID

---

### Scenario 4: Send Email with Template

**Objective:** Queue an email using a template.

**Command:**
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$SERVICE_URL/emails" \
  -d '{
    "to": ["user@example.com"],
    "subject": "Verify Your Email",
    "body": "fallback",
    "template_id": "otp_verification",
    "template_vars": {
      "recipient_name": "John Doe",
      "otp_code": "123456",
      "company_name": "NexusIntelligent"
    }
  }' | jq
```

**Expected Response (202 Accepted):**
```json
{
  "status": "accepted",
  "queued": true,
  "message_id": "uuid-here",
  "detail": "Email stored in queue",
  "timestamp": "2025-12-26T10:02:00.000000"
}
```

**Verification:**
- [ ] Template is rendered correctly in database
- [ ] Variables are substituted

---

### Scenario 5: Queue Status

**Objective:** Get email queue statistics.

**Command:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "$SERVICE_URL/queue/status" | jq
```

**Expected Response (200 OK):**
```json
{
  "pending": 2,
  "scheduled": 0,
  "processing": 0,
  "sent": 0,
  "failed": 0,
  "timestamp": "2025-12-26T10:03:00.000000"
}
```

**Verification:**
- [ ] Counts reflect queued emails
- [ ] No errors accessing database

---

### Scenario 6: Invalid Email Validation

**Objective:** Verify API validation rejects invalid emails.

**Command:**
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$SERVICE_URL/emails" \
  -d '{
    "to": ["invalid-email"],
    "subject": "Test",
    "body": "Body"
  }'
```

**Expected Response (422 Unprocessable Entity):**
```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "to", 0],
      "msg": "value is not a valid email address: An email address must have an @-sign."
    }
  ]
}
```

**Verification:**
- [ ] HTTP status is 422
- [ ] Error message indicates invalid email

---

### Scenario 7: Service-to-Service Call (Orchestrator)

**Objective:** Verify orchestrator-sa can invoke the service.

**Prerequisites:**
1. IAM binding exists:
   ```bash
   gcloud run services get-iam-policy email-service --region=us-central1
   ```

2. Should show:
   ```yaml
   - members:
     - serviceAccount:orchestrator-sa@gen-lang-client-0329024102.iam.gserviceaccount.com
     role: roles/run.invoker
   ```

**Test from Orchestrator:**
```python
from internal_service_client import InternalServiceClient

client = InternalServiceClient()

# Health check
health = await client.health_check("email")
print(health)  # Should show healthy

# Send email
result = await client.call_email_service(
    to=["user@example.com"],
    subject="Test from Orchestrator",
    body="<h1>Hello!</h1>"
)
print(result)  # Should show accepted
```

**Verification:**
- [ ] No authentication errors
- [ ] Email queued successfully

---

### Scenario 8: Cloud SQL Connection

**Objective:** Verify Cloud SQL Unix socket connection works.

**Check Logs:**
```bash
gcloud run services logs read email-service \
  --region=us-central1 --limit=20 \
  --format="table(timestamp,textPayload)"
```

**Expected Log Entry:**
```
INFO - Database connected: test.email_queue
```

**Verification:**
- [ ] No connection errors in logs
- [ ] Schema is correct (`test`)

---

### Scenario 9: Secret Manager Access

**Objective:** Verify secrets are properly injected.

**Check Service Config:**
```bash
gcloud run services describe email-service \
  --region=us-central1 \
  --format="yaml(spec.template.spec.containers[0].env)"
```

**Expected:** Shows `DATABASE_URL`, `SMTP_USER`, `SMTP_PASSWORD` sourced from Secret Manager.

**Verification:**
- [ ] Secrets are mounted as environment variables
- [ ] No plaintext secrets in config

---

### Scenario 10: Load Test

**Objective:** Verify service handles concurrent requests.

**Command:**
```bash
# Install hey if not present: go install github.com/rakyll/hey@latest

hey -n 100 -c 10 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -m POST \
  -d '{"to":["test@example.com"],"subject":"Load Test","body":"<p>Test</p>"}' \
  "$SERVICE_URL/emails"
```

**Expected Results:**
- 200+ requests/second
- < 500ms average latency
- 0% error rate

**Verification:**
- [ ] No 500 errors
- [ ] Latency within acceptable range
- [ ] Auto-scaling works (check instance count)

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| 403 Forbidden | Missing or invalid token | Refresh token with `gcloud auth print-identity-token` |
| Database connection failed | Cloud SQL socket not mounted | Check `--add-cloudsql-instances` flag |
| Secret access denied | Missing IAM binding | Grant `secretmanager.secretAccessor` to SA |
| SMTP authentication failed | Wrong credentials | Update secret values in Secret Manager |

### Debug Commands

```bash
# View logs
gcloud run services logs read email-service --region=us-central1 --limit=50

# Check IAM policy
gcloud run services get-iam-policy email-service --region=us-central1

# Describe service
gcloud run services describe email-service --region=us-central1

# List revisions
gcloud run revisions list --service=email-service --region=us-central1
```

---

## Rollback Procedure

```bash
# List all revisions
gcloud run revisions list --service=email-service --region=us-central1

# Route 100% traffic to previous revision
gcloud run services update-traffic email-service \
  --region=us-central1 \
  --to-revisions=email-service-PREVIOUS=100
```

---

## Approval

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Developer | | | |
| Reviewer | | | |
| Approver | | | |
