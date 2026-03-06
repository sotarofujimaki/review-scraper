"""Google Maps review scraper using Scrapling StealthySession."""
from scrapling.fetchers import StealthySession
from scrapling.engines.toolbelt.fingerprints import generate_convincing_referer
import time
import subprocess
import re
import shutil
import glob


def _resolve_url(url: str) -> str:
    """Resolve short URLs and ensure full Google Maps URL format."""
    # Expand short URLs (maps.app.goo.gl, goo.gl)
    if "goo.gl/" in url or "maps.app.goo.gl/" in url:
        try:
            result = subprocess.run(
                ["curl", "-sI", "-L", url],
                capture_output=True, text=True, timeout=15
            )
            locations = re.findall(
                r'location:\s*(https://www\.google\.com/maps/place/[^\r\n]+)',
                result.stdout, re.IGNORECASE
            )
            if locations:
                url = locations[-1]
        except Exception:
            pass

    # Validate URL has coordinates (@lat,lng)
    if "/maps/place/" in url and "/@" not in url:
        raise ValueError(
            "URLに座標情報がありません。Google Mapsで店舗ページを開き、"
            "口コミタブをクリックした状態のURLを使用してください。"
            "または maps.app.goo.gl の短縮URLを使ってください。"
        )

    return url


def _clean_browser_profiles():
    """Clean up old browser profiles to avoid detection."""
    import tempfile
    tmp = tempfile.gettempdir()
    for pattern in ["patchright*", "playwright*"]:
        for path in glob.glob(f"{tmp}/{pattern}"):
            try:
                shutil.rmtree(path, ignore_errors=True)
            except Exception:
                pass


def _ensure_reviews_tab(url: str) -> str:
    """Ensure URL has !9m1!1b1 parameter to show reviews tab by default."""
    if "!9m1!1b1" not in url:
        if "/data=" in url:
            url = url.replace("/data=", "/data=!9m1!1b1")
        else:
            sep = "&" if "?" in url else "?"
            url = url + sep + "data=!9m1!1b1"
    return url


def scrape_gmap_reviews(url: str) -> list[dict]:
    """Scrape all reviews from a Google Maps URL.

    Uses StealthySession with direct Playwright page manipulation.
    Includes retry logic (up to 5 attempts) for the ~30% failure rate.
    """
    url = _resolve_url(url)
    url = _ensure_reviews_tab(url)
    _clean_browser_profiles()
    session = None
    try:
        page, session = _start_session(url)
        return _collect_all_reviews(page)
    finally:
        if session:
            try:
                session.close()
            except Exception:
                pass


def _start_session(url: str):
    """Start a StealthySession and navigate to the URL with retries."""
    for retry in range(5):
        session = StealthySession(headless=True)
        session.start()
        page = (
            session.context.pages[0]
            if session.context.pages
            else session.context.new_page()
        )

        # Block heavy resources to save memory
        page.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,mp4,mp3}",
            lambda route: route.abort(),
        )

        referer = generate_convincing_referer(url)
        page.goto(
            url, referer=referer, wait_until="domcontentloaded", timeout=60000
        )

        # Poll for review elements (wait_for_selector is unreliable)
        found = False
        for _ in range(20):
            if page.query_selector_all(".wiI7pd"):
                found = True
                break
            time.sleep(2)

        if found:
            return page, session

        try:
            session.close()
        except Exception:
            pass

    raise RuntimeError("Failed to load Google Maps reviews after 5 retries")


def _extract_reviews_from_dom(page, saved_ids: set) -> list[dict]:
    """Extract unsaved reviews currently in the DOM."""
    blocks = page.query_selector_all("[data-review-id]")
    new_reviews = []
    for block in blocks:
        try:
            rid = block.get_attribute("data-review-id")
            if not rid or rid in saved_ids:
                continue

            # Expand "More" button
            more = block.query_selector("button.w8nwRe")
            if more:
                try:
                    more.click()
                    time.sleep(0.08)
                except Exception:
                    pass

            author_el = block.query_selector(".d4r55")
            rating_el = block.query_selector(".kvMYJc")
            date_el = block.query_selector(".rsqaWe")
            text_el = block.query_selector(".wiI7pd")

            author = (author_el.text_content() or "").strip() if author_el else ""
            rating = (
                (rating_el.get_attribute("aria-label") or "").strip()
                if rating_el
                else ""
            )
            date = (date_el.text_content() or "").strip() if date_el else ""
            comment = (text_el.text_content() or "").strip() if text_el else ""

            if comment:
                new_reviews.append(
                    {
                        "review_id": rid,
                        "author": author,
                        "rating": rating,
                        "date": date,
                        "comment": comment,
                    }
                )
                saved_ids.add(rid)
        except Exception:
            continue
    return new_reviews


def _cleanup_heavy_elements(page):
    """Remove heavy child elements (images etc.) but keep review blocks."""
    page.evaluate(
        """() => {
        document.querySelectorAll('[data-review-id] img, [data-review-id] picture, [data-review-id] svg').forEach(el => el.remove());
        document.querySelectorAll('canvas, .Tya61d, .p0Aybe, .cYrDcb').forEach(el => el.remove());
    }"""
    )


def _scroll_reviews(page):
    """Scroll the reviews container to load more."""
    page.evaluate(
        """() => {
        const els = document.querySelectorAll('div.m6QErb');
        for (const el of els) {
            if (el.scrollHeight > el.clientHeight && el.scrollHeight > 500) {
                el.scrollTop = el.scrollHeight;
            }
        }
    }"""
    )


def _collect_all_reviews(page) -> list[dict]:
    """Scroll through all reviews and collect them incrementally."""
    saved_ids: set = set()
    all_reviews: list[dict] = []

    # Initial collection
    all_reviews.extend(_extract_reviews_from_dom(page, saved_ids))

    # Scroll loop
    no_new = 0
    for i in range(2000):
        _scroll_reviews(page)
        time.sleep(1.0)

        # Every 3 scrolls: save + cleanup
        if i % 3 == 2:
            new = _extract_reviews_from_dom(page, saved_ids)
            all_reviews.extend(new)
            _cleanup_heavy_elements(page)
            if len(new) == 0:
                no_new += 1
            else:
                no_new = 0

        # 20 consecutive rounds with no new reviews -> done
        if no_new >= 20:
            final = _extract_reviews_from_dom(page, saved_ids)
            all_reviews.extend(final)
            break

    return all_reviews
