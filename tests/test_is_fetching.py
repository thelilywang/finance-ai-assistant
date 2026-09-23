"""_is_fetching 判斷 agent 這一輪要不要補抓，決定進度顯示切不切到
「自動抓取財報/新聞」。

判錯的兩個方向都只影響顯示、不影響回答：漏判會讓補抓那段（中位 67.6s）一直停在
「檢索資料庫」，誤判會讓純檢索也閃一下抓取提示。固定住的是 tool_calls 的讀法——
agent 回傳 directive + [resp]，LLM 的回應固定在最後一則。
"""
from langchain_core.messages import AIMessage, HumanMessage

from src.graph import is_fetching as _is_fetching


def _ai(*tool_names):
    return AIMessage(
        content="",
        tool_calls=[{"name": n, "args": {}, "id": f"call_{i}"}
                    for i, n in enumerate(tool_names)],
    )


def test_is_fetching_detects_fetch_tools():
    # 補抓 tool：要提示
    assert _is_fetching({"messages": [_ai("fetch_company_data")]})
    assert _is_fetching({"messages": [_ai("fetch_market_overview")]})


def test_is_fetching_ignores_pure_retrieval():
    # 純檢索：不提示，否則每輪都閃一下
    assert not _is_fetching({"messages": [_ai("search_knowledge_base")]})


def test_is_fetching_mixed_calls():
    # 同一輪混合呼叫，只要有補抓就提示（補抓才是慢的那個）
    assert _is_fetching({"messages": [_ai("search_knowledge_base", "fetch_company_data")]})


def test_is_fetching_no_tool_calls():
    # 沒有 tool_calls＝agent 收工要進 assemble，不提示
    assert not _is_fetching({"messages": [AIMessage(content="我查完了")]})


def test_is_fetching_looks_at_last_message_only():
    # directive 在前、LLM 回應在最後：只看最後一則，別被前面的 HumanMessage 帶歪
    assert _is_fetching({"messages": [HumanMessage(content="2330 已過期"), _ai("fetch_company_data")]})


def test_is_fetching_handles_edge_cases():
    # 邊界：空 state、空 messages、缺 key 都不該炸——這是顯示層，壞了不該擋住回答
    assert not _is_fetching({})
    assert not _is_fetching({"messages": []})
    assert not _is_fetching(None)

    # HumanMessage 沒有 tool_calls 屬性，getattr 要擋掉
    assert not _is_fetching({"messages": [HumanMessage(content="hi")]})
