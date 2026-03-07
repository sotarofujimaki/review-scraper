"""Google Maps review scraper using Scrapling StealthySession."""
import os
import re
import glob
import shutil
import time
import threading
import uuid
import random

from scrapling.fetchers import StealthySession
from scrapling.engines.toolbelt.fingerprints import generate_convincing_referer

from config import (
    BLOCKED_DOMAINS_GOOGLE,
    GOOGLE_PAGE_TIMEOUT_MS,
    GOOGLE_WARMUP_TIMEOUT_MS,
    GOOGLE_STALL_SECONDS,
    GOOGLE_NO_NEW_THRESHOLD,
    GOOGLE_MAX_SCROLLS,
    GOOGLE_SCROLL_INTERVAL_MIN,
    GOOGLE_SCROLL_INTERVAL_MAX,
    GOOGLE_WARMUP_DELAY_MIN,
    GOOGLE_WARMUP_DELAY_MAX,
    GOOGLE_TAB_WAIT_SECONDS,
    GOOGLE_PROFILE_BASE,
    GOOGLE_VIEWPORTS,
    MAX_RETRIES,
    TOR_PROXY_URL,
)
from utils.date_parser import parse_japanese_date
from utils.tor import get_proxy_for_retry
import utils.tor as tor_utils
from css_selectors import GOOGLE, query_first, query_all_first
from utils.gyazo import upload_screenshot


REQUIRED_COOKIES = {"AEC", "NID"}  # Minimum cookies needed for reviews tab


def _resolve_url(url: str) -> str:
    """Resolve short URLs and ensure full Google Maps URL format."""
    import subprocess
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
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
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


def scrape_google_reviews(url: str, progress_callback=None, review_save_callback=None) -> list[dict]:
    """Scrape all reviews from a Google Maps URL.
    
    0件で終了した場合、最大3回まで全体リトライする（「取れるまで粘る」戦略）。
    """
    url = _resolve_url(url)
    # Note: !9m1!1b1 は付けない（概要タブで開いてからクチコミタブをクリックする方が確実）
    _clean_browser_profiles()
    if not any(d in url.lower() for d in ["google.com/maps", "google.co.jp/maps", "maps.app.goo.gl", "maps.google", "share.google"]):
        raise ValueError("Google MapsのURLを入力してください")

    MAX_OUTER_RETRIES = 3
    all_collected = []

    for outer in range(MAX_OUTER_RETRIES):
        session = None
        try:
            if outer > 0:
                if progress_callback:
                    progress_callback(0, f"0件のため全体リトライ ({outer + 1}/{MAX_OUTER_RETRIES})...")
                _clean_browser_profiles()
                time.sleep(random.uniform(5, 15))

            page, session = _start_session(url, progress_callback)

            # バックグラウンド30秒スクショスレッド（スクロールループ外でも撮影）
            _stop_bg_screenshot = threading.Event()
            def _bg_screenshot_loop():
                while not _stop_bg_screenshot.is_set():
                    _stop_bg_screenshot.wait(30)
                    if _stop_bg_screenshot.is_set():
                        break
                    try:
                        gyazo_url = upload_screenshot(page, f"Google Maps - periodic ({time.strftime('%H:%M:%S')})")
                        if gyazo_url and progress_callback:
                            progress_callback(0, f"📸 {gyazo_url}")
                    except Exception:
                        pass  # page closed等
            bg_ss = threading.Thread(target=_bg_screenshot_loop, daemon=True)
            bg_ss.start()

            try:
                reviews = _collect_all_reviews(page, session, url, progress_callback, review_save_callback)
            finally:
                _stop_bg_screenshot.set()

            if reviews:
                return reviews  # 取れたら即返す

            if progress_callback:
                progress_callback(0, f"0件で終了、リトライ判定中... ({outer + 1}/{MAX_OUTER_RETRIES})")
        except RuntimeError as e:
            if progress_callback:
                progress_callback(0, f"エラー: {e}, リトライ判定中...")
        finally:
            if session:
                try:
                    session.close()
                except Exception:
                    pass

    return all_collected  # 最終的に取れなかった


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
            return True

        page.goto("https://www.google.co.jp/", wait_until="domcontentloaded", timeout=GOOGLE_WARMUP_TIMEOUT_MS)
        time.sleep(random.uniform(GOOGLE_WARMUP_DELAY_MIN, GOOGLE_WARMUP_DELAY_MAX))
        page.goto("https://www.google.com/maps", wait_until="domcontentloaded", timeout=GOOGLE_WARMUP_TIMEOUT_MS)
        time.sleep(random.uniform(GOOGLE_WARMUP_DELAY_MIN, GOOGLE_WARMUP_DELAY_MAX))

        check = _check_cookies(session)
        if check["missing"]:
            page.goto("https://www.google.co.jp/search?q=maps", wait_until="domcontentloaded", timeout=GOOGLE_WARMUP_TIMEOUT_MS)
            time.sleep(random.uniform(GOOGLE_WARMUP_DELAY_MIN, GOOGLE_WARMUP_DELAY_MAX))
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
            try:
                tab.click(timeout=10000)  # 10s timeout
            except Exception:
                # Fallback: JS click
                try:
                    tab.evaluate("el => el.click()")
                except Exception:
                    pass
            time.sleep(2)
            return True

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
        time.sleep(2)
    return clicked


