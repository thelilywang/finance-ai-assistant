"""最小 self-check：fetch_missing_data 收集各來源結果訊息，單一來源失敗不中斷、不吞訊息。

原本的 route_after_retrieve/needs_refetch 測試已隨函式移除——「資料夠不夠新、要不要補抓」
現在由 LLM 依 MCP tool 說明自行判斷（見 src/mcp_server.py 的 docstring），沒有確定性路由可測。
執行：python tests/test_fetch.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.update as update
from src.graph import fetch_missing_data
from src.update import FetchResult

_orig = (update.fetch_mops, update.fetch_edgar, update.fetch_news,
         update.fetch_market_news, update.fetch_tw_financials)
# 台股財報兩軌：官方 API 與 MOPS 各自獨立成敗，都要 patch 掉否則會真的連外
update.fetch_tw_financials = lambda co_id: FetchResult(True, "已匯入 2330 115Q2 財報數字")
update.fetch_mops = lambda co_id: FetchResult(False, "MOPS 查無財報")
update.fetch_news = lambda company, limit=10: FetchResult(True, "已寫入 3 筆")
update.fetch_market_news = lambda limit_per_source=10: FetchResult(True, "已寫入 2 筆")
try:
    results = fetch_missing_data("2330", has_report=False)
    # 一軌失敗一軌成功：兩則訊息都要保留，不因其中一軌掛掉就少一則
    assert results == ["已匯入 2330 115Q2 財報數字", "MOPS 查無財報", "已寫入 3 筆", "已寫入 2 筆"]

    def _boom(*a, **k):
        raise RuntimeError("網路逾時")
    update.fetch_mops = _boom
    results = fetch_missing_data("2330", has_report=False)
    assert results[1] == "抓取失敗：網路逾時"  # 例外不中斷後續來源
    assert results[0] == "已匯入 2330 115Q2 財報數字"  # 另一軌不受影響
    assert results[2:] == ["已寫入 3 筆", "已寫入 2 筆"]

    # has_report=True 只補新聞，兩軌財報都不重抓（依賴新聞排在最後）
    results = fetch_missing_data("2330", has_report=True)
    assert results == ["已寫入 3 筆", "已寫入 2 筆"]
finally:
    (update.fetch_mops, update.fetch_edgar, update.fetch_news,
     update.fetch_market_news, update.fetch_tw_financials) = _orig

print("fetch_missing_data self-check OK")
