#!/bin/bash
# =============================================================================
# GCP Initial Setup Script for Email Service
# =============================================================================
# This script sets up all required GCP infrastructure for the email service.
# Run this ONCE before the first deployment.
#
# Prerequisites:
#   - Google Cloud SDK installed (gcloud)
#   - Authenticated with: gcloud auth login
#   - Billing enabled on the project
#
# Usage:
#   chmod +x deploy/setup-gcp.sh
#   ./deploy/setup-gcp.sh
#
# Best Practices Applied:
#   - Principle of least privilege for IAM roles
#   - No service account keys (uses Workload Identity)
#   - Secrets stored in Secret Manager
#   - Idempotent operations (safe to re-run)
# =============================================================================

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# =============================================================================
# CONFIGURATION
# =============================================================================
PROJECT_ID="gen-lang-client-0329024102"
REGION="us-central1"
SERVICE_NAME="email-service"
REPO_NAME="email-repo"
SA_NAME="email-service-sa"
GITHUB_REPO="javierjortiz82/email-service"

# Cloud SQL instance (shared with other services)
CLOUD_SQL_INSTANCE="demo-db"
CLOUD_SQL_CONNECTION="${PROJECT_ID}:${REGION}:${CLOUD_SQL_INSTANCE}"

# Orchestrator Service Account (for service-to-service calls)
ORCHESTRATOR_SA="orchestrator-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Output file for setup results
OUTPUT_FILE="deploy/.gcp-setup-output.txt"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "\n${CYAN}--- $1 ---${NC}"; }

check_command() {
    if ! command -v "$1" &> /dev/null; then
        log_error "$1 is not installed. Please install it first."
        exit 1
    fi
}

# Check if resource exists (returns 0 if exists)
resource_exists() {
    local type=$1
    shift
    case $type in
        "service-account")
            gcloud iam service-accounts describe "$1" &>/dev/null
            ;;
        "artifact-repo")
            gcloud artifacts repositories describe "$1" --location="$2" &>/dev/null
            ;;
        "secret")
            gcloud secrets describe "$1" &>/dev/null
            ;;
        "wif-pool")
            gcloud iam workload-identity-pools describe "$1" --location=global &>/dev/null
            ;;
        "wif-provider")
            gcloud iam workload-identity-pools providers describe "$1" \
                --workload-identity-pool="$2" --location=global &>/dev/null
            ;;
    esac
}

# =============================================================================
# PRE-FLIGHT CHECKS
# =============================================================================
echo ""
echo "============================================================"
echo "       GCP Setup for Email Service                          "
echo "       Project: $PROJECT_ID                                 "
echo "============================================================"
echo ""

log_step "Pre-flight Checks"

check_command gcloud

# Verify authentication
CURRENT_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | head -n1)
if [ -z "$CURRENT_ACCOUNT" ]; then
    log_error "Not authenticated. Run: gcloud auth login"
    exit 1
fi
log_success "Authenticated as: $CURRENT_ACCOUNT"

# Set and verify project
gcloud config set project "$PROJECT_ID" --quiet
if ! gcloud projects describe "$PROJECT_ID" &>/dev/null; then
    log_error "Project $PROJECT_ID not found or no access"
    exit 1
fi
log_success "Project: $PROJECT_ID"

# Get project number (needed for WIF)
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
log_success "Project Number: $PROJECT_NUMBER"

# =============================================================================
# STEP 1: Enable Required APIs
# =============================================================================
log_step "Step 1/7: Enabling APIs"

APIS=(
    "run.googleapis.com"              # Cloud Run
    "artifactregistry.googleapis.com" # Artifact Registry
    "cloudbuild.googleapis.com"       # Cloud Build
    "iam.googleapis.com"              # IAM
    "iamcredentials.googleapis.com"   # IAM Credentials (for WIF)
    "cloudresourcemanager.googleapis.com"  # Resource Manager
    "secretmanager.googleapis.com"    # Secret Manager
    "sqladmin.googleapis.com"         # Cloud SQL Admin
)

for api in "${APIS[@]}"; do
    if gcloud services list --enabled --filter="name:$api" --format="value(name)" | grep -q "$api"; then
        log_success "$api (already enabled)"
    else
        log_info "Enabling $api..."
        gcloud services enable "$api" --quiet
        log_success "$api"
    fi
done

# =============================================================================
# STEP 2: Create Artifact Registry
# =============================================================================
log_step "Step 2/7: Artifact Registry"

if resource_exists artifact-repo "$REPO_NAME" "$REGION"; then
    log_success "Repository '$REPO_NAME' already exists"
