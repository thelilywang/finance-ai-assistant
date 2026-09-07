"""最小 self-check：三個 MCP tool 的回傳格式與參數傳遞。

tool 是 async def（MCP 規範），所以用 asyncio.run 呼叫，與其他同步測試略有差異。
不測 LLM 會不會依 docstring 正確選用 tool——那需要真實 Ollama 且結果不確定，屬手動驗證。
執行：python tests/test_mcp_tools.py
"""
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.mcp_server as mcp_server
from src.update import FetchResult

TODAY = dt.date.today()
chunks = [
    {"id": 1, "source": "EDGAR:AAPL:x", "title": None, "doc_type": "financial_report",
     "company": "AAPL", "published_at": TODAY - dt.timedelta(days=60), "content": "財報內容"},
    {"id": 2, "source": "https://news/1", "title": "新聞標題", "doc_type": "news",
     "company": "AAPL", "published_at": TODAY - dt.timedelta(days=1), "content": "新聞內容"},
]

# --- search_knowledge_base：回傳 JSON 須同時給 LLM 讀的文字與程式用的結構化 chunks ---
mcp_server.retrieve_context = lambda q, c=None, d=None: chunks
out = json.loads(asyncio.run(mcp_server.search_knowledge_base("AAPL 財報", "AAPL")))
assert set(out) == {"summary_for_llm", "chunks"}
assert len(out["chunks"]) == len(chunks)  # 原封不動帶回，generate 要靠它組來源編號
assert "EDGAR:AAPL:x" in out["summary_for_llm"]

# 時效性判斷的關鍵：LLM 讀得到日期卻不會自己跟今天相減，所以要直接給「距今 N 天」與今天日期
summary = out["summary_for_llm"]
assert f"今天是 {TODAY}" in summary
assert "距今 60 天" in summary
assert "距今 1 天" in summary
# 時效結論只看新聞：財報 60 天不該被拿來當過期依據（實測模型會混用兩者的天數）
assert "最新的「新聞」距今 1 天" in summary
assert "[財報｜EDGAR:AAPL:x]" in summary and "[新聞｜https://news/1]" in summary

# 只有財報沒有新聞時要明講，否則模型會誤以為新聞夠新
mcp_server.retrieve_context = lambda q, c=None, d=None: [chunks[0]]
only_report = json.loads(asyncio.run(mcp_server.search_knowledge_base("x")))
assert "沒有任何新聞" in only_report["summary_for_llm"]

# 日期不明的資料不應該炸，也不該硬掰天數
mcp_server.retrieve_context = lambda q, c=None, d=None: [
    {"id": 3, "source": "s", "title": None, "doc_type": "news",
     "company": None, "published_at": None, "content": "無日期"}
]
no_date = json.loads(asyncio.run(mcp_server.search_knowledge_base("x")))
assert "發布日期：不明" in no_date["summary_for_llm"]

# doc_type 只接受單一合法值：LLM 實測會塞 "financial_report,news"，那樣過濾會查空
seen = {}
mcp_server.retrieve_context = lambda q, c=None, d=None: seen.update(doc_type=d) or chunks
asyncio.run(mcp_server.search_knowledge_base("x", None, "financial_report,news"))
assert seen["doc_type"] is None  # 多值 → 不過濾，而非照字面查
asyncio.run(mcp_server.search_knowledge_base("x", None, "news"))
assert seen["doc_type"] == "news"  # 單一合法值照常傳遞
asyncio.run(mcp_server.search_knowledge_base("x", None, "亂填"))
assert seen["doc_type"] is None

# 查無資料時仍是合法 JSON，chunks 為空
mcp_server.retrieve_context = lambda q, c=None, d=None: []
empty = json.loads(asyncio.run(mcp_server.search_knowledge_base("無此標的")))
assert empty["chunks"] == []
assert "查無" in empty["summary_for_llm"]

# --- fetch_company_data：正規化 ticker、依既有財報決定 has_report ---
calls = {}
mcp_server.fetch_missing_data = lambda company, has_report: (
    calls.update(company=company, has_report=has_report) or ["已匯入財報", "新聞更新完成"]
)

mcp_server.retrieve_context = lambda q, c=None, d=None: []  # 沒有既有財報
assert asyncio.run(mcp_server.fetch_company_data("2330")) == "已匯入財報；新聞更新完成"
assert calls == {"company": "2330", "has_report": False}

mcp_server.retrieve_context = lambda q, c=None, d=None: chunks  # 已有財報 → 只補新聞
asyncio.run(mcp_server.fetch_company_data("aapl.us"))  # 順便驗證後綴會被正規化掉
assert calls == {"company": "AAPL", "has_report": True}

# 代號格式不符時不應打外部來源
calls.clear()
assert "無法辨識" in asyncio.run(mcp_server.fetch_company_data("這不是代號"))
assert calls == {}

# --- fetch_market_overview：取 FetchResult.detail ---
mcp_server.fetch_market_news = lambda limit: FetchResult(True, "市場新聞更新完成，共寫入 5 筆")
assert asyncio.run(mcp_server.fetch_market_overview()) == "市場新聞更新完成，共寫入 5 筆"

print("mcp tools self-check OK")
