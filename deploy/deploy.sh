#!/usr/bin/env bash
# Deploys AsobiAgent to its own Google Cloud project (see docs/DEPLOYMENT.md for what each step is).
#
#   PROJECT_ID=asobi-agent-xxxx ./deploy/deploy.sh setup     # once: project, billing, budgets, APIs, Firestore, secrets
#   PROJECT_ID=asobi-agent-xxxx ./deploy/deploy.sh app       # every code change: build + deploy the bot
#   PROJECT_ID=asobi-agent-xxxx ./deploy/deploy.sh agent     # build + deploy the form agent job
#   PROJECT_ID=asobi-agent-xxxx ./deploy/deploy.sh secrets   # after changing a key in .env
#   PROJECT_ID=asobi-agent-xxxx ./deploy/deploy.sh webhook   # point LINE at the bot
#
# Every command names the project explicitly: this Mac's gcloud default is the hackathon project.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID, e.g. PROJECT_ID=asobi-agent-xxxx}"
REGION=asia-northeast1
BILLING_ACCOUNT="${BILLING_ACCOUNT:-012F2F-99D2FB-931A00}"
SERVICE=asobi-agent
JOB=asobi-form-agent
REPO=asobi
WEB_SA="asobi-web@${PROJECT_ID}.iam.gserviceaccount.com"
JOB_SA="asobi-form-agent@${PROJECT_ID}.iam.gserviceaccount.com"
P=(--project="${PROJECT_ID}")
PY=.venv/bin/python

# secret name → .env variable
SECRETS=(
  "app-secret:APP_SECRET"
  "admin-api-token:ADMIN_API_TOKEN"
  "line-channel-secret:LINE_CHANNEL_SECRET"
  "line-channel-access-token:LINE_CHANNEL_ACCESS_TOKEN"
  "line-admin-user-id:LINE_ADMIN_USER_ID"
  "gmi-api-key:GMI_API_KEY"
  "ekispert-api-key:EKISPERT_API_ACCESS_KEY"
  "hotpepper-api-key:HOTPEPPER_API_KEY"
  "places-api-key:GOOGLE_PLACES_API_KEY"
)
TTL_COLLECTIONS=(groups plans invites events daily agent_runs cache_station cache_station_code cache_hotpepper cache_shop cache_hub)

env_value() {  # prints a .env value without a trailing newline (never echoed to the terminal by this script)
  "$PY" -I -c "import sys; from dotenv import dotenv_values; sys.stdout.write(dotenv_values('.env').get(sys.argv[1]) or '')" "$1"
}

secret_has_version() {
  gcloud secrets versions list "$1" "${P[@]}" --filter="state=ENABLED" --format="value(name)" --limit=1 2>/dev/null | grep -q .
}

secret_matches_env() {  # compares hashes only, so neither value is ever shown
  [ "$(gcloud secrets versions access latest --secret="$1" "${P[@]}" 2>/dev/null | shasum)" = "$(env_value "$2" | shasum)" ]
}

put_secret() {  # put_secret NAME VALUE_COMMAND...  (value comes from stdin of the command)
  local name=$1; shift
  gcloud secrets describe "$name" "${P[@]}" >/dev/null 2>&1 || gcloud secrets create "$name" "${P[@]}" --replication-policy=automatic --quiet
  "$@" | gcloud secrets versions add "$name" "${P[@]}" --data-file=- --quiet >/dev/null
  echo "  secret $name: new version"
}

base_url() {
  local number
  number=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
  echo "https://${SERVICE}-${number}.${REGION}.run.app"
}

setup() {
  echo "== project and billing"
  gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1 || gcloud projects create "$PROJECT_ID" --name="AsobiAgent"
  gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"

  echo "== APIs"
  gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
    firestore.googleapis.com secretmanager.googleapis.com iam.googleapis.com places.googleapis.com \
    apikeys.googleapis.com billingbudgets.googleapis.com "${P[@]}"

  echo "== budgets (email alerts only; they don't stop anything)"
  if ! gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" --format="value(displayName)" | grep -q "AsobiAgent credit burn"; then
    gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" --display-name="AsobiAgent credit burn" \
      --budget-amount=1000JPY --filter-projects="projects/${PROJECT_ID}" --credit-types-treatment=EXCLUDE_ALL_CREDITS \
      --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
  fi
  if ! gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" --format="value(displayName)" | grep -q "AsobiAgent real money"; then
    gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" --display-name="AsobiAgent real money" \
      --budget-amount=100JPY --filter-projects="projects/${PROJECT_ID}" --credit-types-treatment=INCLUDE_ALL_CREDITS \
      --threshold-rule=percent=1.0
  fi

  echo "== Firestore (Tokyo) and auto-delete (TTL) on expire_at"
  gcloud firestore databases describe --database="(default)" "${P[@]}" >/dev/null 2>&1 || \
    gcloud firestore databases create --location="$REGION" --type=firestore-native "${P[@]}"
  for c in "${TTL_COLLECTIONS[@]}"; do
    gcloud firestore fields ttls update expire_at --collection-group="$c" --enable-ttl --async --quiet "${P[@]}" >/dev/null
  done

  echo "== image storage (keeps the 3 newest images)"
  gcloud artifacts repositories describe "$REPO" --location="$REGION" "${P[@]}" >/dev/null 2>&1 || \
    gcloud artifacts repositories create "$REPO" --repository-format=docker --location="$REGION" "${P[@]}"
  gcloud artifacts repositories set-cleanup-policies "$REPO" --location="$REGION" --no-dry-run \
    --policy=deploy/artifact-cleanup.json "${P[@]}" >/dev/null

  echo "== service accounts"
  gcloud iam service-accounts describe "$WEB_SA" "${P[@]}" >/dev/null 2>&1 || \
    gcloud iam service-accounts create asobi-web --display-name="AsobiAgent bot" "${P[@]}"
  gcloud iam service-accounts describe "$JOB_SA" "${P[@]}" >/dev/null 2>&1 || \
    gcloud iam service-accounts create asobi-form-agent --display-name="AsobiAgent form agent" "${P[@]}"
  for sa in "$WEB_SA" "$JOB_SA"; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$sa" --role=roles/datastore.user \
      --condition=None --quiet >/dev/null
  done

  echo "== Places API key (restricted to Places API)"
  if ! secret_has_version places-api-key 2>/dev/null; then
    local uid
    uid=$(gcloud services api-keys list "${P[@]}" --filter='displayName="AsobiAgent Places"' --format="value(uid)" | head -1)
    if [ -z "$uid" ]; then
      gcloud services api-keys create --display-name="AsobiAgent Places" \
        --api-target=service=places.googleapis.com "${P[@]}" >/dev/null
      uid=$(gcloud services api-keys list "${P[@]}" --filter='displayName="AsobiAgent Places"' --format="value(uid)" | head -1)
    fi
    put_secret places-api-key sh -c "gcloud services api-keys get-key-string $uid --project=$PROJECT_ID --format='value(keyString)' | tr -d '\n'"
  fi

  secrets
}