else
    log_info "Creating repository..."
    gcloud artifacts repositories create "$REPO_NAME" \
        --repository-format=docker \
        --location="$REGION" \
        --description="Email Service Docker images"
    log_success "Repository '$REPO_NAME' created"
fi

# =============================================================================
# STEP 3: Create Service Account
# =============================================================================
log_step "Step 3/7: Service Account & IAM"

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if resource_exists service-account "$SA_EMAIL"; then
    log_success "Service account '$SA_NAME' already exists"
else
    gcloud iam service-accounts create "$SA_NAME" \
        --display-name="Email Service Account" \
        --description="Service account for email-service Cloud Run"
    log_success "Service account '$SA_NAME' created"
fi

# Grant minimal required roles (principle of least privilege)
ROLES=(
    "roles/logging.logWriter"            # Write logs
    "roles/monitoring.metricWriter"      # Write metrics
    "roles/cloudsql.client"              # Connect to Cloud SQL
    "roles/secretmanager.secretAccessor" # Access secrets
)

log_info "Granting IAM roles..."
for role in "${ROLES[@]}"; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="$role" \
        --condition=None \
        --quiet &>/dev/null
done
log_success "IAM roles granted (${#ROLES[@]} roles)"

# Allow SA to act as itself (required for Cloud Run deployment)
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
    --role="roles/iam.serviceAccountUser" \
    --member="serviceAccount:${SA_EMAIL}" \
    --quiet &>/dev/null
log_success "Service account self-impersonation enabled"

# =============================================================================
# STEP 4: Grant orchestrator-sa Invoker Role
# =============================================================================
log_step "Step 4/7: Orchestrator Access"

# This will be applied after the service is deployed
log_info "Note: After deployment, run this to grant orchestrator access:"
echo "  gcloud run services add-iam-policy-binding ${SERVICE_NAME} \\"
echo "    --region=${REGION} \\"
echo "    --member='serviceAccount:${ORCHESTRATOR_SA}' \\"
echo "    --role='roles/run.invoker'"
log_warning "Save this command for post-deployment"

# =============================================================================
# STEP 5: Create Secrets in Secret Manager
# =============================================================================
log_step "Step 5/7: Secret Manager"

declare -A SECRETS=(
    ["email-service-db-url"]="PostgreSQL connection URL for email service"
    ["email-smtp-user"]="SMTP username (email address)"
    ["email-smtp-password"]="SMTP password (app password)"
)

for secret_name in "${!SECRETS[@]}"; do
    if resource_exists secret "$secret_name"; then
        log_success "Secret '$secret_name' already exists"
    else
        log_info "Creating secret '$secret_name'..."
        echo "PLACEHOLDER_VALUE" | gcloud secrets create "$secret_name" \
            --data-file=- \
            --replication-policy="automatic"
        log_success "Secret '$secret_name' created"
        log_warning "Remember to update with actual value!"
    fi

    # Grant access to service account
    gcloud secrets add-iam-policy-binding "$secret_name" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="roles/secretmanager.secretAccessor" \
        --quiet &>/dev/null
done

log_info ""
log_info "To update secrets with actual values:"
echo "  echo 'postgresql://user:pass@/dbname?host=/cloudsql/${CLOUD_SQL_CONNECTION}' | \\"
echo "    gcloud secrets versions add email-service-db-url --data-file=-"
echo ""
echo "  echo 'your-smtp-email@gmail.com' | \\"
echo "    gcloud secrets versions add email-smtp-user --data-file=-"
echo ""
echo "  echo 'your-app-password' | \\"
echo "    gcloud secrets versions add email-smtp-password --data-file=-"

# =============================================================================
# STEP 6: Workload Identity Federation (GitHub Actions)
# =============================================================================
log_step "Step 6/7: Workload Identity Federation"

WIF_POOL="github-pool"
WIF_PROVIDER="github-provider"

# Create Workload Identity Pool (or use existing)
if resource_exists wif-pool "$WIF_POOL"; then
    log_success "Pool '$WIF_POOL' already exists"
else
    gcloud iam workload-identity-pools create "$WIF_POOL" \
        --location="global" \
        --description="GitHub Actions authentication pool" \
        --display-name="GitHub Actions"
    log_success "Pool '$WIF_POOL' created"
fi

# Create OIDC Provider (or use existing)
if resource_exists wif-provider "$WIF_PROVIDER" "$WIF_POOL"; then
    log_success "Provider '$WIF_PROVIDER' already exists"
