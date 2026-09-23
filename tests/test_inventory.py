"""inventory 的軌別缺口判定。不連 DB，直接餵 list_sources 的回傳形狀。"""
import contextlib
import io

from src import update


def _run(monkeypatch, rows):
    # inventory 是在函式內 from .vectorstore import list_sources，故 patch 在來源模組
    import src.vectorstore as vs
    monkeypatch.setattr(vs, "list_sources", lambda *a, **k: rows)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        update.inventory()
    return buf.getvalue()


def _row(src, prefix, co, n, unit=None):
    return {"source": src, "prefix": prefix, "doc_type": "financial_report",
            "company": co, "published_at": None, "chunks": n,
            "chunk_unit": unit, "chunk_size": None, "embed_model": None}


def test_inventory_reports_missing_full_text_track(monkeypatch):
    # META 修復前：全文軌 0、XBRL 1 → 必須報缺口
    out = _run(monkeypatch, [_row("SEC-XBRL:META:x", "SEC-XBRL", "META", 1),
               _row("EDGAR:NVDA:y", "EDGAR", "NVDA", 586),
               _row("SEC-XBRL:NVDA:y", "SEC-XBRL", "NVDA", 1)])
    assert "缺口：全文軌（EDGAR）掛零" in out and "META" in out, out
    assert "⚠ 1 個標的" in out, out


def test_inventory_f_shares_no_xbrl_expected(monkeypatch):
    # F 股只有 EDGAR：不可誤報
    out = _run(monkeypatch, [_row("EDGAR:ASML:z", "EDGAR", "ASML", 104)])
    assert "缺口" not in out and "⚠" not in out, out
    assert "F 股不報 SEC-XBRL" in out, out


def test_inventory_tw_missing_numeric_track(monkeypatch):
    # 台股缺數字軌（2380 實況）：必須報缺口
    out = _run(monkeypatch, [_row("data/a.pdf", "data/a.pdf", "2380", 94)])
    assert "缺口：數字軌（TWSE-API）掛零" in out, out


def test_inventory_tw_both_tracks_present(monkeypatch):
    # 台股兩軌俱全 → 正常
    out = _run(monkeypatch, [_row("data/b.pdf", "data/b.pdf", "2330", 284),
               _row("TWSE-API:2330:115Q2", "TWSE-API", "2330", 2)])
    assert "正常" in out and "缺口" not in out.split("判定")[1], out


def test_inventory_tw_missing_full_text_track(monkeypatch):
    # 台股全文軌掛零（只有 TWSE-API 數字）→ 報全文軌缺口
    out = _run(monkeypatch, [_row("TWSE-API:2379:115Q2", "TWSE-API", "2379", 1)])
    assert "缺口：全文軌（MOPS-PDF）掛零" in out, out


def test_inventory_non_whitelisted_f_share_still_flagged(monkeypatch):
    # F 股白名單只涵蓋 ASML/TSM：其他美股缺數字軌仍是缺口（META 反例）
    out = _run(monkeypatch, [_row("EDGAR:AAPL:x", "EDGAR", "AAPL", 363)])
    assert "缺口：數字軌（SEC-XBRL）掛零" in out, out


def test_inventory_news_not_in_track_table(monkeypatch):
    # 新聞不列入軌別表
    out = _run(monkeypatch, [{"source": "https://x", "prefix": "https", "doc_type": "news",
                "company": "AAPL", "published_at": None, "chunks": 3,
                "chunk_unit": None, "chunk_size": None, "embed_model": None}])
    assert "財報軌別" not in out, out
