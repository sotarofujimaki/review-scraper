"""
Centralized CSS selectors with fallbacks.
When site layout changes, update selectors here only.
"""

# Google Maps
GOOGLE = {
    # Review block container
    "review_block": [
        "[data-review-id]",
        ".jftiEf",
        ".WMbnJf",
    ],
    # Review text
    "review_text": [
        ".wiI7pd",
        ".MyEned span",
        "[data-review-id] .rsqaWe ~ span",
    ],
    # Author name
    "author": [
        ".d4r55",
        "button[data-review-id] .d4r55",
        ".WNxzHc a",
    ],
    # Star rating (aria-label contains "X つ星")
    "rating": [
        ".kvMYJc",
        "[aria-label*='つ星']",
        "[aria-label*='star']",
    ],
    # Date
    "date": [
        ".rsqaWe",
        "[data-review-id] .dehysf",
        ".DU9Pgb",
    ],
    # Read more button
    "read_more": [
        "button.w8nwRe",
        "button.w8nwRe.kyuRq",
        "[aria-expanded='false'][jsaction*='review']",
    ],
    # Scroll container
    "scroll_container": [
        "div.m6QErb.DxyBCb.kA9KIf.dS8AEf",
        "div.m6QErb",
        "[role='feed']",
    ],
    # Sort button
    "sort_button": [
        'button[aria-label="クチコミの並べ替え"]',
        'button[aria-label="Sort reviews"]',
        'button[data-value="並べ替え"]',
    ],
    # Sort newest option
    "sort_newest": [
        '[role="menuitemradio"][data-index="1"]',
        '[role="menuitemradio"]:nth-child(2)',
    ],
}

# TripAdvisor
TRIPADVISOR = {
    # Review card container
    "review_card": [
        '[data-automation="reviewCard"]',
        '[data-test-target="HR_CC_CARD"]',
        '.review-container',
    ],
    # Author name (ordered by reliability)
    "author": [
        "a.BMQDV.ukgoS",
        "a.BMQDV:not([aria-hidden])",
        "span.biGQs._P.ezezH a",
        "a.ui_header_link",
        "span.biGQs._P.fiohW.fOtGX",
    ],
    # Comment text
    "comment": [
        "div.biGQs._P.VImYz.AWdfh",
        "div.biGQs._P.pZUbB.KxBGd",
        "span.JguWG",
        ".review-body",
    ],
    # Rating bubble
    "rating_title": "title",  # look for "バブル評価" in title text
    "rating_bubble": "[class*='bubble']",
    # Review ID link
    "review_id_link": 'a[href*="ShowUserReviews"]',
}


def query_first(element, selectors: list[str]):
    """Try multiple selectors, return first match."""
    for sel in selectors:
        try:
            el = element.query_selector(sel)
            if el:
                return el
        except Exception:
            continue
    return None


def query_all_first(element, selectors: list[str]) -> list:
    """Try multiple selectors for query_selector_all, return first non-empty."""
    for sel in selectors:
        try:
            els = element.query_selector_all(sel)
            if els:
                return els
        except Exception:
            continue
    return []
