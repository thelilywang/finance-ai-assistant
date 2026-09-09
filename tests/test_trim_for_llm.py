"""最小 self-check：_trim_for_llm 只裁掉送進模型的檢索結果，state 本身不受影響。

裁錯會有兩種壞法：assemble 拿不到 chunks（來源編號與引用連結全壞），
或補抓 tool 的訊息被誤裁（模型看不到抓取失敗，會一直重抓）。這裡把兩者都固定住。
執行：python tests/test_trim_for_llm.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.graph import _trim_for_llm, assemble

chunks = [{"id": 1, "source": "EDGAR:AAPL:x", "doc_type": "financial_report",
           "published_at": "2026-08-01", "content": "財報內容"}]
payload = json.dumps({"summary_for_llm": "摘要文字", "chunks": chunks}, ensure_ascii=False)

messages = [
    HumanMessage(content="seed"),
    ToolMessage(content=payload, name="search_knowledge_base", tool_call_id="1"),
    ToolMessage(content="已匯入 AAPL 財報", name="fetch_company_data", tool_call_id="2"),
]
trimmed = _trim_for_llm(messages)

# 檢索結果只剩 summary，chunks 不再重送給模型
assert trimmed[1].content == "摘要文字"
assert "財報內容" not in trimmed[1].content
# tool_call_id/name 要留著，否則 Ollama 對不上這輪的 tool call
assert trimmed[1].tool_call_id == "1" and trimmed[1].name == "search_knowledge_base"
# 補抓訊息原樣保留：模型要靠它判斷抓取成功或失敗
assert trimmed[2].content == "已匯入 AAPL 財報"
assert trimmed[0].content == "seed"

# 原本的 messages 不被就地改動，assemble 仍拿得到完整 chunks
assert messages[1].content == payload
assert assemble({"messages": messages})["retrieved"] == chunks

# MCP content block 陣列格式也要能裁
blocks = [ToolMessage(content=[{"type": "text", "text": payload}],
                      name="search_knowledge_base", tool_call_id="1")]
assert _trim_for_llm(blocks)[0].content == "摘要文字"

# tool 回傳非 JSON 或缺欄位時原樣送進模型，不炸掉 agent 這一輪
broken = [ToolMessage(content="not-json", name="search_knowledge_base", tool_call_id="1"),
          ToolMessage(content=json.dumps({"chunks": []}), name="search_knowledge_base",
                      tool_call_id="2")]
out = _trim_for_llm(broken)
assert out[0].content == "not-json"
assert out[1].content == json.dumps({"chunks": []})

# 沒有 tool 訊息時原樣通過
assert _trim_for_llm([AIMessage(content="查完了")])[0].content == "查完了"

print("trim_for_llm self-check OK")
