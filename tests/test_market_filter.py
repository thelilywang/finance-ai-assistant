"""similarity_search 的 market 過濾：問一邊不得撈到另一邊。

打真實資料庫（不 patch），因為要驗的正是「庫裡的塊有沒有被正確擋掉」。
market 為 NULL 的塊視為市場不明，指定市場時一律排除——放行它們就是原本
問美股卻收到台股大盤新聞的成因。

需要 Postgres 才能跑；本地沒有 DB 時整支 skip（見 module 開頭的連線探測）。
在 app container 內執行：
    docker exec finance_ai_assistant_app python -m pytest tests/test_market_filter.py
"""
import psycopg
import pytest

from src import config
from src.graph import _embed_query_cached, retrieve_context
from src.vectorstore import similarity_search

QUESTION = "半導體產業最近的狀況如何？"


def _db_reachable() -> bool:
    try:
        with psycopg.connect(config.DATABASE_URL, connect_timeout=2):
            return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="需要 Postgres")


def test_market_filter_excludes_other_market():
    vec, _ = _embed_query_cached(QUESTION)

    for want in ("tw", "us"):
        docs = similarity_search(vec, top_k=20, market=want)
        assert docs, f"market={want} 應撈得到資料"
        got = {d.get("market") for d in docs}
        assert got == {want}, f"market={want} 卻撈到 {got}"

    # 不指定就不過濾：應涵蓋到指定單一市場時看不到的塊
    unfiltered = similarity_search(vec, top_k=20)
    assert unfiltered, "不指定市場應撈得到資料"


def test_market_filter_excludes_null_market():
    vec, _ = _embed_query_cached(QUESTION)

    # NULL 市場的塊不得混進任一邊
    for want in ("tw", "us"):
        docs = similarity_search(vec, top_k=50, market=want)
        assert not [d for d in docs if d.get("market") is None], \
            f"market={want} 撈到了市場不明（NULL）的塊"


def test_retrieve_context_both_not_filtered():
    # retrieve_context 這層：'both' 代表兩邊都要，不可被當成市場值過濾成空
    both = retrieve_context(QUESTION, market="both")
    assert both, "'both' 應視為不限市場，不得過濾成零筆"


def test_retrieve_context_full_path_no_leak():
    # 整條路徑（含市場新聞補充）都不得外洩到另一個市場
    for want, other in (("us", "tw"), ("tw", "us")):
        docs = retrieve_context(QUESTION, market=want)
        leaked = [d for d in docs if d.get("market") == other]
        assert not leaked, f"問 {want} 卻外洩 {len(leaked)} 筆 {other} 文件"
