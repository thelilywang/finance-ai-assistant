"""最小 self-check：route_after_tools 只在「資料明顯夠用」時收工。

判錯的代價不對稱：誤判成 assemble 會拿過期資料回答（該補抓卻沒補），
誤判成 agent 只是多花一輪。所以這裡把每個該回 agent 的情境都固定住。
執行：python tests/test_route_after_tools.py
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.graph import route_after_tools

TODAY = dt.date.today()


def _doc(doc_type, days_ago, doc_id=1):
    published = (TODAY - dt.timedelta(days=days_ago)).isoformat() if days_ago is not None else None
    return {"id": doc_id, "source": f"s{doc_id}", "doc_type": doc_type,
            "published_at": published, "content": "內容"}


def _search(docs, cid="1"):
    return ToolMessage(
        content=json.dumps({"summary_for_llm": "摘要", "chunks": docs}, ensure_ascii=False),
        name="search_knowledge_base", tool_call_id=cid)


def _state(messages, question="AAPL 營收多少？"):
    return {"question": question, "messages": messages}


report = _doc("financial_report", 40, 9)

# 今天的新聞 → 明顯夠用，直接收工
assert route_after_tools(_state([_search([report, _doc("news", 0)])])) == "assemble"
# 3 天內的新聞 → 一般問題視為夠新
assert route_after_tools(_state([_search([report, _doc("news", 3)])])) == "assemble"
# 4 天前的新聞 → 超過門檻，交還 LLM 決定要不要補抓
assert route_after_tools(_state([_search([report, _doc("news", 4)])])) == "agent"

# 問題問「最近」時門檻收緊到當天
recent = "AAPL 最近有什麼新聞？"
assert route_after_tools(_state([_search([_doc("news", 0)])], recent)) == "assemble"
assert route_after_tools(_state([_search([_doc("news", 2)])], recent)) == "agent"

# 只有財報、沒有新聞 → 不自作主張，交給 LLM
assert route_after_tools(_state([_search([report])])) == "agent"
# 查無資料 → 交給 LLM 決定補抓
assert route_after_tools(_state([_search([])])) == "agent"
# 新聞沒有發布日期 → 無從判斷時效，交給 LLM
assert route_after_tools(_state([_search([_doc("news", None)])])) == "agent"
# 日期格式異常不能炸掉路由
broken = {"id": 1, "source": "s", "doc_type": "news", "published_at": "不是日期", "content": "x"}
assert route_after_tools(_state([_search([broken])])) == "agent"

# 剛跑完補抓 tool：要不要再查一次是 LLM 的決定，不能替它收工
assert route_after_tools(_state([
    _search([]),
    ToolMessage(content="已匯入 AAPL 財報", name="fetch_company_data", tool_call_id="2"),
])) == "agent"
# 補抓後又查到今天的新聞 → 最後一則是檢索且夠新，可以收工
assert route_after_tools(_state([
    _search([], "1"),
    ToolMessage(content="已匯入", name="fetch_company_data", tool_call_id="2"),
    _search([_doc("news", 0)], "3"),
])) == "assemble"

# 完全沒有 tool 訊息（理論上不會走到）→ 交給 LLM
assert route_after_tools(_state([HumanMessage(content="seed"), AIMessage(content="x")])) == "agent"

print("route_after_tools self-check OK")