def _sort_by_newest(page, progress_callback=None):
    """Sort reviews by newest first."""
    try:
        sort_btn = query_first(page, GOOGLE["sort_button"])
        if not sort_btn:
            return
        try:
            sort_btn.click(timeout=10000)
        except Exception:
            try:
                sort_btn.evaluate("el => el.click()")
            except Exception:
                return
        time.sleep(2)
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
        if progress_callback:
            gyazo_url = upload_screenshot(page, "Google Maps - sorted by newest")
            msg = "新しい順にソート完了"
            if gyazo_url:
                msg += f" 📸 {gyazo_url}"
            progress_callback(0, msg)
    except Exception:
        pass


def _start_session(url: str, progress_callback=None, proxy: str | None = None):
    """Start a StealthySession and navigate to the URL.

    Args:
        url: Target Google Maps URL.
        progress_callback: Optional progress reporting callback.
        proxy: Explicit proxy URL. If None with no explicit call context,
               uses get_proxy_for_retry logic across MAX_RETRIES attempts.
               If called with proxy explicitly set (even None), only tries once.
    """
    last_error = ""
    for retry in range(MAX_RETRIES):
        profile_dir = os.path.join(GOOGLE_PROFILE_BASE, uuid.uuid4().hex[:8])
        os.makedirs(profile_dir, exist_ok=True)

        if progress_callback:
            progress_callback(0, f"セッション開始中... (試行 {retry + 1}/{MAX_RETRIES}, profile: {os.path.basename(profile_dir)})")

        try:
            effective_proxy = proxy if proxy is not None else get_proxy_for_retry(retry)
            if effective_proxy and progress_callback:
                progress_callback(0, "Tor回線更新済み、新IP経由で接続中...")
            viewport = random.choice(GOOGLE_VIEWPORTS)
            session_kwargs = dict(
                headless=True,
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                user_data_dir=profile_dir,
                disable_resources=False,  # CSS/JSが必要（SPAの描画に必須）
                hide_canvas=True,
                block_webrtc=True,
                google_search=True,
                blocked_domains=BLOCKED_DOMAINS_GOOGLE,
            )
            if effective_proxy:
                session_kwargs["proxy"] = {"server": effective_proxy}
            if progress_callback:
                progress_callback(0, f"Session kwargs: headless={session_kwargs.get('headless')}, hide_canvas={session_kwargs.get('hide_canvas')}, block_webrtc={session_kwargs.get('block_webrtc')}")
            session = StealthySession(**session_kwargs)
            # 60秒タイムアウト: watchdogスレッドで監視、タイムアウト時にsession.close()で強制終了
            # session.start()はメインスレッドで実行（greenletスレッド親和性の制約回避）
            _timed_out = [False]
            def _watchdog():
                time.sleep(120)  # 120秒: 起動+warm-up+gotoをカバー
                _timed_out[0] = True
                try:
                    session.close()
                except Exception:
                    pass
            wd = threading.Thread(target=_watchdog, daemon=True)
            wd.start()
            try:
                session.start()
            except Exception as e:
                if _timed_out[0]:
                    if progress_callback:
                        progress_callback(0, f"ブラウザ起動タイムアウト(60秒)、リトライ中... ({retry + 1}/{MAX_RETRIES})")
                    time.sleep(3)
                    continue
                raise
            if progress_callback:
                progress_callback(0, "ブラウザ起動完了")
        except Exception as e:
            last_error = f"セッション起動失敗: {e}"
            if progress_callback:
                progress_callback(0, f"セッション起動失敗、リトライ中... ({retry + 1}/{MAX_RETRIES})")
            time.sleep(3)
            continue

        page = (
            session.context.pages[0]
            if session.context.pages
            else session.context.new_page()
        )

        # Viewport randomization for fingerprint diversity
        try:
            page.set_viewport_size(viewport)
        except Exception:
            pass

        # Block heavy resources (images only - NOT stylesheets/fonts, Google Maps SPA needs them)
        page.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,mp4,mp3}",
            lambda route: route.abort(),
        )

        if progress_callback:
            progress_callback(0, "Cookie取得中（warm-up）...")
        warmup_start = time.time()
        cookies_ok = _warm_up_session(page, session)
        if progress_callback:
            progress_callback(0, f"Cookie取得完了 ({int(time.time()-warmup_start)}秒)")
        if not cookies_ok:
            check = _check_cookies(session)
            if progress_callback:
                progress_callback(0, f"Cookie不足 (missing: {check['missing']}, present: {check['present']})")
            # Cookie不足でもmissing=set()なら実質OK、そうでなければリトライ
            if check["missing"]:
                if progress_callback:
                    progress_callback(0, f"Cookie不足、リトライ中... ({retry + 1}/{MAX_RETRIES})")
                try:
                    session.close()
                except Exception:
                    pass
                time.sleep(3)
                continue
        if progress_callback:
            progress_callback(0, "Cookie OK、ページ読み込み中...")

        url = _resolve_share_url_in_browser(page, url)

        if progress_callback:
            progress_callback(0, f"ページ読み込み中... {url[:60]}...")
        try:
            referer = generate_convincing_referer(url)
            page.goto(
                url, referer=referer, wait_until="domcontentloaded", timeout=GOOGLE_PAGE_TIMEOUT_MS
            )
            # SPAの描画を待つ（networkidleはハングするため手動wait）
            page.wait_for_timeout(5000)
        except Exception as e:
            last_error = f"ページ読み込み失敗: {e}"
            if progress_callback:
                progress_callback(0, f"ページタイムアウト、リトライ中... ({retry + 1}/{MAX_RETRIES})")
            try:
                session.close()
            except Exception:
                pass
            time.sleep(random.uniform(3, 8))
            continue

        time.sleep(random.uniform(GOOGLE_TAB_WAIT_SECONDS, GOOGLE_TAB_WAIT_SECONDS + 3))

        # ページ読み込み完了スクリーンショット
        gyazo_loaded = upload_screenshot(page, "Google Maps - page loaded")
        if progress_callback:
            progress_callback(0, f"スクショ結果: {gyazo_loaded or 'FAILED'}")
            msg = f"ページ読み込み完了"
            if gyazo_loaded:
                msg += f" 📸 {gyazo_loaded}"
            progress_callback(0, msg)

        tabs = page.query_selector_all('button[role="tab"]')
        tab_names = [t.text_content().strip() for t in tabs]
        has_review_tab = any('クチコミ' in n for n in tab_names)
        
        # Gyazo: タブ検出スクリーンショット
        gyazo_url = upload_screenshot(page, f"Google Maps - tabs detected ({len(tabs)})")
        if progress_callback:
            tab_msg = f"タブ検出: {len(tabs)}個 ({', '.join(tab_names)})"
            if gyazo_url:
                tab_msg += f" 📸 {gyazo_url}"
            progress_callback(0, tab_msg)

        if not has_review_tab:
            gyazo_url = upload_screenshot(page, f"Google Maps - no review tab (retry {retry+1})")
            if progress_callback:
                msg = f"クチコミタブなし（{', '.join(tab_names)}）、リトライ..."
                if gyazo_url:
                    msg += f" 📸 {gyazo_url}"
                progress_callback(0, msg)
            try:
                session.close()
            except Exception:
                pass
            shutil.rmtree(profile_dir, ignore_errors=True)
            profile_dir = os.path.join(GOOGLE_PROFILE_BASE, uuid.uuid4().hex[:8])
            os.makedirs(profile_dir, exist_ok=True)
            time.sleep(random.uniform(3, 8))
            continue

        if progress_callback:
            progress_callback(0, f"クチコミタブをクリック中... ({len(tab_names)}個: {', '.join(tab_names)})")
        clicked = _click_reviews_tab(page)
        if progress_callback:
            gyazo_url = upload_screenshot(page, f"Google Maps - tab click {'ok' if clicked else 'fail'}")
            msg = f"タブクリック {'成功' if clicked else '失敗'}"
            if gyazo_url:
                msg += f" 📸 {gyazo_url}"
            progress_callback(0, msg)

        if progress_callback:
            progress_callback(0, "新しい順にソート中...")
        _sort_by_newest(page, progress_callback)
        if progress_callback:
            progress_callback(0, "ソート完了、レビュー読み込み待機中...")

        found = False
        # まずwait_for_selectorで最大15秒待つ
        for sel in ['[data-review-id]', '.jftiEf', '.wiI7pd']:
            try:
                page.wait_for_selector(sel, timeout=15000)
                found = True
                if progress_callback:
                    progress_callback(0, f"レビュー要素検出 (selector: {sel})")
                break
            except Exception:
                continue
        # フォールバック: ポーリング
        if not found:
            for i in range(5):
                if query_all_first(page, GOOGLE["review_text"]) or query_all_first(page, GOOGLE["review_block"]):
                    found = True
                    break
                if progress_callback:
                    progress_callback(0, f"レビュー要素を待機中... ({i + 1}/5)")
                time.sleep(3)

        if found:
            gyazo_url = upload_screenshot(page, "Google Maps - reviews found")
            if progress_callback:
                msg = "レビュー検出OK、収集開始..."
                if gyazo_url:
                    msg += f" 📸 {gyazo_url}"
                progress_callback(0, msg)
            return page, session

        last_error = "レビュー要素が見つかりませんでした"
        if progress_callback:
            progress_callback(0, f"レビュー未検出（IP制限の可能性）、リトライ中... ({retry + 1}/{MAX_RETRIES})")
        try:
            session.close()
        except Exception:
            pass

    # Partial success: return collected reviews even if session failed
    # (RuntimeError は上位の _collect_all_reviews → scrape_google_reviews で処理)
    raise RuntimeError(f"Google Maps レビュー取得失敗 ({MAX_RETRIES}回リトライ済み): {last_error}")


