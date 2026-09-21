"""market 欄位在寫入端的決定方式：由 company 推定，或由來源 key 指定。

市場別只在寫入時判定一次，檢索端直接讀欄位。這支守住兩件事：
推定規則（台股代號→tw、美股 ticker→us）與來源 key 的對應（_tw/_us 尾碼），
以及「推不出來時留 NULL 而不是亂猜一邊」——猜錯會讓問美股的人拿到台股資料，
比留白更糟。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import ingest, vectorstore
import src.update as update
from src.update import MARKET_SOURCES, _market_of_source


def market_of(company):
    """複製 ingest_text 的推定規則來驗；改動任一邊這裡就會對不上。"""
    from src.tickers import is_tw_ticker
    if not company:
        return None
    return "tw" if is_tw_ticker(company) else "us"


def main() -> None:
    # 由 company 推定
    assert market_of("2330") == "tw", "台股代號應推為 tw"
    assert market_of("8150") == "tw", "四碼台股代號應推為 tw"
    assert market_of("00981A") == "tw", "帶尾碼的台股 ETF 應推為 tw"
    assert market_of("TSM") == "us", "美股 ticker 應推為 us"
    assert market_of("AAPL") == "us", "美股 ticker 應推為 us"
    assert market_of(None) is None, "無 company 時不得自行推定"

    # 由 MARKET_SOURCES 的 key 指定
    assert _market_of_source("udn_tw") == "tw"
    assert _market_of_source("cnyes_us") == "us"
    assert _market_of_source("cmoney_tw") == "tw"
    assert _market_of_source("cmoney_us") == "us"
    # key 沒標市場就留 NULL，不可猜成任一邊
    assert _market_of_source("cmoney_tag") is None, "未標明市場的來源不得亂猜"

    # 現有來源全部都要標到市場：沒標的塊 market 為 NULL，而指定市場的檢索一律
    # 排除 NULL，等於該來源對「美股…」「台股…」的問句完全不可見
    for name in MARKET_SOURCES:
        assert _market_of_source(name) in ("tw", "us"), f"{name} 未以 _tw／_us 尾碼標明市場"

    # 雙掛牌兩邊必須落在不同市場——這正是 M6/M7 要分辨的東西
    assert market_of("2330") != market_of("TSM"), "雙掛牌兩邊不得落在同一市場"

    print("OK")


def test_fetch_tw_stock_news_market():
    """fetch_tw_stock_news 是函式而非 MARKET_SOURCES 的 key，market 靠程式明確傳
    'tw'，不靠 ingest_text 從 company 推定（此來源定義上只供台股）。

    攔 ingest.insert_chunks 收 rows 驗欄位，同 test_ingest.py 的手法；
    requests/trafilatura 全部假掉，不碰網路。
    """
    class _FakeResp:
        status_code = 200
        text = '"https://tw.stock.yahoo.com/news/公告-精金-2026年8月合併營收-111.html"'

    class _FakeDoc:
        text = "內文" * 60  # >= 100 字元門檻
        title = "公告-精金-2026年8月合併營收"
        date = "2026-08-31"

    captured_rows = []

    _orig_get = update.requests.get
    _orig_fetch_url = update.trafilatura.fetch_url
    _orig_bare_extraction = update.trafilatura.bare_extraction
    _orig_source_exists = vectorstore.source_exists
    _orig_insert_chunks = ingest.insert_chunks
    _orig_delete_by_source = ingest.delete_by_source
    _orig_ollama = ingest.OllamaEmbeddings

    update.requests.get = lambda *a, **k: _FakeResp()
    update.trafilatura.fetch_url = lambda link: "<html>fake</html>"
    update.trafilatura.bare_extraction = lambda html, with_metadata=True: _FakeDoc()
    vectorstore.source_exists = lambda source: False
    ingest.delete_by_source = lambda source: None
    ingest.OllamaEmbeddings = lambda *a, **k: type(
        "E", (), {"embed_documents": lambda self, chunks: [[0.0] for _ in chunks]}
    )()
    ingest.insert_chunks = lambda rows: captured_rows.extend(rows)
    try:
        result = update.fetch_tw_stock_news("3049", limit=10)
        assert result.ok, result.detail
        assert captured_rows, "應寫入至少一筆 chunk"
        assert all(r["market"] == "tw" for r in captured_rows), captured_rows
        assert all(r["company"] == "3049" for r in captured_rows), captured_rows
    finally:
        update.requests.get = _orig_get
        update.trafilatura.fetch_url = _orig_fetch_url
        update.trafilatura.bare_extraction = _orig_bare_extraction
        vectorstore.source_exists = _orig_source_exists
        ingest.insert_chunks = _orig_insert_chunks
        ingest.delete_by_source = _orig_delete_by_source
        ingest.OllamaEmbeddings = _orig_ollama

    print("fetch_tw_stock_news market='tw' self-check OK")


if __name__ == "__main__":
    main()
    test_fetch_tw_stock_news_market()
