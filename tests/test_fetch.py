"""最小 self-check：fetch_missing_data 收集各來源結果訊息，單一來源失敗不中斷、不吞訊息，
且每筆耗時 log 帶正確的 company／source（市場總覽新聞不掛在當次查詢的公司名下）。

原本的 route_after_retrieve/needs_refetch 測試已隨函式移除——「資料夠不夠新、要不要補抓」
現在由 LLM 依 MCP tool 說明自行判斷（見 src/mcp_server.py 的 docstring），沒有確定性路由可測。
執行：python tests/test_fetch.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.graph as graph
import src.update as update
from src.graph import fetch_missing_data
from src.update import FetchResult

# 攔 log_duration 收欄位：驗 company/source 標籤有沒有貼錯到隔壁那筆
logged = []
_orig_log_duration = graph.log_duration
graph.log_duration = lambda log, event, started, **f: logged.append(f)

_orig = (update.fetch_mops, update.fetch_edgar, update.fetch_news,
         update.fetch_market_news, update.fetch_tw_financials, update.fetch_sec_financials)
# 台股財報兩軌：官方 API 與 MOPS 各自獨立成敗，都要 patch 掉否則會真的連外
update.fetch_tw_financials = lambda co_id: FetchResult(True, "已匯入 2330 115Q2 財報數字")
update.fetch_mops = lambda co_id: FetchResult(False, "MOPS 查無財報")
update.fetch_news = lambda company, limit=10: FetchResult(True, "已寫入 3 筆")
update.fetch_market_news = lambda limit_per_source=10: FetchResult(True, "已寫入 2 筆")
# 美股分支雖未在本測試中走到，但 fetch_missing_data 會 import 到，不 patch 會真的連外
update.fetch_sec_financials = lambda ticker: FetchResult(True, "已匯入 AAPL XBRL 財報數字")
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

    # 市場總覽新聞與特定公司無關，記成 company=None 才不會灌水該公司的抓取成功率
    update.fetch_mops = lambda co_id: FetchResult(False, "MOPS 查無財報")
    logged.clear()
    fetch_missing_data("2330", has_report=False)
    assert [(f["company"], f["source"], f["ok"]) for f in logged] == [
        ("2330", "fetch_tw_financials", True),
        ("2330", "fetch_mops", False),
        ("2330", "fetch_news", True),
        (None, "fetch_market_news", True),
    ]

    # 例外那條路徑也要帶對標籤（成功/失敗兩處 log_duration 各自帶參數，容易漏改一邊）
    update.fetch_mops = _boom
    logged.clear()
    fetch_missing_data("2330", has_report=False)
    assert (logged[1]["company"], logged[1]["source"], logged[1]["ok"]) == ("2330", "fetch_mops", False)
    assert logged[-1]["company"] is None
finally:
    graph.log_duration = _orig_log_duration
    (update.fetch_mops, update.fetch_edgar, update.fetch_news,
     update.fetch_market_news, update.fetch_tw_financials, update.fetch_sec_financials) = _orig

print("fetch_missing_data self-check OK")


# --- agent() 的 directive 要同時指名 stale 與 missing ---
# 迴歸防線：修前 `if stale := _stale_companies(state)[0]:` 丟掉了 missing，
# 零新聞的標的（如 TSM）永遠進不了 directive，補抓從未被觸發（見待辦4）。
class _FakeToolLLM:
    """假 bind_tools 鏈：回一則沒有 tool_calls 的訊息，讓 agent() 立刻收工。"""
    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        sent_messages.clear()
        sent_messages.extend(messages)
        return graph.AIMessage(content="ok")


sent_messages: list = []

async def _fake_get_tools():
    return []

_orig_llms = graph._llms
_orig_get_tools = graph._mcp_client.get_tools
graph._llms = lambda model: {"tool": _FakeToolLLM()}
graph._mcp_client.get_tools = _fake_get_tools
try:
    # TSM 沒有任何檢索結果可算天數 → 落在 missing，不落在 stale
    state = {
        "question": "TSM 最近新聞", "companies": ["TSM"], "messages": [],
        "news_since_days": None, "model": "",
    }
    result = asyncio.run(graph.agent(state))
    directive_msgs = [m for m in result["messages"] if isinstance(m, graph.HumanMessage)]
    assert directive_msgs, "零新聞標的應觸發 directive，結果卻是空的"
    text = directive_msgs[0].content
    assert "TSM" in text and "完全沒有檢索到新聞" in text, text
    # 送進模型的訊息裡也要看得到 directive，否則模型收不到指名
    assert any("TSM" in getattr(m, "content", "") for m in sent_messages), "directive 沒送進模型"
finally:
    graph._llms = _orig_llms
    graph._mcp_client.get_tools = _orig_get_tools

print("agent directive (missing) self-check OK")