def _extract_reviews_from_dom(page, saved_ids: set) -> list[dict]:
    """Extract unsaved reviews currently in the DOM."""
    blocks = query_all_first(page, GOOGLE["review_block"])
    new_reviews = []
    for block in blocks:
        try:
            rid = block.get_attribute("data-review-id")
            if not rid or rid in saved_ids:
                continue

            more = query_first(block, GOOGLE["read_more"])
            if more:
                try:
                    more.click()
                    time.sleep(0.08)
                except Exception:
                    pass

            author_el = query_first(block, GOOGLE["author"])
            rating_el = query_first(block, GOOGLE["rating"])
            date_el = query_first(block, GOOGLE["date"])
            text_el = query_first(block, GOOGLE["review_text"])

            author = (author_el.text_content() or "").strip() if author_el else ""
            raw_rating = (
                (rating_el.get_attribute("aria-label") or "").strip()
                if rating_el
                else ""
            )
            m = re.search(r'(\d)', raw_rating)
            rating = m.group(1) if m else raw_rating
            raw_date = (date_el.text_content() or "").strip() if date_el else ""
            date = parse_japanese_date(raw_date)
            comment = (text_el.text_content() or "").strip() if text_el else ""

            if comment or rating:
                new_reviews.append(
                    {
                        "review_id": rid,
                        "author": author,
                        "rating": rating,
                        "posted_at": date,
                        "comment": comment,
                    }
                )
                saved_ids.add(rid)
        except Exception:
            continue
    return new_reviews


