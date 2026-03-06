"""TripAdvisor review scraper using Scrapling StealthyFetcher."""
from scrapling.fetchers import StealthyFetcher
import re


def scrape_tripadvisor_reviews(url: str, progress_callback=None) -> list[dict]:
    """Scrape all reviews from a TripAdvisor URL with pagination.

    The URL should contain '{}' or 'Reviews-' as the insertion point for
    pagination offsets. If not, pagination offset is inserted after 'Reviews'.
    """
    base_url = _prepare_base_url(url)
    all_reviews = []
    page_num = 0

    while True:
        offset = f"-or{page_num * 15}" if page_num > 0 else ""
        page_url = base_url.format(offset)

        page = StealthyFetcher.fetch(page_url, headless=True, network_idle=True)
        cards = page.css('[data-automation="reviewCard"]')

        if not cards:
            break

        new_count = 0
        for card in cards:
            review = _parse_review_card(card)
            if review:
                all_reviews.append(review)
                new_count += 1

        if progress_callback:
            progress_callback(len(all_reviews), f"ページ{page_num + 1}取得中... {len(all_reviews)}件")

        if new_count == 0:
            break

        page_num += 1
        if page_num >= 30:
            break

    return all_reviews


def _prepare_base_url(url: str) -> str:
    """Ensure the URL has a {} placeholder for pagination offset."""
    if "{}" in url:
        return url
    # Insert placeholder after 'Reviews'
    if "Reviews-" in url:
        return url.replace("Reviews-", "Reviews{}-", 1)
    if "Reviews" in url:
        return url.replace("Reviews", "Reviews{}", 1)
    return url + "{}"


def _parse_review_card(card) -> dict | None:
    """Parse a single TripAdvisor review card element."""
    # review_id
    review_id = ""
    review_link = card.css('a[href*="ShowUserReviews"]')
    if review_link:
        href = review_link[0].attrib.get("href", "")
        m = re.search(r"-r(\d+)-", href)
        if m:
            review_id = m.group(1)
    if not review_id:
        for attr_name in ["data-reviewid", "data-review-id"]:
            val = card.attrib.get(attr_name, "")
            if val:
                review_id = val
                break

    # Author
    author_el = card.css("a.BMQDV")
    author = (author_el[0].text or "").strip() if author_el else ""

    # Rating
    rating = ""
    title_els = card.css("title")
    for t in title_els:
        txt = t.text or ""
        if "バブル評価" in txt or "段階中" in txt or "of 5 bubbles" in txt:
            rating = txt.strip()
            break

    # Date
    full_text = card.get_all_text()
    date = ""
    date_match = re.search(r"(\d{4}年\d{1,2}月)", full_text)
    if date_match:
        date = date_match.group(1)
    else:
        # English date format fallback
        date_match_en = re.search(r"([A-Z][a-z]+ \d{4})", full_text)
        if date_match_en:
            date = date_match_en.group(1)

    # Comment (use get_all_text, not .text which returns empty)
    comment_el = card.css("div.biGQs._P.VImYz.AWdfh")
    comment = comment_el[0].get_all_text().strip() if comment_el else ""

    if not comment:
        return None

    return {
        "review_id": review_id,
        "author": author,
        "rating": rating,
        "date": date,
        "comment": comment,
    }
