"""Centralized configuration. All magic numbers and tunable values live here."""
import os

# --- Retry & Timeout ---
MAX_RETRIES = 5
JOB_TIMEOUT_SECONDS = 600        # 10 min overall job timeout
STALE_JOB_MINUTES = 30           # Mark running jobs older than this as failed on startup
DUPLICATE_URL_MINUTES = 5        # Reject same URL within this window

# --- Google Maps ---
GOOGLE_PAGE_TIMEOUT_MS = 90_000  # Page load timeout
GOOGLE_WARMUP_TIMEOUT_MS = 30_000
GOOGLE_TAB_WAIT_SECONDS = 8     # Wait after domcontentloaded for dynamic content
GOOGLE_SCROLL_INTERVAL = 1.0
GOOGLE_STALL_SECONDS = 60       # No new reviews for this long → finish
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

# --- Paths ---
GOOGLE_PROFILE_BASE = os.environ.get("GOOGLE_PROFILE_BASE", "/tmp/google-profiles")

# --- Firestore ---
FIRESTORE_COLLECTION = "scrape_jobs"
FIRESTORE_BATCH_SIZE = 450      # Max docs per Firestore batch (limit is 500)
