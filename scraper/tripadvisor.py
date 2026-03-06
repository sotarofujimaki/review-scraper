"""TripAdvisor review scraper using Scrapling StealthyFetcher.

Uses google_search + page_action to bypass DataDome CAPTCHA.
StealthyFetcher's browserforge fingerprints allow bypassing DataDome,
while page_action gives us direct Playwright page control for navigation.
"""
from scrapling.fetchers import StealthyFetcher
import re
import time


def scrape_tripadvisor_reviews(url: str, progress_callback=None, review_save_callback=None) -> list[dict]:
    """Scrape all reviews from a TripAdvisor URL with pagination.

    Uses StealthyFetcher with google_search to bypass DataDome,
    then navigates to target URL via page_action.
    Retries up to 5 times. 30-minute timeout.
    """
    if "tripadvisor" not in url.lower():
        raise ValueError("TripAdvisorのURLを入力してください")

    base_url = _prepare_base_url(url)
    start_time = time.time()
    max_time = 1800  # 30 minutes

    # Extract domain for initial fetch (e.g. tripadvisor.jp)
    domain_match = re.search(r'(https?://[^/]+)', url)
    domain = domain_match.group(1) if domain_match else 'https://www.tripadvisor.jp'

    last_error = ""
    for attempt in range(5):
        if time.time() - start_time > max_time:
            break

        if progress_callback:
            progress_callback(0, f"セッション開始中... (試行 {attempt + 1}/5)")

        result = {"reviews": [], "error": None}

        def make_action(base, pcb, res, st, mt):
            """Create page_action closure with current attempt's variables."""
            def action(page):
                html = page.content()
                if "captcha-delivery" in html:
                    res["error"] = "CAPTCHA on landing page"
                    if pcb:
                        pcb(0, f"トップページでCAPTCHA検出")
                    return

                if pcb:
                    pcb(0, "トップページOK、レストランページへ遷移中...")

                # Navigate to first page of reviews
                page_url = base.format("")
                page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(5)

                html2 = page.content()
                if "captcha-delivery" in html2:
                    res["error"] = "CAPTCHA on restaurant page"
                    if pcb:
                        pcb(0, "レストランページでCAPTCHA検出")
                    return

                # Check for review cards
                cards = page.query_selector_all('[data-automation="reviewCard"]')
                if not cards:
                    for alt in ['[data-test-target="HR_CC_CARD"]', '.review-container']:
                        cards = page.query_selector_all(alt)
                        if cards:
                            break

                if not cards:
                    res["error"] = "No review cards found"
                    if pcb:
                        pcb(0, "レビューカード未検出")
                    return

                if pcb:
                    pcb(0, f"レビュー検出OK ({len(cards)}件)、収集開始...")

                # Collect from all pages
                all_reviews = []
                page_num = 0

                while True:
                    if time.time() - st > mt:
                        if pcb:
                            pcb(len(all_reviews), "30分タイムアウト、収集終了")
                        break

                    cards = page.query_selector_all('[data-automation="reviewCard"]')
                    if not cards:
                        for alt in ['[data-test-target="HR_CC_CARD"]', '.review-container']:
                            cards = page.query_selector_all(alt)
                            if cards:
                                break

                    if not cards:
                        if pcb:
                            pcb(len(all_reviews), f"ページ{page_num + 1}: カードなし、終了")
                        break

                    new_count = 0
                    for card in cards:
                        review = _parse_review_card(card)
                        if review:
                            all_reviews.append(review)
                            new_count += 1

                    if pcb:
                        pcb(len(all_reviews), f"ページ{page_num + 1}: {new_count}件取得 (合計{len(all_reviews)}件)")

                    if new_count == 0:
                        break

                    page_num += 1
                    if page_num >= 30:
                        break

                    # Next page
                    offset = f"-or{page_num * 15}"
                    next_url = base.format(offset)
                    try:
                        page.goto(next_url, wait_until="domcontentloaded", timeout=30000)
                        # Wait for cards to render
                        for _w in range(8):
                            time.sleep(1)
                            if page.query_selector('[data-automation="reviewCard"]'):
                                break
                        time.sleep(1)
                        html_next = page.content()
                        if "captcha-delivery" in html_next:
                            if pcb:
                                pcb(len(all_reviews), f"ページ{page_num + 1}でCAPTCHA、収集終了")
                            break
                    except Exception as e:
                        if pcb:
                            pcb(len(all_reviews), f"ページ{page_num + 1}取得失敗: {e}")
                        break

                res["reviews"] = all_reviews

            return action

        try:
            action_fn = make_action(base_url, progress_callback, result, start_time, max_time)

            fetch_kwargs = dict(
                headless=True,
                network_idle=True,
                google_search=True,
                page_action=action_fn,
                wait=5,
            )
            # Use Tor proxy on retries
            if attempt > 0:
                import socket
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(3)
                    if s.connect_ex(("127.0.0.1", 9050)) == 0:
                        fetch_kwargs["proxy"] = "socks5://127.0.0.1:9050"
                        if progress_callback:
                            progress_callback(0, "Tor経由で接続中...")
                    s.close()
                except Exception:
                    pass

            StealthyFetcher.fetch(
                domain + "/",
                **fetch_kwargs,
            )

            if result["error"]:
                last_error = result["error"]
                if progress_callback:
                    progress_callback(0, f"{result['error']}、リトライ... ({attempt + 1}/5)")
                time.sleep(5)
                continue

            return result["reviews"]

        except Exception as e:
            last_error = str(e)
            if progress_callback:
                progress_callback(0, f"エラー: {e}、リトライ... ({attempt + 1}/5)")
            time.sleep(3)
            continue

    raise RuntimeError(f"TripAdvisor レビュー取得失敗 (5回リトライ済み): {last_error}")


