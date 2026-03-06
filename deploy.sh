#!/bin/bash
set -e
cd "$(dirname "$0")"

# キャッシュバスト: タイムスタンプ更新
date +%s > .build-timestamp
git add .build-timestamp
git diff --cached --quiet || git commit -m "deploy: cache bust $(date +%Y%m%d-%H%M%S)"
git push

echo "🚀 デプロイ開始..."
gcloud run deploy review-scraper \
  --source . \
  --region asia-northeast1 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 1800 \
  --allow-unauthenticated \
  --concurrency 1 \
  --project fujimaki-sandbox-484206

echo "✅ デプロイ完了"
