"""similarity_search 的 market 過濾：問一邊不得撈到另一邊。

打真實資料庫（不 patch），因為要驗的正是「庫裡的塊有沒有被正確擋掉」。
market 為 NULL 的塊視為市場不明，指定市場時一律排除——放行它們就是原本
問美股卻收到台股大盤新聞的成因。

需在 app container 內執行（DB 未對 host 開 port）：
    docker exec finance_ai_assistant_app python tests/test_market_filter.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph import _embed_query_cached, retrieve_context
from src.vectorstore import similarity_search

QUESTION = "半導體產業最近的狀況如何？"


def main() -> None:
    vec, _ = _embed_query_cached(QUESTION)

    for want in ("tw", "us"):
        docs = similarity_search(vec, top_k=20, market=want)
        assert docs, f"market={want} 應撈得到資料"
        got = {d.get("market") for d in docs}
        assert got == {want}, f"market={want} 卻撈到 {got}"

    # 不指定就不過濾：應涵蓋到指定單一市場時看不到的塊
    unfiltered = similarity_search(vec, top_k=20)
    assert unfiltered, "不指定市場應撈得到資料"

    # NULL 市場的塊不得混進任一邊
    for want in ("tw", "us"):
        docs = similarity_search(vec, top_k=50, market=want)
        assert not [d for d in docs if d.get("market") is None], \
            f"market={want} 撈到了市場不明（NULL）的塊"

    # retrieve_context 這層：'both' 代表兩邊都要，不可被當成市場值過濾成空
    both = retrieve_context(QUESTION, market="both")
    assert both, "'both' 應視為不限市場，不得過濾成零筆"

    # 整條路徑（含市場新聞補充）都不得外洩到另一個市場
    for want, other in (("us", "tw"), ("tw", "us")):
        docs = retrieve_context(QUESTION, market=want)
        leaked = [d for d in docs if d.get("market") == other]
        assert not leaked, f"問 {want} 卻外洩 {len(leaked)} 筆 {other} 文件"

    print("OK")


if __name__ == "__main__":
    main()
