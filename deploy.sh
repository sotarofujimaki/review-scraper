#!/bin/bash
set -e
cd "$(dirname "$0")"

REGION="asia-northeast1"
PROJECT="fujimaki-sandbox-484206"
SERVICE="review-scraper"
TAG="v$(date +%s)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy/${SERVICE}:${TAG}"

# 1. Cache bust + commit
date +%s > .build-timestamp
git add -A
git diff --cached --quiet || git commit -m "deploy: ${TAG}"
git push

# 2. Build with unique tag (kaniko, no-cache)
echo "🔨 ビルド中... (${IMAGE})"
gcloud config set builds/use_kaniko True 2>/dev/null
gcloud builds submit --tag "$IMAGE" --project "$PROJECT" --no-cache

# 3. Deploy fresh image
echo "🚀 デプロイ中..."
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --memory 4Gi \
  --cpu 2 \
  --timeout 1800 \
  --allow-unauthenticated \
  --concurrency 1 \
  --project "$PROJECT"

# 4. Force traffic to latest revision
LATEST=$(gcloud run revisions list --service "$SERVICE" --region "$REGION" --project "$PROJECT" --sort-by="~creationTimestamp" --limit=1 --format="value(name)" 2>/dev/null)
echo "🔀 トラフィック切替: ${LATEST}"
gcloud run services update-traffic "$SERVICE" \
  --to-revisions="${LATEST}=100" \
  --region "$REGION" \
  --project "$PROJECT"

echo "✅ デプロイ完了 (${LATEST})"
