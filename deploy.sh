#!/bin/bash
set -e
cd "$(dirname "$0")"

REGION="asia-northeast1"
PROJECT="fujimaki-sandbox-484206"
SERVICE="review-scraper"
REPO="cloud-run-source-deploy"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:$(date +%s)"

# 1. Cache bust
date +%s > .build-timestamp
git add .build-timestamp
git diff --cached --quiet || git commit -m "deploy: cache bust $(date +%Y%m%d-%H%M%S)"
git push

# 2. Build with unique tag (no cache reuse)
echo "🔨 ビルド中... (image: $IMAGE)"
gcloud builds submit --tag "$IMAGE" --project "$PROJECT"

# 3. Deploy the freshly built image
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

echo "✅ デプロイ完了"
