"""Tests for scraper/tripadvisor.py — pure-logic functions (no browser/network)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import pytest
from unittest.mock import MagicMock, patch


# ── _prepare_base_url ────────────────────────────────────────────────────────

def test_prepare_base_url_already_has_placeholder():
    """{} が既にある場合はそのまま返す。"""
    from scraper.tripadvisor import _prepare_base_url
    url = "https://www.tripadvisor.com/Restaurant_Review-g294232-d123456-Reviews{}-Name.html"
    assert _prepare_base_url(url) == url


def test_prepare_base_url_inserts_before_dash():
    """Reviews- がある場合、最初の Reviews- を Reviews{}- に変換する。"""
    from scraper.tripadvisor import _prepare_base_url
    url = "https://www.tripadvisor.com/Restaurant_Review-g294232-d123456-Reviews-Name.html"
    result = _prepare_base_url(url)
    assert "Reviews{}-" in result
    assert result.count("{}") == 1


def test_prepare_base_url_reviews_no_dash():
    """Reviews があるが - がない場合、Reviews{} に変換する。"""
    from scraper.tripadvisor import _prepare_base_url
    url = "https://www.tripadvisor.com/ShowUserReviews-g123-d456-Name.html"
    result = _prepare_base_url(url)
    assert "{}" in result


def test_prepare_base_url_no_reviews_keyword():
    """Reviews キーワードが全くない場合、末尾に {} を付与する。"""
    from scraper.tripadvisor import _prepare_base_url
    url = "https://www.tripadvisor.com/Restaurant_Review-g294232-d123456-Name.html"
    result = _prepare_base_url(url)
    assert result.endswith("{}")


# ── domain conversion (.jp → .com) ──────────────────────────────────────────

def test_domain_conversion_jp_to_com(monkeypatch):
    """.jp URL を .com に変換してからスクレイピングを試みる。"""
    from scraper import tripadvisor as ta_mod

    captured_base_url = []
    original_prepare = ta_mod._prepare_base_url

    def fake_prepare(url):
        captured_base_url.append(url)
        # 無限ループ防止のため RuntimeError を投げて抜ける
        raise RuntimeError("stop_test")

    monkeypatch.setattr(ta_mod, "_prepare_base_url", fake_prepare)

    import pytest
    with pytest.raises(RuntimeError, match="stop_test"):
        ta_mod.scrape_tripadvisor_reviews(
            "https://www.tripadvisor.jp/Restaurant_Review-g294232-d123456-Reviews-Name.html"
        )

    assert len(captured_base_url) >= 1
    assert "tripadvisor.com" in captured_base_url[0]


def test_domain_stays_com(monkeypatch):
    """.com URL はそのまま使われる（変換なし）。"""
    from scraper import tripadvisor as ta_mod

    captured = []
    def fake_prepare(url):
        captured.append(url)
        raise RuntimeError("stop_test")

    monkeypatch.setattr(ta_mod, "_prepare_base_url", fake_prepare)

    with pytest.raises(RuntimeError, match="stop_test"):
        ta_mod.scrape_tripadvisor_reviews(
            "https://www.tripadvisor.com/Restaurant_Review-g294232-d123456-Reviews-Name.html"
        )

    assert "tripadvisor.com" in captured[0]
    assert ".jp" not in captured[0]


# ── _parse_review_card ───────────────────────────────────────────────────────

def _make_card(review_id="", author="", rating_html="", date_text="", comment=""):
    """mock Playwright card 要素を生成。"""
    card = MagicMock()
    card.get_attribute.side_effect = lambda attr: review_id if attr == "data-reviewid" else None

    author_el = MagicMock()
    author_el.text_content.return_value = author

    comment_el = MagicMock()
    comment_el.text_content.return_value = comment

    # inner_html でレーティング
    card.inner_html.return_value = rating_html
    card.text_content.return_value = f"{author} {date_text} {comment}"

    def mock_query_selector(sel):
        if "BMQDV" in sel or "Profile" in sel or "ezezH" in sel:
            return author_el
        if "biGQs" in sel or "reviewText" in sel or "partial_entry" in sel:
            if comment:
                return comment_el
        return None

    def mock_query_selector_all(sel):
        if "ShowUserReviews" in sel or "Profile" in sel:
            return []
        return []

    card.query_selector.side_effect = mock_query_selector
    card.query_selector_all.side_effect = mock_query_selector_all

    return card


def test_parse_review_card_basic():
    """基本パース: author/rating/date/comment が取れる。"""
    from scraper.tripadvisor import _parse_review_card

    card = _make_card(
        review_id="r12345",
        author="佐藤 花子",
        rating_html='<title>5 of 5 bubbles</title>',
        date_text="January 2024",
        comment="最高のレストランでした",
    )
    card.get_attribute.side_effect = lambda attr: "r12345" if attr == "data-reviewid" else None
    card.text_content.return_value = "佐藤 花子 January 2024 最高のレストランでした"
    card.inner_html.return_value = '<title>5 of 5 bubbles</title>'

    result = _parse_review_card(card)
    assert result is not None
    assert result["rating"] == "5"
    assert result["posted_at"] == "2024-01"


def test_parse_review_card_japanese_date():
    """日本語日付 (2023年11月) のパース。"""
    from scraper.tripadvisor import _parse_review_card

    card = MagicMock()
    card.get_attribute.return_value = "r99"
    card.text_content.return_value = "テストユーザー 2023年11月 良い店"
    card.inner_html.return_value = '<title>4 of 5 bubbles</title>'
    card.query_selector.return_value = None
    card.query_selector_all.return_value = []

    result = _parse_review_card(card)
    assert result is not None
    assert result["posted_at"] == "2023-11"
    assert result["rating"] == "4"


def test_parse_review_card_no_comment_no_rating_returns_none():
    """コメントも評価もない → None"""
    from scraper.tripadvisor import _parse_review_card

    card = MagicMock()
    card.get_attribute.return_value = ""
    card.text_content.return_value = ""
    card.inner_html.return_value = ""
    card.query_selector.return_value = None
    card.query_selector_all.return_value = []

    result = _parse_review_card(card)
    assert result is None


def test_parse_review_card_rating_from_text_fallback():
    """inner_html にタイトルがない場合、text_content からフォールバック。"""
    from scraper.tripadvisor import _parse_review_card

    card = MagicMock()
    card.get_attribute.return_value = "r_fb"
    card.text_content.return_value = "Reviewer Name 3 of 5 bubbles March 2023 Good place"
    card.inner_html.return_value = ""  # no title tag
    card.query_selector.return_value = None
    card.query_selector_all.return_value = []

    result = _parse_review_card(card)
    assert result is not None
    assert result["rating"] == "3"
    assert result["posted_at"] == "2023-03"
