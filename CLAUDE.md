# Review Scraper API

## Goal
Build a FastAPI web service that scrapes reviews from Google Maps and TripAdvisor.
Deploy on Google Cloud Run.

## API Design
- `POST /scrape` with JSON body `{"url": "...", "source": "gmap|tripadvisor"}`
- Returns JSON array of reviews: `[{"review_id": "...", "author": "...", "rating": "...", "date": "...", "comment": "..."}]`
- Also support `?format=csv` to return CSV file

## Technical Requirements
- Use Scrapling library (`scrapling[all]`) for scraping
- Read `REFERENCE.md` for the working patterns (critical bugs and workarounds documented there)
- Read `reference_gmap.py` and `reference_tripadvisor.py` for working implementations
- Google Maps: Use `StealthySession` directly with Playwright page manipulation (NOT page_action parameter)
- TripAdvisor: Use `StealthyFetcher` with pagination
- Include retry logic (30% failure rate on Google Maps)
- Incremental collection with memory management for large review counts

## Stack
- Python 3.10+
- FastAPI + uvicorn
- Scrapling[all]
- Dockerfile with Chromium

## Files to Create
- `main.py` - FastAPI app
- `scraper/gmap.py` - Google Maps scraper
- `scraper/tripadvisor.py` - TripAdvisor scraper  
- `Dockerfile`
- `requirements.txt`
- `README.md`
- `.dockerignore`

## Important
- Do NOT use `page_action` parameter with Scrapling fetchers (causes Google Maps reviews to disappear)
- Use `generate_convincing_referer()` for Google Maps
- Use `headless=True` always
- Block images via `page.route()` for memory savings
- CSV encoding: `utf-8-sig` (BOM for Excel)
