"""最小 self-check：三個 MCP tool 的回傳格式與參數傳遞。

tool 是 async def（MCP 規範），所以用 asyncio.run 呼叫，與其他同步測試略有差異。
不測 LLM 會不會依 docstring 正確選用 tool——那需要真實 Ollama 且結果不確定，屬手動驗證。
執行：python tests/test_mcp_tools.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.mcp_server as mcp_server
from src.update import FetchResult

chunks = [
    {"id": 1, "source": "EDGAR:AAPL:x", "title": None, "doc_type": "financial_report",
     "company": "AAPL", "published_at": "2026-08-01", "content": "財報內容"},
    {"id": 2, "source": "https://news/1", "title": "新聞標題", "doc_type": "news",
     "company": "AAPL", "published_at": "2026-09-06", "content": "新聞內容"},
]

# --- search_knowledge_base：回傳 JSON 須同時給 LLM 讀的文字與程式用的結構化 chunks ---
mcp_server.retrieve_context = lambda q, c=None, d=None: chunks
out = json.loads(asyncio.run(mcp_server.search_knowledge_base("AAPL 財報", "AAPL")))
assert set(out) == {"summary_for_llm", "chunks"}
assert out["chunks"] == chunks  # 原封不動帶回，generate 要靠它組來源編號
assert "EDGAR:AAPL:x" in out["summary_for_llm"]
assert "2026-08-01" in out["summary_for_llm"]  # 日期要在文字裡，LLM 才判斷得出是否過期

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
