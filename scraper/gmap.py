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
        page, session = _start_session(url, progress_callback)
        reviews = _collect_all_reviews(page, progress_callback)
        return reviews
    finally:
        if session:
            try:
                session.close()
            except Exception:
                pass


PROFILE_BASE = "/tmp/gmap-profiles"


REQUIRED_COOKIES = {"AEC", "NID"}  # Minimum cookies needed for reviews tab


def _check_cookies(session) -> dict:
    """Check which required Google cookies are present."""
    cookies = session.context.cookies()
    names = {c.get("name", "") for c in cookies if "google" in c.get("domain", "")}
    return {
        "present": names & REQUIRED_COOKIES,
        "missing": REQUIRED_COOKIES - names,
        "all_google": names,
    }


def _warm_up_session(page, session):
    """Visit Google properties to accumulate cookies for trust score."""
    try:
        check = _check_cookies(session)
        if not check["missing"]:
            return True  # Already has required cookies

        page.goto("https://www.google.co.jp/", wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        page.goto("https://www.google.com/maps", wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)

        # Verify cookies were set
        check = _check_cookies(session)
        if check["missing"]:
            # Try one more time with longer wait
            page.goto("https://www.google.co.jp/search?q=maps", wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            check = _check_cookies(session)

        return not check["missing"]
    except Exception:
        return False


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


def _start_session(url: str, progress_callback=None):
    """Start a StealthySession and navigate to the URL with retries."""
    import os, uuid
    profile_dir = os.path.join(PROFILE_BASE, uuid.uuid4().hex[:8])
    os.makedirs(profile_dir, exist_ok=True)

    last_error = ""
    for retry in range(5):
        if progress_callback:
            progress_callback(0, f"セッション開始中... (試行 {retry + 1}/5)")

        # Remove stale SingletonLock if exists
        lock_file = os.path.join(profile_dir, "SingletonLock")
        if os.path.exists(lock_file):
            os.remove(lock_file)

        try:
            session = StealthySession(
                headless=True,
                locale="ja-JP",
                user_data_dir=profile_dir,
            )
            session.start()
        except Exception as e:
            last_error = f"セッション起動失敗: {e}"
            if progress_callback:
                progress_callback(0, f"セッション起動失敗、リトライ中... ({retry + 1}/5)")
            time.sleep(3)
            continue

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

        # Cookie warm-up with validation
        if progress_callback:
            progress_callback(0, "Cookie取得中...")
        cookies_ok = _warm_up_session(page, session)
        if not cookies_ok:
            check = _check_cookies(session)
            if progress_callback:
                progress_callback(0, f"Cookie不足 (missing: {check['missing']})、Cookie無しでページ読み込みを試行...")
            # Don't bail out - try loading the page anyway (Cloud Run IPs may not get all cookies)
        else:
            if progress_callback:
                progress_callback(0, "Cookie OK、ページ読み込み中...")

        # Resolve share.google URLs in browser (JS redirect)
        url = _resolve_share_url_in_browser(page, url)

        try:
            referer = generate_convincing_referer(url)
            page.goto(
                url, referer=referer, wait_until="networkidle", timeout=120000
            )
        except Exception as e:
            last_error = f"ページ読み込み失敗: {e}"
            if progress_callback:
                progress_callback(0, f"ページタイムアウト、リトライ中... ({retry + 1}/5)")
            try:
                session.close()
            except Exception:
                pass
            time.sleep(3)
            continue

        time.sleep(5)

        # Early detection: check if page has tabs (概要/クチコミ/写真/基本情報)
        tab_count = len(page.query_selector_all('button[role="tab"]'))
        if progress_callback:
            progress_callback(0, f"タブ検出: {tab_count}個")

        if tab_count < 3:
            if progress_callback:
                progress_callback(0, f"タブ不足({tab_count}個)、IP制限の可能性。プロファイル再作成してリトライ...")
            try:
                session.close()
            except Exception:
                pass
            import shutil
            shutil.rmtree(profile_dir, ignore_errors=True)
            profile_dir = os.path.join(PROFILE_BASE, uuid.uuid4().hex[:8])
            os.makedirs(profile_dir, exist_ok=True)
            time.sleep(5)
            continue

        # Try clicking reviews tab
        if progress_callback:
            progress_callback(0, "クチコミタブをクリック中...")
        _click_reviews_tab(page)

        # Sort by newest
        if progress_callback:
            progress_callback(0, "新しい順にソート中...")
        _sort_by_newest(page)

        # Poll for review elements
        found = False
        for i in range(15):
            if page.query_selector_all(".wiI7pd"):
                found = True
                break
            if progress_callback:
                progress_callback(0, f"レビュー要素を待機中... ({i + 1}/15)")
            time.sleep(2)

        if found:
            if progress_callback:
                progress_callback(0, "レビュー検出OK、収集開始...")
            return page, session

        last_error = "レビュー要素が見つかりませんでした"
        if progress_callback:
            progress_callback(0, f"レビュー未検出、リトライ中... ({retry + 1}/5)")
        try:
            session.close()
        except Exception:
            pass

    raise RuntimeError(f"Google Maps レビュー取得失敗 (5回リトライ済み): {last_error}")


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

            if comment or rating:
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
            if progress_callback:
                if new:
                    progress_callback(len(all_reviews), f"スクロール中... {len(all_reviews)}件取得")
                elif i % 15 == 14:
                    progress_callback(len(all_reviews), f"スクロール中... {len(all_reviews)}件 (新規なし {no_new+1}/5)")
            if len(new) == 0:
                no_new += 1
            else:
                no_new = 0

        # 20 consecutive rounds with no new reviews -> done
        if no_new >= 5:
            final = _extract_reviews_from_dom(page, saved_ids)
            all_reviews.extend(final)
            break

    return all_reviews
