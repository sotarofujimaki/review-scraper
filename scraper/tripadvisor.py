"""TripAdvisor review scraper using Scrapling StealthyFetcher.

Uses google_search + page_action to bypass DataDome CAPTCHA.
StealthyFetcher's browserforge fingerprints allow bypassing DataDome,
while page_action gives us direct Playwright page control for navigation.
"""
import re
import time

from scrapling.fetchers import StealthyFetcher

from config import (
    BLOCKED_DOMAINS_TA,
    TA_PAGE_TIMEOUT_MS,
    TA_REVIEWS_PER_PAGE,
    TA_MAX_PAGES,
    TA_MAX_TIME_SECONDS,
    TA_CARD_WAIT_SECONDS,
    TOR_PROXY_URL,
    MAX_RETRIES,
)
from utils.date_parser import parse_japanese_date
from utils.tor import is_tor_available
from css_selectors import TRIPADVISOR, query_first, query_all_first


def scrape_tripadvisor_reviews(url: str, progress_callback=None, review_save_callback=None) -> list[dict]:
    """Scrape all reviews from a TripAdvisor URL with pagination.

    Uses StealthyFetcher with google_search to bypass DataDome,
    then navigates to target URL via page_action.
    Retries up to MAX_RETRIES times. 30-minute timeout.
    """
    if "tripadvisor" not in url.lower():
        raise ValueError("TripAdvisorのURLを入力してください")

    # .com → .jp に変換（日本語版=全言語レビュー表示、英語版=Englishフィルタがかかる）
    url = re.sub(r'tripadvisor\.com', 'tripadvisor.jp', url, flags=re.IGNORECASE)
    base_url = _prepare_base_url(url)
    start_time = time.time()

    domain_match = re.search(r'(https?://[^/]+)', url)
    domain = domain_match.group(1) if domain_match else 'https://www.tripadvisor.jp'

    last_error = ""
    for attempt in range(MAX_RETRIES):
        if time.time() - start_time > TA_MAX_TIME_SECONDS:
            break

        if progress_callback:
            progress_callback(0, f"セッション開始中... (試行 {attempt + 1}/{MAX_RETRIES})")

        result = {"reviews": [], "error": None}

        def make_action(base, pcb, rsc, res, st):
            """Create page_action closure with current attempt's variables."""
            def action(page):
                html = page.content()
                if "captcha-delivery" in html:
                    res["error"] = "CAPTCHA on landing page"
                    if pcb:
                        pcb(0, "トップページでCAPTCHA検出")
                    return

                if pcb:
                    pcb(0, "トップページOK、レストランページへ遷移中...")

                page_url = base.format("")
                if "?" in page_url:
                    page_url += "&filterLang=ALL"
                else:
                    page_url += "?filterLang=ALL"
                if pcb:
                    pcb(0, "全言語フィルタ適用: filterLang=ALL")
                page.goto(page_url, wait_until="domcontentloaded", timeout=TA_PAGE_TIMEOUT_MS)
                for _w in range(TA_CARD_WAIT_SECONDS):
                    time.sleep(1)
                    if query_first(page, TRIPADVISOR["review_card"]):
                        break
                time.sleep(2)

                html2 = page.content()
                if "captcha-delivery" in html2:
                    res["error"] = "CAPTCHA on restaurant page"
                    if pcb:
                        pcb(0, "レストランページでCAPTCHA検出")
                    return

                # .jpドメイン使用で全言語レビュー表示（フィルタ操作不要）
                if pcb:
                    pcb(0, f"言語: 日本語版 (tripadvisor.jp) → 全言語レビュー表示")

                # フィルタ変更後にカード検出
                cards = query_all_first(page, TRIPADVISOR["review_card"])
                if not cards:
                    res["error"] = "No review cards found after filter"
                    if pcb:
                        pcb(0, "レビューカード未検出")
                    return

                actual_url = page.evaluate("() => window.location.href")
                if pcb:
                    pcb(0, f"レビュー検出OK ({len(cards)}件)、収集開始...")
                    pcb(0, f"ページURL: {actual_url[:100]}")

                all_reviews = []
                page_num = 0

                while True:
                    if time.time() - st > TA_MAX_TIME_SECONDS:
                        if pcb:
                            pcb(len(all_reviews), "30分タイムアウト、収集終了")
                        break

                    cards = query_all_first(page, TRIPADVISOR["review_card"])
                    if not cards:
                        for alt in ['[data-test-target="HR_CC_CARD"]', '.review-container']:
                            cards = page.query_selector_all(alt)
                            if cards:
                                break

                    if not cards:
                        if pcb:
                            pcb(len(all_reviews), f"ページ{page_num + 1}: カードなし、終了")
                        break

                    new_batch = []
                    parse_fails = 0
                    for ci, card in enumerate(cards):
                        review = _parse_review_card(card)
                        if review:
                            all_reviews.append(review)
                            new_batch.append(review)
                        else:
                            parse_fails += 1
                            # Debug: log what we found in this card
                            try:
                                card_html = card.inner_html()[:200] if hasattr(card, 'inner_html') else str(card)[:200]
                                card_text = (card.text_content() or "")[:100] if hasattr(card, 'text_content') else ""
                                if pcb:
                                    pcb(len(all_reviews), f"パース失敗 card[{ci}]: text={card_text[:60]}... html_snippet={card_html[:80]}...")
                            except Exception as dbg_e:
                                if pcb:
                                    pcb(len(all_reviews), f"パース失敗 card[{ci}]: デバッグ取得エラー: {dbg_e}")
                    new_count = len(new_batch)
                    if pcb and parse_fails:
                        pcb(len(all_reviews), f"パース結果: 成功{new_count} 失敗{parse_fails}/{len(cards)}")

                    if rsc and new_batch:
                        if pcb:
                            pcb(len(all_reviews), f"Firestore保存中... {len(new_batch)}件")
                        rsc(new_batch)
                        if pcb:
                            pcb(len(all_reviews), f"Firestore保存完了")
                    elif pcb and not new_batch and cards:
                        pcb(len(all_reviews), f"パース結果: 全{len(cards)}件失敗（new_batch空）")

                    if pcb:
                        pcb(len(all_reviews), f"ページ{page_num + 1}: {new_count}件取得 (合計{len(all_reviews)}件)")

                    if new_count == 0:
                        if pcb:
                            pcb(len(all_reviews), f"ページ{page_num + 1}: 新規0件、収集完了")
                        break
                    if new_count < TA_REVIEWS_PER_PAGE:
                        if pcb:
                            pcb(len(all_reviews), f"ページ{page_num + 1}: {new_count}件（{TA_REVIEWS_PER_PAGE}未満=最終ページ）、収集完了")
                        break

                    page_num += 1
                    if page_num >= TA_MAX_PAGES:
                        break

                    offset = f"-or{page_num * TA_REVIEWS_PER_PAGE}"
                    next_url = base.format(offset)
                    if "?" in next_url:
                        next_url += "&filterLang=ALL"
                    else:
                        next_url += "?filterLang=ALL"
                    if pcb:
                        pcb(len(all_reviews), f"ページ{page_num + 1}: filterLang=ALL 適用済み")
                    if pcb:
                        pcb(len(all_reviews), f"ページ{page_num + 1}へ遷移中... ({next_url[-30:]})")
                    try:
                        page.goto(next_url, wait_until="domcontentloaded", timeout=TA_PAGE_TIMEOUT_MS)
                        card_found = False
                        for _w in range(TA_CARD_WAIT_SECONDS):
                            time.sleep(1)
                            if query_first(page, TRIPADVISOR["review_card"]):
                                card_found = True
                                break
                        if not card_found and pcb:
                            pcb(len(all_reviews), f"ページ{page_num + 1}: カード未検出、終了")
                        if not card_found:
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
            action_fn = make_action(base_url, progress_callback, review_save_callback, result, start_time)

            # 全試行直接（Tor不使用、失敗時はインスタンス切替リトライ）
            # 試行1,3,5: google_search=True
            # 試行2,4: google_search=False
            use_google_search = (attempt % 2 == 0)
            use_proxy = None

            fetch_kwargs = dict(
                headless=True,
                network_idle=True,
                google_search=use_google_search,
                page_action=action_fn,
                wait=5,
                hide_canvas=True,
                block_webrtc=True,
                timezone_id="Asia/Tokyo",
                locale="ja-JP",
                blocked_domains=BLOCKED_DOMAINS_TA,
            )
            if use_proxy:
                fetch_kwargs["proxy"] = use_proxy
                if progress_callback:
                    progress_callback(0, "Tor経由で接続中...")

            StealthyFetcher.fetch(
                domain + "/",
                **fetch_kwargs,
            )

            if result["error"]:
                last_error = result["error"]
                if progress_callback:
                    progress_callback(0, f"{result['error']}、リトライ... ({attempt + 1}/{MAX_RETRIES})")
                time.sleep(5)
                continue

            return result["reviews"]

        except Exception as e:
            last_error = str(e)
            if progress_callback:
                progress_callback(0, f"エラー: {e}、リトライ... ({attempt + 1}/{MAX_RETRIES})")
            time.sleep(3)
            continue

    raise RuntimeError(f"TripAdvisor レビュー取得失敗 ({MAX_RETRIES}回リトライ済み): {last_error}")


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
    import re

    full_text = ""
    try:
        full_text = card.text_content() or ""
    except Exception:
        pass

    # Review ID
    review_id = ""
    for attr in ["data-reviewid", "data-review-id"]:
        val = card.get_attribute(attr) or ""
        if val:
            review_id = val
            break
    if not review_id:
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
        try:
            plink = card.query_selector('a[href*="/Profile/"]')
            if plink:
                href = plink.get_attribute("href") or ""
                m = re.search(r"/Profile/(\w+)", href)
                if m:
                    review_id = m.group(1)
        except Exception:
            pass

    # Author
    author = ""
    for sel in [
        "a.BMQDV.ukgoS", "a.BMQDV:not([aria-hidden])",
        "a[href*=\'/Profile/\']:not([aria-hidden])",
        "span.biGQs._P.ezezH a",
    ]:
        try:
            el = card.query_selector(sel)
            if el:
                author = (el.text_content() or "").strip()
                if author:
                    break
        except Exception:
            continue

    # Rating — SVG title in innerHTML or text fallback
    rating = ""
    try:
        html = card.inner_html()
        m = re.search(r"<title[^>]*>(\d)(?:\.\d)?\s*of\s*5\s*bubbles</title>", html)
        if m:
            rating = m.group(1)
        else:
            m = re.search(r"<title[^>]*>バブル評価\s*5\s*段階中\s*(\d)", html)
            if m:
                rating = m.group(1)
    except Exception:
        pass
    if not rating:
        m = re.search(r"(\d)(?:\.\d)?\s*of\s*5\s*bubbles", full_text)
        if m:
            rating = m.group(1)
        else:
            m = re.search(r"バブル評価\s*5\s*段階中\s*(\d)", full_text)
            if m:
                rating = m.group(1)

    # Date
    date = ""
    try:
        m = re.search(r"(\d{4})年(\d{1,2})月", full_text)
        if m:
            date = f"{m.group(1)}-{int(m.group(2)):02d}"
        else:
            month_map = {
                "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
                "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
                "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
                "January": "01", "February": "02", "March": "03",
                "April": "04", "June": "06", "July": "07",
                "August": "08", "September": "09", "October": "10",
                "November": "11", "December": "12",
            }
            m2 = re.search(r"([A-Z][a-z]{2,8})\s+(\d{4})", full_text)
            if m2 and m2.group(1) in month_map:
                date = f"{m2.group(2)}-{month_map[m2.group(1)]}"
    except Exception:
        pass

    # Comment
    comment = ""
    for sel in [
        "div.biGQs._P.VImYz.AWdfh", "div.biGQs._P.pZUbB.KxBGd",
        "span.biGQs._P.VImYz.AWdfh", "[class*=\'reviewText\']", ".partial_entry",
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
        "rating": rating, "posted_at": date, "comment": comment,
    }