def _prepare_base_url(url: str) -> str:
    """Ensure the URL has a {} placeholder for pagination offset."""
    if "{}" in url:
        return url
    if "Reviews-" in url:
        return url.replace("Reviews-", "Reviews{}-", 1)
    if "Reviews" in url:
        return url.replace("Reviews", "Reviews{}", 1)
    return url + "{}"


def _parse_review_card(card) -> dict | None:
    """Parse a single TripAdvisor review card (Playwright element)."""
    # review_id
    review_id = ""
    try:
        links = card.query_selector_all('a[href*="ShowUserReviews"]')
        for link in links:
            href = link.get_attribute("href") or ""
            m = re.search(r"-r(\d+)-", href)
            if m:
                review_id = m.group(1)
                break
    except Exception:
        pass

    if not review_id:
        for attr in ["data-reviewid", "data-review-id"]:
            val = card.get_attribute(attr) or ""
            if val:
                review_id = val
                break

    # Author
    author = ""
    for sel in [
        "a.BMQDV.ukgoS", "a.BMQDV:not([aria-hidden])", "span.biGQs._P.ezezH a",
        "a.ui_header_link", "span.biGQs._P.fiohW.fOtGX",
        "a[href*='/Profile/']:not([aria-hidden])", "[class*='username']",
    ]:
        try:
            el = card.query_selector(sel)
            if el:
                author = (el.text_content() or "").strip()
                if author:
                    break
        except Exception:
            continue

    # Rating
    rating = ""
    try:
        titles = card.query_selector_all("title")
        for t in titles:
            txt = t.text_content() or ""
            if "バブル評価" in txt or "段階中" in txt or "of 5 bubbles" in txt:
                import re
                m = re.search(r'(\d)\s*$', txt.strip())
                rating = m.group(1) if m else txt.strip()
                break
        if not rating:
            bubble = card.query_selector("[class*='bubble']")
            if bubble:
                raw = bubble.get_attribute("aria-label") or ""
                import re
                m = re.search(r'(\d)\s*$', raw)
                rating = m.group(1) if m else raw
    except Exception:
        pass

    # Date
    date = ""
    try:
        full_text = card.text_content() or ""
        m = re.search(r"(\d{4}年\d{1,2}月)", full_text)
        if m:
            date = m.group(1)
        else:
            m2 = re.search(r"([A-Z][a-z]+ \d{4})", full_text)
            if m2:
                date = m2.group(1)
    except Exception:
        pass

    # Comment
    comment = ""
    for sel in [
        "div.biGQs._P.VImYz.AWdfh", "div.biGQs._P.pZUbB.KxBGd",
        "[class*='reviewText']", ".partial_entry",
    ]:
        try:
            el = card.query_selector(sel)
            if el:
                comment = (el.text_content() or "").strip()
                if comment:
                    break
        except Exception:
            continue

    if not comment and not rating:
        return None

    return {
        "review_id": review_id, "author": author,
        "rating": rating, "date": date, "comment": comment,
    }
