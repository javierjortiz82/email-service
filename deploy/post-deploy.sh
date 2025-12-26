#!/bin/bash
# =============================================================================
# Post-Deployment Script for Email Service
# =============================================================================
# Run this AFTER the first successful deployment to:
#   1. Initialize database schema
#   2. Create Cloud Scheduler job
#   3. Grant access to service accounts
#
# Prerequisites:
#   - Service deployed to Cloud Run
#   - Cloud SQL Proxy installed (for database init)
#   - Secrets configured with actual values
#
# Usage:
#   chmod +x deploy/post-deploy.sh
#   ./deploy/post-deploy.sh
# =============================================================================

set -euo pipefail

# Configuration
PROJECT_ID="gen-lang-client-0329024102"
REGION="us-central1"
SERVICE_NAME="email-service"
CLOUD_SQL_INSTANCE="demo-db"
CLOUD_SQL_CONNECTION="${PROJECT_ID}:${REGION}:${CLOUD_SQL_INSTANCE}"

# Service accounts that need invoker access
SERVICE_ACCOUNTS=(
    "orchestrator-sa@${PROJECT_ID}.iam.gserviceaccount.com"
    "demo-service-sa@${PROJECT_ID}.iam.gserviceaccount.com"
)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "\n${CYAN}--- $1 ---${NC}"; }

echo ""
echo "============================================================"
echo "       Post-Deployment Setup - Email Service               "
echo "============================================================"
echo ""

# Get service URL
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --format='value(status.url)' 2>/dev/null || echo "")

if [ -z "$SERVICE_URL" ]; then
    log_error "Service not found. Deploy the service first."
    exit 1
fi

log_success "Service URL: ${SERVICE_URL}"

# =============================================================================
# STEP 1: Initialize Database Schema
# =============================================================================
log_step "Step 1/3: Database Schema Initialization"

if [ -f "sql/init.sql" ]; then
    log_info "Checking for Cloud SQL Proxy..."

    if command -v cloud-sql-proxy &> /dev/null || [ -f "/tmp/cloud-sql-proxy" ]; then
        PROXY_CMD="${CLOUD_SQL_PROXY:-/tmp/cloud-sql-proxy}"
        [ ! -f "$PROXY_CMD" ] && PROXY_CMD="cloud-sql-proxy"

        log_info "Starting Cloud SQL Proxy..."
        $PROXY_CMD --port=5433 --gcloud-auth "${CLOUD_SQL_CONNECTION}" &
        PROXY_PID=$!
        sleep 5

        # Get DATABASE_URL from centralized secret
        DB_URL=$(gcloud secrets versions access latest --secret=database-url 2>/dev/null || echo "")

        if [ -n "$DB_URL" ]; then
            # Extract credentials from URL
            # Format: postgresql://user:pass@/dbname?host=/cloudsql/...
            DB_USER=$(echo "$DB_URL" | sed -n 's|postgresql://\([^:]*\):.*|\1|p')
            DB_PASS=$(echo "$DB_URL" | sed -n 's|postgresql://[^:]*:\([^@]*\)@.*|\1|p')
            DB_NAME=$(echo "$DB_URL" | sed -n 's|.*/\([^?]*\)?.*|\1|p')

            log_info "Running init.sql against database..."
            PGPASSWORD="$DB_PASS" psql -h localhost -p 5433 -U "$DB_USER" -d "$DB_NAME" -f sql/init.sql 2>/dev/null && \
                log_success "Database schema initialized" || \
                log_warning "Schema may already exist or psql not installed"
        else
            log_warning "Could not retrieve DATABASE_URL from secrets"
        fi

        # Stop proxy
        kill $PROXY_PID 2>/dev/null || true
    else
        log_warning "Cloud SQL Proxy not found. Run init.sql manually:"
        echo ""
        echo "  # Download proxy"
        echo "  curl -o /tmp/cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.1/cloud-sql-proxy.linux.amd64"
        echo "  chmod +x /tmp/cloud-sql-proxy"
        echo ""
        echo "  # Start proxy"
        echo "  /tmp/cloud-sql-proxy --port=5433 --gcloud-auth ${CLOUD_SQL_CONNECTION} &"
        echo ""
        echo "  # Run init.sql (replace credentials)"
        echo "  PGPASSWORD=xxx psql -h localhost -p 5433 -U demo_user -d demodb -f sql/init.sql"
        echo ""
    fi
else
    log_warning "sql/init.sql not found"
fi

# =============================================================================
# STEP 2: Grant Service Account Access
# =============================================================================
log_step "Step 2/3: Granting Service Account Access"

for sa in "${SERVICE_ACCOUNTS[@]}"; do
    log_info "Granting invoker role to: $sa"
    gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
        --region="${REGION}" \
        --member="serviceAccount:${sa}" \
        --role="roles/run.invoker" \
        --quiet 2>/dev/null && \
        log_success "Access granted to ${sa}" || \
        log_warning "Could not grant access to ${sa}"
done

# =============================================================================
# STEP 3: Create Cloud Scheduler Job
# =============================================================================
log_step "Step 3/3: Cloud Scheduler Setup"

SCHEDULER_JOB="email-queue-processor"

# Check if job exists
if gcloud scheduler jobs describe "${SCHEDULER_JOB}" --location="${REGION}" &>/dev/null; then
    log_success "Scheduler job '${SCHEDULER_JOB}' already exists"
else
    log_info "Creating Cloud Scheduler job..."
    gcloud scheduler jobs create http "${SCHEDULER_JOB}" \
        --location="${REGION}" \
        --schedule="* * * * *" \
        --uri="${SERVICE_URL}/queue/process" \
        --http-method=POST \
        --oidc-service-account-email="orchestrator-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
        --oidc-token-audience="${SERVICE_URL}" \
        --description="Process email queue every minute" \
        --quiet && \
        log_success "Scheduler job created" || \
        log_error "Failed to create scheduler job"
fi

# =============================================================================
# VERIFICATION
# =============================================================================
log_step "Verification"

log_info "Testing health endpoint..."
TOKEN=$(gcloud auth print-identity-token 2>/dev/null || echo "")

if [ -n "$TOKEN" ]; then
    HEALTH=$(curl -s -H "Authorization: Bearer $TOKEN" "${SERVICE_URL}/health" 2>/dev/null || echo "error")
    if echo "$HEALTH" | grep -q '"status":"ok"'; then
        log_success "Health check passed"
        echo "  $HEALTH"
    else
        log_warning "Health check returned: $HEALTH"
    fi
else
    log_warning "Could not get identity token for health check"
fi

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo "============================================================"
echo "                Post-Deployment Complete                    "
echo "============================================================"
echo ""
echo -e "Service URL: ${GREEN}${SERVICE_URL}${NC}"
echo ""
echo "Endpoints:"
echo "  POST ${SERVICE_URL}/emails         - Queue email"
echo "  GET  ${SERVICE_URL}/queue/status   - Queue stats"
echo "  POST ${SERVICE_URL}/queue/process  - Process queue"
echo "  GET  ${SERVICE_URL}/health         - Health check"
echo ""
echo "Test commands:"
echo "  TOKEN=\$(gcloud auth print-identity-token)"
echo "  curl -H \"Authorization: Bearer \$TOKEN\" ${SERVICE_URL}/health"
echo ""
log_success "Setup complete!"
