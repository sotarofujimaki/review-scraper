"""Centralized configuration. All magic numbers and tunable values live here."""
import os

# --- Retry & Timeout ---
MAX_RETRIES = 5
JOB_TIMEOUT_SECONDS = 1800        # 10 min overall job timeout
STALE_JOB_MINUTES = 30           # Mark running jobs older than this as failed on startup
DUPLICATE_URL_MINUTES = 5        # Reject same URL within this window

# --- Google Maps ---
GOOGLE_PAGE_TIMEOUT_MS = 60_000  # 60s
GOOGLE_WARMUP_TIMEOUT_MS = 30_000  # 15s (was 30s)
GOOGLE_TAB_WAIT_SECONDS = 5     # 5s (was 8s)     # Wait after domcontentloaded for dynamic content
GOOGLE_SCROLL_INTERVAL_MIN = 1.5   # ランダムスクロール間隔（秒）
GOOGLE_SCROLL_INTERVAL_MAX = 2.5
GOOGLE_WARMUP_DELAY_MIN = 2.0     # warm-up間のランダム遅延（秒）
GOOGLE_WARMUP_DELAY_MAX = 5.0
GOOGLE_STALL_SECONDS = 120       # No new reviews for this long → finish
GOOGLE_NO_NEW_THRESHOLD = 5     # Consecutive empty scroll rounds → finish
GOOGLE_MAX_SCROLLS = 2000

# --- TripAdvisor ---
TA_PAGE_TIMEOUT_MS = 30_000
TA_CARD_WAIT_SECONDS = 8        # Max seconds to wait for cards after navigation
TA_REVIEWS_PER_PAGE = 15
TA_MAX_PAGES = 30
TA_MAX_TIME_SECONDS = 1800      # 30 min

# --- Tor ---
TOR_SOCKS_HOST = "127.0.0.1"
TOR_SOCKS_PORT = 9050
TOR_PROXY_URL = f"socks5://{TOR_SOCKS_HOST}:{TOR_SOCKS_PORT}"
TOR_CIRCUIT_WAIT = 3            # Seconds to wait after SIGHUP


# --- Blocked ad/tracking domains ---
BLOCKED_DOMAINS_GOOGLE = {"doubleclick.net", "googlesyndication.com", "googleadservices.com", "google-analytics.com", "googletagmanager.com"}
BLOCKED_DOMAINS_TA = {"doubleclick.net", "googlesyndication.com", "google-analytics.com", "googletagmanager.com", "facebook.com", "facebook.net"}

# --- Paths ---
GOOGLE_PROFILE_BASE = os.environ.get("GOOGLE_PROFILE_BASE", "/tmp/google-profiles")

# --- Firestore ---
FIRESTORE_COLLECTION = "scrape_jobs"
FIRESTORE_BATCH_SIZE = 450      # Max docs per Firestore batch (limit is 500)

# --- Viewport randomization ---
GOOGLE_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 720},
    {"width": 1600, "height": 900},
]

# --- Cloud Tasks ---
CLOUD_TASKS_QUEUE = os.environ.get("CLOUD_TASKS_QUEUE", "review-scraper-queue")
CLOUD_TASKS_LOCATION = os.environ.get("CLOUD_TASKS_LOCATION", "asia-northeast1")
GCP_PROJECT = os.environ.get("GCP_PROJECT", "fujimaki-sandbox-484206")
SERVICE_URL = os.environ.get("SERVICE_URL", "https://review-scraper-kkp4ztvbxa-an.a.run.app")
