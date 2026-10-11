"""_format_source 三種情況（EDGAR/本地檔/帶追蹤參數的 URL）、_clean_url。"""
from src.app import _clean_url, _format_source


_LIST = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={}&owner=include&count=40"


def test_format_source_edgar():
    # EDGAR 來源：連到 ticker 申報列表，帶申報日期以區分不同申報
    assert _format_source("EDGAR:AAPL:0000320193-25-000057") == f"[SEC EDGAR filing (AAPL)]({_LIST.format('AAPL')})"
    assert _format_source("EDGAR:NVDA:0001045810-26-000075", None, "2026-05-28") == \
        f"[SEC EDGAR filing (NVDA, 2026-05-28)]({_LIST.format('NVDA')})"


def test_format_source_xbrl_and_twse():
    assert _format_source("SEC-XBRL:NVDA:0001045810-26-000075", None, "2026-05-28") == \
        f"[SEC XBRL financials (NVDA, 2026-05-28)]({_LIST.format('NVDA')})"
    assert _format_source("TWSE-API:2330:115Q2") == "TWSE financials (2330, 115Q2)"
    assert _clean_url("TWSE-API:2330:115Q2") is None


def test_source_meta():
    from src.app import _source_meta
    docs = [{"source": "a", "title": "T", "published_at": "2026-05-28T00:00:00"}, {"source": "a", "title": "U"}]
    assert _source_meta(docs) == ({"a": "T"}, {"a": "2026-05-28"})


def test_format_source_local_path():
    # 本地路徑：只留檔名
    assert _format_source("data/202601_2330_AI1.pdf") == "202601_2330_AI1.pdf"


def test_format_source_url_with_tracking_query():
    # 帶追蹤 query 的 URL：去掉 query/fragment，標題從 path slug 生成
    result = _format_source("https://www.example.com/news/apple-q3-earnings-beat?.tsrc=rss&utm=1#section")
    assert "?.tsrc=rss" not in result
    assert "https://www.example.com/news/apple-q3-earnings-beat" in result
    assert "example.com" in result
    assert "www." not in result.split("(")[0]  # domain 去掉 www.


def test_format_source_uses_real_title():
    # 有提供 title 時優先用真標題，不用 slug
    assert _format_source("https://www.example.com/news/abc-123", "Real Title") == \
        "[Real Title — example.com](https://www.example.com/news/abc-123)"


def test_clean_url():
    # _clean_url：URL 去 query/fragment；非 URL（EDGAR/本地檔）回 None
    assert _clean_url("https://www.example.com/a?x=1#y") == "https://www.example.com/a"
    assert _clean_url("EDGAR:AAPL:0000320193-25-000057") == _LIST.format("AAPL")
    assert _clean_url("data/202601_2330_AI1.pdf") is None
