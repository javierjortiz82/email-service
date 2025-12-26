#!/bin/bash
# =============================================================================
# Manual Deployment Script for Email Service
# =============================================================================
# Use this script for manual deployments outside of Cloud Build.
#
# Prerequisites:
#   - GCP setup completed (run setup-gcp.sh first)
#   - Secrets configured in Secret Manager
#   - Docker configured for Artifact Registry
#
# Usage:
#   chmod +x deploy/deploy-manual.sh
#   ./deploy/deploy-manual.sh
# =============================================================================

set -euo pipefail

# Configuration
PROJECT_ID="gen-lang-client-0329024102"
REGION="us-central1"
SERVICE_NAME="email-service"
REPO_NAME="email-repo"
SA_EMAIL="email-service-sa@${PROJECT_ID}.iam.gserviceaccount.com"
CLOUD_SQL_INSTANCE="${PROJECT_ID}:${REGION}:demo-db"

# Image tag (use git short SHA or timestamp)
if git rev-parse --short HEAD &>/dev/null; then
    IMAGE_TAG=$(git rev-parse --short HEAD)
else
    IMAGE_TAG=$(date +%Y%m%d%H%M%S)
fi

IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }

echo ""
echo "============================================================"
echo "       Manual Deployment - Email Service                    "
echo "============================================================"
echo ""

# Step 1: Build Docker image
log_info "Building Docker image..."
docker build -f deploy/Dockerfile.cloudrun -t "${IMAGE_NAME}:${IMAGE_TAG}" -t "${IMAGE_NAME}:latest" .
log_success "Image built: ${IMAGE_NAME}:${IMAGE_TAG}"

# Step 2: Push to Artifact Registry
log_info "Pushing to Artifact Registry..."
docker push "${IMAGE_NAME}:${IMAGE_TAG}"
docker push "${IMAGE_NAME}:latest"
log_success "Image pushed"

# Step 3: Deploy to Cloud Run
log_info "Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE_NAME}:${IMAGE_TAG}" \
    --region="${REGION}" \
    --platform=managed \
    --service-account="${SA_EMAIL}" \
    --no-allow-unauthenticated \
    --port=8080 \
    --memory=512Mi \
    --cpu=1 \
    --min-instances=0 \
    --max-instances=10 \
    --timeout=120 \
    --concurrency=80 \
    --add-cloudsql-instances="${CLOUD_SQL_INSTANCE}" \
    --set-env-vars="SERVICE_NAME=${SERVICE_NAME},SERVICE_VERSION=2.0.0,ENVIRONMENT=production,API_HOST=0.0.0.0,API_PORT=8080,SCHEMA_NAME=test,SMTP_HOST=smtp.gmail.com,SMTP_PORT=587,SMTP_USE_TLS=true,SMTP_TIMEOUT=30,SMTP_FROM_EMAIL=noreply@nexusintelligent.ai,SMTP_FROM_NAME=NexusIntelligent,EMAIL_WORKER_POLL_INTERVAL=10,EMAIL_WORKER_BATCH_SIZE=50,EMAIL_RETRY_MAX_ATTEMPTS=3,EMAIL_RETRY_BACKOFF_SECONDS=300,EMAIL_WORKER_CONCURRENCY=5,DB_POOL_SIZE_MIN=1,DB_POOL_SIZE_MAX=5,LOG_LEVEL=INFO,LOG_TO_FILE=false" \
    --set-secrets="DATABASE_URL=email-service-db-url:latest,SMTP_USER=email-smtp-user:latest,SMTP_PASSWORD=email-smtp-password:latest"

log_success "Deployment complete!"

# Step 4: Get service URL
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --format='value(status.url)')
echo ""
echo "============================================================"
echo -e "Service URL: ${GREEN}${SERVICE_URL}${NC}"
echo "============================================================"
echo ""
log_info "Test health endpoint:"
echo "  curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" ${SERVICE_URL}/health"
echo ""
log_warning "Remember to grant orchestrator-sa access if not done:"
echo "  gcloud run services add-iam-policy-binding ${SERVICE_NAME} \\"
echo "    --region=${REGION} \\"
echo "    --member='serviceAccount:orchestrator-sa@${PROJECT_ID}.iam.gserviceaccount.com' \\"
echo "    --role='roles/run.invoker'"
echo ""