def _cleanup_heavy_elements(page):
    """Remove heavy child elements (images etc.) but keep review blocks."""
    try:
        page.evaluate(
            """() => {
            document.querySelectorAll('[data-review-id] img, [data-review-id] picture, [data-review-id] svg').forEach(el => el.remove());
            document.querySelectorAll('canvas, .Tya61d, .p0Aybe, .cYrDcb').forEach(el => el.remove());
        }""")
    except Exception:
        pass


def _scroll_reviews(page):
    """Scroll the reviews container using incremental approach.
    
    scrollTop = scrollHeight（一気に最下部）だとGoogle側がlazy loadを
    発火させないことがある。段階的スクロール（+800px）で確実に読み込ませる。
    """
    try:
        panel = page.query_selector('div.m6QErb.DxyBCb')
        if panel:
            # 段階的スクロール（+800px）— 一気に最下部に飛ばない
            page.evaluate("""() => {
                const el = document.querySelector('div.m6QErb.DxyBCb');
                if (el) el.scrollTop += 800;
            }""")
            # mouse.wheel for human-like behavior
            try:
                panel.hover()
                page.mouse.wheel(0, 500)
            except Exception:
                pass
        else:
            page.mouse.wheel(0, 800)
    except Exception:
        pass


def _try_stage1_recovery(page, progress_callback=None, count: int = 0) -> bool:
    """Stage 1: ページリフレッシュで回復試行。成功したらTrue。"""
    try:
        if progress_callback:
            progress_callback(count, "Stage 1: ページリフレッシュで回復試行中...")
        page.reload(wait_until="networkidle", timeout=30000)
        time.sleep(8)
        _click_reviews_tab(page)
        _sort_by_newest(page, progress_callback)
        time.sleep(3)
        if query_all_first(page, GOOGLE["review_text"]) or query_all_first(page, GOOGLE["review_block"]):
            return True
        return False
    except Exception:
        return False


