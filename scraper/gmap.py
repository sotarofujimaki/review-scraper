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
    if "goo.gl/" in url or "maps.app.goo.gl/" in url or "share.google/" in url:
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



    return url


def _resolve_share_url_in_browser(page, url: str) -> str:
    """Resolve share.google URLs using the browser (JS redirect)."""
    if "share.google" not in url:
        return url
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)
        final_url = page.url
        if "google.com/maps" in final_url or "google.co.jp/maps" in final_url:
            return final_url
    except Exception:
        pass
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


def scrape_gmap_reviews(url: str, progress_callback=None) -> list[dict]:
    """Scrape all reviews from a Google Maps URL.

    Uses StealthySession with direct Playwright page manipulation.
    Includes retry logic (up to 5 attempts) for the ~30% failure rate.
    """
    url = _resolve_url(url)
    url = _ensure_reviews_tab(url)
    _clean_browser_profiles()
    # Validate domain
    if not any(d in url.lower() for d in ["google.com/maps", "google.co.jp/maps", "maps.app.goo.gl", "maps.google", "share.google"]):
        raise ValueError("Google MapsのURLを入力してください")

    session = None
    try:
        page, session = _start_session(url)
        return _collect_all_reviews(page, progress_callback)
    finally:
        if session:
            try:
                session.close()
            except Exception:
                pass


PROFILE_DIR = "/tmp/gmap-browser-profile"


def _warm_up_session(page, session):
    """Visit Google properties to accumulate cookies for trust score."""
    try:
        cookies = session.context.cookies()
        google_cookies = [c for c in cookies if "google" in c.get("domain", "")]
        if google_cookies:
            return  # Already has Google cookies

        page.goto("https://www.google.co.jp/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
        page.goto("https://www.google.com/maps", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
    except Exception:
        pass


def _click_reviews_tab(page):
    """Click the reviews tab to show all reviews."""
    tabs = page.query_selector_all('button[role="tab"]')
    for tab in tabs:
        text = (tab.text_content() or "").strip()
        if "クチコミ" in text or "口コミ" in text or "review" in text.lower():
            tab.click()
            time.sleep(5)
            return True

    # Fallback: click element with aria-label containing クチコミ
    clicked = page.evaluate("""() => {
        const els = document.querySelectorAll('button, a, [role="button"]');
        for (const el of els) {
            const label = el.getAttribute('aria-label') || '';
            if (label.includes('クチコミ') || label.includes('口コミ')) {
                el.click();
                return true;
            }
        }
        return false;
    }""")
    if clicked:
        time.sleep(5)
    return clicked


def _sort_by_newest(page):
    """Sort reviews by newest first."""
    try:
        sort_btn = page.query_selector('button[aria-label="クチコミの並べ替え"]')
        if not sort_btn:
            return
        sort_btn.click()
        time.sleep(2)
        # Click "新しい順" (data-index=1)
        page.evaluate("""() => {
            const items = document.querySelectorAll('[role="menuitemradio"]');
            for (const item of items) {
                if (item.getAttribute('data-index') === '1') {
                    item.click();
                    return;
                }
            }
        }""")
        time.sleep(3)
    except Exception:
        pass


def _start_session(url: str):
    """Start a StealthySession and navigate to the URL with retries."""
    import os
    os.makedirs(PROFILE_DIR, exist_ok=True)

    for retry in range(5):
        session = StealthySession(
            headless=True,
            locale="ja-JP",
            user_data_dir=PROFILE_DIR,
        )
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

        # Warm up: visit Google to get cookies (critical for reviews tab)
        _warm_up_session(page, session)

        # Resolve share.google URLs in browser (JS redirect)
        url = _resolve_share_url_in_browser(page, url)

        referer = generate_convincing_referer(url)
        page.goto(
            url, referer=referer, wait_until="domcontentloaded", timeout=60000
        )

        # Wait for page to load, then click reviews tab
        time.sleep(8)

        # Try clicking reviews tab first
        _click_reviews_tab(page)

        # Sort by newest
        _sort_by_newest(page)

        # Poll for review elements
        found = False
        for _ in range(15):
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


def _collect_all_reviews(page, progress_callback=None) -> list[dict]:
    """Scroll through all reviews and collect them incrementally."""
    saved_ids: set = set()
    all_reviews: list[dict] = []

    # Initial collection
    all_reviews.extend(_extract_reviews_from_dom(page, saved_ids))
    if progress_callback:
        progress_callback(len(all_reviews), f"初期読み込み: {len(all_reviews)}件")

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
            if progress_callback and new:
                progress_callback(len(all_reviews), f"スクロール中... {len(all_reviews)}件取得")
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
