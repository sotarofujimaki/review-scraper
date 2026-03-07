#!/bin/bash
gcloud tasks queues create review-scraper-queue \
  --location=asia-northeast1 \
  --max-concurrent-dispatches=3 \
  --max-dispatches-per-second=1 \
  --max-attempts=1 \
  --project=fujimaki-sandbox-484206