def _try_stage2_recovery(session, url: str, progress_callback=None, count: int = 0):
    """Stage 2: 新プロファイルで再起動（同IP）。成功時に (page, new_session) を返す。失敗時は (None, None)。"""
    try:
        if progress_callback:
            progress_callback(count, "Stage 2: 新プロファイルで回復試行中...")
        try:
            session.close()
        except Exception:
            pass
        new_page, new_session = _start_session(url, progress_callback)
        return new_page, new_session
    except Exception:
        return None, None


def _try_stage3_recovery(session, url: str, progress_callback=None, count: int = 0):
    """Stage 3: Tor回線更新 + 新プロファイルで再起動（別IP）。成功時に (page, new_session) を返す。失敗時は (None, None)。"""
    try:
        if progress_callback:
            progress_callback(count, "Stage 3: Tor回線更新 + 新プロファイルで回復試行中...")
        tor_ok = tor_utils.renew_circuit()
        proxy = TOR_PROXY_URL if tor_ok else None
        try:
            session.close()
        except Exception:
            pass
        new_page, new_session = _start_session(url, progress_callback, proxy=proxy)
        return new_page, new_session
    except Exception:
        return None, None


def _collect_all_reviews(
    page,
    session,
    url: str,
    progress_callback=None,
    review_save_callback=None,
) -> list[dict]:
    """Scroll through all reviews and collect them incrementally.

    Implements a 3-stage stall recovery mechanism:
      Stage 1: Page refresh (same session/IP)
      Stage 2: New browser profile (same IP)
      Stage 3: Tor circuit renewal + new profile (new IP)
    """
    saved_ids: set = set()
    all_reviews: list[dict] = []
    start_time = time.time()

    all_reviews.extend(_extract_reviews_from_dom(page, saved_ids))
    if progress_callback:
        progress_callback(len(all_reviews), f"初期読み込み: {len(all_reviews)}件")
    if review_save_callback and all_reviews:
        review_save_callback(all_reviews)

    no_new = 0
    last_new_time = time.time()
    last_screenshot_time = time.time()

    if progress_callback:
        progress_callback(len(all_reviews), f"スクロール開始 (最大{GOOGLE_MAX_SCROLLS}回)")

    for i in range(GOOGLE_MAX_SCROLLS):
        try:
            _scroll_reviews(page)
        except Exception as scroll_err:
            if progress_callback:
                progress_callback(len(all_reviews), f"スクロールエラー: {scroll_err}")
            break
        time.sleep(random.uniform(GOOGLE_SCROLL_INTERVAL_MIN, GOOGLE_SCROLL_INTERVAL_MAX))

        elapsed = int(time.time() - last_new_time)

        if time.time() - last_new_time > GOOGLE_STALL_SECONDS:
            # スクロール停止 → 取れた分で完了（部分成功）
            gyazo_url = upload_screenshot(page, f"Google Maps - stall done ({len(all_reviews)} reviews)")
            if progress_callback:
                msg = f"{GOOGLE_STALL_SECONDS}秒間新規なし、収集終了 ({len(all_reviews)}件)"
                if gyazo_url:
                    msg += f" 📸 {gyazo_url}"
                progress_callback(len(all_reviews), msg)
            final = _extract_reviews_from_dom(page, saved_ids)
            all_reviews.extend(final)
            if review_save_callback and final:
                review_save_callback(final)
            break

        # DOM抽出は3回ごと（パフォーマンス）、進捗表示は毎回
        if i % 3 == 2:
            new = _extract_reviews_from_dom(page, saved_ids)
            all_reviews.extend(new)
            if review_save_callback and new:
                review_save_callback(new)
            _cleanup_heavy_elements(page)
            if len(new) == 0:
                no_new += 1
            else:
                no_new = 0
                last_new_time = time.time()
                elapsed = 0

        # 30秒おきにGyazoスクリーンショット
        _did_30s = False
        if time.time() - last_screenshot_time >= 30:
            gyazo_url = upload_screenshot(page, f"Google Maps - scrolling ({len(all_reviews)} reviews, scroll {i+1})")
            last_screenshot_time = time.time()
            msg_30 = f"🔍 30秒チェック: {len(all_reviews)}件収集中 (経過{int(time.time()-start_time)}秒, scroll {i+1})"
            if gyazo_url:
                msg_30 += f" 📸 {gyazo_url}"
            if progress_callback:
                progress_callback(len(all_reviews), msg_30)
            _did_30s = True

        # 毎スクロール進捗更新（30秒チェック直後はスキップ）
        if progress_callback and not _did_30s:
            if elapsed > 0:
                remaining = max(0, GOOGLE_STALL_SECONDS - elapsed)
                progress_callback(len(all_reviews), f"スクロール中... {len(all_reviews)}件 (新規なし {elapsed}秒/{GOOGLE_STALL_SECONDS}秒, scroll {i+1})")
            else:
                progress_callback(len(all_reviews), f"スクロール中... {len(all_reviews)}件取得 (scroll {i+1})")

        if no_new >= GOOGLE_NO_NEW_THRESHOLD:
            final = _extract_reviews_from_dom(page, saved_ids)
            all_reviews.extend(final)
            break

    return all_reviews
