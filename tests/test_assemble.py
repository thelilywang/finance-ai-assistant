"""最小 self-check：assemble 把 tool-calling 結果還原成下游節點要的既有欄位，
以及 agent_route 的分支與輪數上限。

assemble 還原的 retrieved 結構若與 retrieve_context 原本回傳的不一致，
generate 的來源編號與 app.py 的引用連結都會壞掉，所以這裡固定住格式。
執行：python tests/test_assemble.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.graph import agent_route, assemble

chunks = [
    {"id": 1, "source": "EDGAR:AAPL:x", "title": None, "doc_type": "financial_report",
     "company": "AAPL", "published_at": "2026-08-01", "content": "財報內容"},
    {"id": 2, "source": "https://news/1", "title": "新聞標題", "doc_type": "news",
     "company": "AAPL", "published_at": "2026-09-06", "content": "新聞內容"},
]


def _tool_call(name, cid):
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": cid}])


# 檢索 + 補抓都跑過：retrieved 還原、fetched/fetch_results 供 no_result 使用
out = assemble({"messages": [
    HumanMessage(content="seed"),
    _tool_call("search_knowledge_base", "1"),
    ToolMessage(content=json.dumps({"summary_for_llm": "...", "chunks": chunks}),
                name="search_knowledge_base", tool_call_id="1"),
    _tool_call("fetch_company_data", "2"),
    ToolMessage(content="已匯入 AAPL 財報", name="fetch_company_data", tool_call_id="2"),
]})
assert out["retrieved"] == chunks
assert out["fetched"] is True
assert out["fetch_results"] == ["已匯入 AAPL 財報"]

# 只檢索沒補抓：fetched 為 False，no_result 才會用「查無資料」而非「抓過仍查無」的說法
out = assemble({"messages": [
    _tool_call("search_knowledge_base", "1"),
    ToolMessage(content=json.dumps({"summary_for_llm": "...", "chunks": chunks}),
                name="search_knowledge_base", tool_call_id="1"),
]})
assert out["fetched"] is False
assert out["fetch_results"] == []

# 補抓後又檢索一次：取最後一次檢索結果（補抓前查無、補抓後查到）
out = assemble({"messages": [
    _tool_call("search_knowledge_base", "1"),
    ToolMessage(content=json.dumps({"summary_for_llm": "查無", "chunks": []}),
                name="search_knowledge_base", tool_call_id="1"),
    _tool_call("fetch_company_data", "2"),
    ToolMessage(content="已匯入", name="fetch_company_data", tool_call_id="2"),
    _tool_call("search_knowledge_base", "3"),
    ToolMessage(content=json.dumps({"summary_for_llm": "...", "chunks": chunks}),
                name="search_knowledge_base", tool_call_id="3"),
]})
assert out["retrieved"] == chunks

# MCP tool 經 langchain-mcp-adapters 回來的是 content block 陣列，不是純字串
out = assemble({"messages": [
    ToolMessage(
        content=[{"type": "text",
                  "text": json.dumps({"summary_for_llm": "...", "chunks": chunks})}],
        name="search_knowledge_base", tool_call_id="1"),
    ToolMessage(content=[{"type": "text", "text": "已匯入 AAPL 財報"}],
                name="fetch_company_data", tool_call_id="2"),
]})
assert out["retrieved"] == chunks
assert out["fetch_results"] == ["已匯入 AAPL 財報"]  # 補抓訊息也要脫殼，否則 no_result 顯示出 dict

# tool 回傳非 JSON（server 異常）時降級成查無資料，不炸掉整個對話
out = assemble({"messages": [
    ToolMessage(content="not-json", name="search_knowledge_base", tool_call_id="x"),
]})
assert out["retrieved"] == []

# 完全沒呼叫過 tool
out = assemble({"messages": [HumanMessage(content="seed"), AIMessage(content="不需要工具")]})
assert out["retrieved"] == [] and out["fetched"] is False

print("assemble self-check OK")

# --- agent_route ---
assert agent_route({"messages": [_tool_call("search_knowledge_base", "1")]}) == "tools"
assert agent_route({"messages": [AIMessage(content="查完了")]}) == "assemble"
# 達輪數上限強制收工，避免 LLM 反覆補抓一直打外部網站
over_limit = [_tool_call("fetch_company_data", str(i)) for i in range(4)]
assert agent_route({"messages": over_limit}) == "assemble"

print("agent_route self-check OK")