else
    gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER" \
        --location="global" \
        --workload-identity-pool="$WIF_POOL" \
        --display-name="GitHub OIDC" \
        --issuer-uri="https://token.actions.githubusercontent.com" \
        --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
        --attribute-condition="assertion.repository_owner=='javierjortiz82'"
    log_success "Provider '$WIF_PROVIDER' created"
fi

# Allow GitHub repo to impersonate service account
WIF_MEMBER="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/attribute.repository/${GITHUB_REPO}"

gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
    --role="roles/iam.workloadIdentityUser" \
    --member="$WIF_MEMBER" \
    --quiet &>/dev/null
log_success "GitHub repo authorized: $GITHUB_REPO"

WIF_PROVIDER_FULL="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/providers/${WIF_PROVIDER}"

# Grant Cloud Build permissions
CLOUD_BUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${CLOUD_BUILD_SA}" \
    --role="roles/run.developer" \
    --quiet &>/dev/null
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${CLOUD_BUILD_SA}" \
    --role="roles/artifactregistry.writer" \
    --quiet &>/dev/null
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
    --role="roles/iam.serviceAccountUser" \
    --member="serviceAccount:${CLOUD_BUILD_SA}" \
    --quiet &>/dev/null
log_success "Cloud Build permissions configured"

# =============================================================================
# STEP 7: Configure Docker
# =============================================================================
log_step "Step 7/7: Docker Configuration"

gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
log_success "Docker configured for Artifact Registry"

# =============================================================================
# SAVE OUTPUT
# =============================================================================
cat > "$OUTPUT_FILE" << EOF
# =============================================================================
# GCP Setup Output - Generated $(date)
# =============================================================================
# IMPORTANT: Keep this file secure! Contains configuration information.
# This file is gitignored.
# =============================================================================

# GitHub Actions Secrets (copy these to your repository settings)
# Repository: https://github.com/${GITHUB_REPO}/settings/secrets/actions

GCP_PROJECT_ID=${PROJECT_ID}
GCP_REGION=${REGION}
GCP_SA_EMAIL=${SA_EMAIL}
GCP_WORKLOAD_IDENTITY_PROVIDER=${WIF_PROVIDER_FULL}

# Service Configuration
SERVICE_NAME=${SERVICE_NAME}
REPO_NAME=${REPO_NAME}
CLOUD_SQL_CONNECTION=${CLOUD_SQL_CONNECTION}

# =============================================================================
# Post-Deployment Commands
# =============================================================================
# 1. Grant orchestrator-sa access to invoke this service:
#    gcloud run services add-iam-policy-binding ${SERVICE_NAME} \\
#      --region=${REGION} \\
#      --member='serviceAccount:${ORCHESTRATOR_SA}' \\
#      --role='roles/run.invoker'

# 2. Update secrets with actual values (see Step 5 output above)

# 3. Get service URL after deployment:
#    gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format='value(status.url)'

# =============================================================================
EOF

# Add to .gitignore if not present
if [ -f .gitignore ]; then
    if ! grep -q ".gcp-setup-output.txt" .gitignore 2>/dev/null; then
        echo "deploy/.gcp-setup-output.txt" >> .gitignore
        log_info "Added output file to .gitignore"
    fi
fi

# =============================================================================
# FINAL SUMMARY
# =============================================================================
echo ""
echo "============================================================"
echo "                    Setup Complete!                         "
echo "============================================================"
echo ""
echo -e "${CYAN}GitHub Actions Secrets${NC} (add to repository settings):"
echo "------------------------------------------------------------"
echo ""
echo -e "${GREEN}GCP_PROJECT_ID${NC}="
echo "  $PROJECT_ID"
echo ""
echo -e "${GREEN}GCP_REGION${NC}="
echo "  $REGION"
echo ""
echo -e "${GREEN}GCP_SA_EMAIL${NC}="
echo "  $SA_EMAIL"
echo ""
echo -e "${GREEN}GCP_WORKLOAD_IDENTITY_PROVIDER${NC}="
echo "  $WIF_PROVIDER_FULL"
echo ""
echo "------------------------------------------------------------"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo "1. Update secrets with actual values (see commands above)"
echo ""
echo "2. Add GitHub secrets:"
echo "   https://github.com/${GITHUB_REPO}/settings/secrets/actions"
echo ""
echo "3. Deploy with Cloud Build:"
echo "   gcloud builds submit --config=cloudbuild.yaml"
echo ""
echo "4. After deployment, grant orchestrator access (see saved command)"
echo ""
echo -e "${GREEN}Output saved to:${NC} $OUTPUT_FILE"
echo ""