secrets() {
  echo "== secrets from .env"
  for pair in "${SECRETS[@]}"; do
    local name=${pair%%:*} var=${pair##*:}
    if [ "$name" = "places-api-key" ] && secret_has_version places-api-key; then continue; fi
    if [ -n "$(env_value "$var")" ]; then
      if secret_matches_env "$name" "$var"; then echo "  secret $name: unchanged"; continue; fi
      put_secret "$name" env_value "$var"
    elif [ "$name" = "app-secret" ] || [ "$name" = "admin-api-token" ]; then
      secret_has_version "$name" || put_secret "$name" sh -c "openssl rand -base64 36 | tr -d '\n'"
    else
      echo "  $var is empty in .env; skipping $name"
    fi
  done
  for pair in "${SECRETS[@]}"; do
    local name=${pair%%:*}
    gcloud secrets describe "$name" "${P[@]}" >/dev/null 2>&1 || continue
    gcloud secrets add-iam-policy-binding "$name" --member="serviceAccount:$WEB_SA" \
      --role=roles/secretmanager.secretAccessor --condition=None --quiet "${P[@]}" >/dev/null
  done
  for name in app-secret gmi-api-key; do
    gcloud secrets add-iam-policy-binding "$name" --member="serviceAccount:$JOB_SA" \
      --role=roles/secretmanager.secretAccessor --condition=None --quiet "${P[@]}" >/dev/null
  done
}

secret_flags() {
  local flags=() pair name var
  for pair in "${SECRETS[@]}"; do
    name=${pair%%:*}; var=${pair##*:}
    secret_has_version "$name" && flags+=("${var}=${name}:latest")
  done
  local IFS=,
  echo "${flags[*]}"
}

app() {
  local tag image url
  tag=$(git rev-parse --short HEAD)$(git diff --quiet || echo "-dirty")
  image="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/web:${tag}-$(date +%s)"
  url=$(base_url)
  echo "== build $image"
  gcloud builds submit . --tag="$image" --region="$REGION" "${P[@]}"
  echo "== deploy $SERVICE → $url"
  gcloud run deploy "$SERVICE" --image="$image" --region="$REGION" "${P[@]}" \
    --service-account="$WEB_SA" --allow-unauthenticated \
    --min-instances=0 --max-instances=3 --concurrency=40 --cpu=1 --memory=512Mi --timeout=60 \
    --set-env-vars="STORE_BACKEND=firestore,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},REGION=${REGION},FORM_AGENT_MODE=job,FORM_AGENT_JOB=${JOB},LINE_BOT_BASIC_ID=$(env_value LINE_BOT_BASIC_ID),PUBLIC_BASE_URL=${url},GMI_MODEL=$(env_value GMI_MODEL)" \
    --set-secrets="$(secret_flags)"
  echo "Live: $url  (webhook: $url/webhook, privacy policy: $url/privacy)"
}

agent() {
  local image url
  image="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/form-agent:$(date +%s)"
  url=$(base_url)
  echo "== build $image (Playwright + Chromium, takes a few minutes)"
  gcloud builds submit . --config=deploy/cloudbuild-form-agent.yaml --substitutions="_IMAGE=${image}" \
    --region="$REGION" "${P[@]}"
  gcloud run jobs deploy "$JOB" --image="$image" --region="$REGION" "${P[@]}" \
    --service-account="$JOB_SA" --task-timeout=180s --max-retries=0 --cpu=1 --memory=2Gi \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},PUBLIC_BASE_URL=${url},GMI_MODEL=$(env_value GMI_MODEL)" \
    --set-secrets="APP_SECRET=app-secret:latest,GMI_API_KEY=gmi-api-key:latest"
  gcloud run jobs add-iam-policy-binding "$JOB" --region="$REGION" "${P[@]}" \
    --member="serviceAccount:$WEB_SA" --role=roles/run.jobsExecutorWithOverrides --quiet >/dev/null
  echo "Form agent job ready."
}

webhook() {
  "$PY" -m deploy.set_webhook "$(base_url)/webhook"
}

case "${1:-}" in
  setup) setup ;;
  secrets) secrets ;;
  app) app ;;
  agent) agent ;;
  webhook) webhook ;;
  all) setup; app; agent; webhook ;;
  *) echo "usage: PROJECT_ID=... $0 setup|secrets|app|agent|webhook|all"; exit 1 ;;
esac
