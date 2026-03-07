"""Tests for scraper/google.py — pure-logic functions (no browser/network)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import pytest
from unittest.mock import MagicMock, patch


# ── _ensure_reviews_tab ──────────────────────────────────────────────────────

def test_ensure_reviews_tab_already_present():
    """!9m1!1b1がすでにあればURLを変更しない。"""
    from scraper.google import _ensure_reviews_tab
    url = "https://www.google.com/maps/place/test/data=!9m1!1b1"
    assert _ensure_reviews_tab(url) == url


def test_ensure_reviews_tab_adds_to_data_param():
    """/data= が存在する場合、先頭に挿入する。"""
    from scraper.google import _ensure_reviews_tab
    url = "https://www.google.com/maps/place/test/data=!4m5!3m4"
    result = _ensure_reviews_tab(url)
    assert "!9m1!1b1" in result
    assert "/data=" in result


def test_ensure_reviews_tab_adds_as_query_param():
    """/data= がない場合、クエリパラメータとして付与する。"""
    from scraper.google import _ensure_reviews_tab
    url = "https://www.google.com/maps/place/test"
    result = _ensure_reviews_tab(url)
    assert "!9m1!1b1" in result
    assert "data=" in result


def test_ensure_reviews_tab_uses_ampersand_if_query_exists():
    """クエリが既にある場合は & で連結する。"""
    from scraper.google import _ensure_reviews_tab
    url = "https://www.google.com/maps/place/test?hl=ja"
    result = _ensure_reviews_tab(url)
    assert "!9m1!1b1" in result
    assert "&data=" in result


# ── _extract_reviews_from_dom ────────────────────────────────────────────────

def _make_block(review_id, author_text, aria_label, date_text, comment_text, has_more=False):
    """Helper: Playwright要素をMagicMockで模倣する。"""
    block = MagicMock()
    block.get_attribute.side_effect = lambda attr: review_id if attr == "data-review-id" else None

    author_el = MagicMock()
    author_el.text_content.return_value = author_text

    rating_el = MagicMock()
    rating_el.get_attribute.side_effect = lambda attr: aria_label if attr == "aria-label" else None

    date_el = MagicMock()
    date_el.text_content.return_value = date_text

    text_el = MagicMock()
    text_el.text_content.return_value = comment_text

    more_btn = MagicMock() if has_more else None

    def mock_query_first(sel):
        # css_selectors.query_first をパッチするのでここでは直接使わない
        # _extract_reviews_from_dom の内部でquery_first(block, GOOGLE[key]) が呼ばれる
        pass

    return block, author_el, rating_el, date_el, text_el, more_btn


def test_extract_reviews_from_dom_basic(monkeypatch):
    """基本パース: review_id/author/rating/date/comment が正しく取得できる。"""
    from scraper import google as g_mod
    from css_selectors import GOOGLE

    block = MagicMock()
    block.get_attribute.side_effect = lambda attr: "rid001" if attr == "data-review-id" else None

    author_el = MagicMock(); author_el.text_content.return_value = "山田 太郎"
    rating_el = MagicMock(); rating_el.get_attribute.side_effect = lambda a: "星5" if a == "aria-label" else None
    date_el = MagicMock(); date_el.text_content.return_value = "1か月前"
    text_el = MagicMock(); text_el.text_content.return_value = "とても良かった"

    def fake_query_first(parent, selectors):
        if parent is block:
            if selectors is GOOGLE["read_more"]:
                return None
            if selectors is GOOGLE["author"]:
                return author_el
            if selectors is GOOGLE["rating"]:
                return rating_el
            if selectors is GOOGLE["date"]:
                return date_el
            if selectors is GOOGLE["review_text"]:
                return text_el
        return None

    def fake_query_all_first(page, selectors):
        return [block]

    monkeypatch.setattr("scraper.google.query_first", fake_query_first)
    monkeypatch.setattr("scraper.google.query_all_first", fake_query_all_first)

    page = MagicMock()
    saved = set()
    results = g_mod._extract_reviews_from_dom(page, saved)

    assert len(results) == 1
    r = results[0]
    assert r["review_id"] == "rid001"
    assert r["author"] == "山田 太郎"
    assert r["comment"] == "とても良かった"
    assert "rid001" in saved


def test_extract_reviews_from_dom_skips_saved(monkeypatch):
    """保存済みIDはスキップされる。"""
    from scraper import google as g_mod
    from css_selectors import GOOGLE

    block = MagicMock()
    block.get_attribute.side_effect = lambda attr: "rid_existing" if attr == "data-review-id" else None

    monkeypatch.setattr("scraper.google.query_all_first", lambda p, s: [block])
    monkeypatch.setattr("scraper.google.query_first", lambda p, s: None)

    page = MagicMock()
    saved = {"rid_existing"}
    results = g_mod._extract_reviews_from_dom(page, saved)
    assert results == []


def test_extract_reviews_from_dom_rating_regex(monkeypatch):
    """aria-label から数字だけ取り出せる。"""
    from scraper import google as g_mod
    from css_selectors import GOOGLE

    block = MagicMock()
    block.get_attribute.side_effect = lambda attr: "r999" if attr == "data-review-id" else None

    rating_el = MagicMock()
    rating_el.get_attribute.side_effect = lambda a: "星4のうちの5" if a == "aria-label" else None
    text_el = MagicMock(); text_el.text_content.return_value = "良い"

    def fake_qf(parent, selectors):
        if selectors is GOOGLE["read_more"]: return None
        if selectors is GOOGLE["author"]: m = MagicMock(); m.text_content.return_value = ""; return m
        if selectors is GOOGLE["rating"]: return rating_el
        if selectors is GOOGLE["date"]: m = MagicMock(); m.text_content.return_value = ""; return m
        if selectors is GOOGLE["review_text"]: return text_el
        return None

    monkeypatch.setattr("scraper.google.query_all_first", lambda p, s: [block])
    monkeypatch.setattr("scraper.google.query_first", fake_qf)

    results = g_mod._extract_reviews_from_dom(MagicMock(), set())
    assert results[0]["rating"] == "4"  # 最初の数字


def test_extract_reviews_from_dom_no_comment_no_rating_skipped(monkeypatch):
    """コメントも評価もない場合はスキップ。"""
    from scraper import google as g_mod
    from css_selectors import GOOGLE

    block = MagicMock()
    block.get_attribute.side_effect = lambda attr: "r_empty" if attr == "data-review-id" else None

    def fake_qf(parent, selectors):
        if selectors is GOOGLE["read_more"]: return None
        el = MagicMock()
        el.text_content.return_value = ""
        el.get_attribute.return_value = ""
        return el

    monkeypatch.setattr("scraper.google.query_all_first", lambda p, s: [block])
    monkeypatch.setattr("scraper.google.query_first", fake_qf)

    results = g_mod._extract_reviews_from_dom(MagicMock(), set())
    assert results == []
