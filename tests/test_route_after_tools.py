"""route_after_tools 只在「資料明顯夠用」時收工。

判錯的代價不對稱：誤判成 assemble 會拿過期資料回答（該補抓卻沒補），
誤判成 agent 只是多花一輪。所以這裡把每個該回 agent 的情境都固定住。
"""
import asyncio
import datetime as dt
import json
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import src.graph as graph
from src.graph import _stale_companies, agent_route, route_after_tools

TODAY = dt.date.today()


def _doc(doc_type, days_ago, doc_id=1, company=None):
    published = (TODAY - dt.timedelta(days=days_ago)).isoformat() if days_ago is not None else None
    return {"id": doc_id, "source": f"s{doc_id}", "doc_type": doc_type,
            "company": company, "published_at": published, "content": "內容"}


def _search(docs, cid="1"):
    return ToolMessage(
        content=json.dumps({"summary_for_llm": "摘要", "chunks": docs}, ensure_ascii=False),
        name="search_knowledge_base", tool_call_id=cid)


def _search_blocks(docs, cid="1"):
    """MCP tool 經 langchain-mcp-adapters 回來的真實形狀：content block 陣列而非字串。

    實測方向二沒 fire 就是敗在這裡——直接 json.loads(m.content) 丟 TypeError
    被 except 吞掉，靜默退化成「沒有新聞」，而測試全都用字串故測不出來。
    """
    return ToolMessage(
        content=[{"type": "text", "text": json.dumps(
            {"summary_for_llm": "摘要", "chunks": docs}, ensure_ascii=False)}],
        name="search_knowledge_base", tool_call_id=cid)


def _state(messages, news_since_days=None, companies=None):
    return {"question": "AAPL 營收多少？", "messages": messages,
            "news_since_days": news_since_days, "companies": companies or []}


REPORT = _doc("financial_report", 40, 9)


def test_route_freshness_threshold():
    # 今天的新聞 → 明顯夠用，直接收工
    assert route_after_tools(_state([_search([REPORT, _doc("news", 0)])])) == "assemble"
    # 3 天內的新聞 → 一般問題視為夠新
    assert route_after_tools(_state([_search([REPORT, _doc("news", 3)])])) == "assemble"
    # 4 天前的新聞 → 超過門檻，交還 LLM 決定要不要補抓
    assert route_after_tools(_state([_search([REPORT, _doc("news", 4)])])) == "agent"


def test_route_freshness_threshold_with_news_since_days():
    # 問題要求近期（時效窗 <= 7 天）時門檻收緊到當天
    assert route_after_tools(_state([_search([_doc("news", 0)])], 7)) == "assemble"
    assert route_after_tools(_state([_search([_doc("news", 2)])], 7)) == "agent"
    # 時效窗 90 天（「最近三個月」）不算要求當天，仍走 3 天門檻
    assert route_after_tools(_state([_search([_doc("news", 2)])], 90)) == "assemble"
    assert route_after_tools(_state([_search([_doc("news", 4)])], 90)) == "agent"


def test_route_defers_to_llm_when_ambiguous():
    # 只有財報、沒有新聞 → 不自作主張，交給 LLM
    assert route_after_tools(_state([_search([REPORT])])) == "agent"
    # 查無資料 → 交給 LLM 決定補抓
    assert route_after_tools(_state([_search([])])) == "agent"
    # 新聞沒有發布日期 → 無從判斷時效，交給 LLM
    assert route_after_tools(_state([_search([_doc("news", None)])])) == "agent"
    # 日期格式異常不能炸掉路由
    broken = {"id": 1, "source": "s", "doc_type": "news", "published_at": "不是日期", "content": "x"}
    assert route_after_tools(_state([_search([broken])])) == "agent"


def test_route_after_fetch_tool_call():
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


def test_route_multi_company_per_company_freshness():
    # 多標的：retrieved 是各家與全域新聞合併後的結果，min 會讓最新的那筆代表全部，
    # 所以新鮮度必須逐家算。實測情境：全域新聞 0 天、台積電 1 天、ASML 65 天——
    # 合併取 min 是 0，看起來夠新，但 ASML 過期，必須交還 LLM 去補抓。
    mixed = [_doc("news", 0, 1), _doc("news", 1, 2, "2330"), _doc("news", 65, 3, "ASML")]
    assert route_after_tools(_state([_search(mixed)], companies=["2330", "ASML"])) == "agent"
    # 每家都夠新 → 不必為了讓模型說一句「夠了，停」再付一輪（實測 96 至 277 秒）
    both_fresh = [_doc("news", 0, 1), _doc("news", 1, 2, "2330"), _doc("news", 2, 3, "ASML")]
    assert route_after_tools(_state([_search(both_fresh)], companies=["2330", "ASML"])) == "assemble"
    # 有公司完全沒檢索到新聞（全域新聞再新也不算）→ 不替 LLM 決定
    only_one = [_doc("news", 0, 1), _doc("news", 1, 2, "2330")]
    assert route_after_tools(_state([_search(only_one)], companies=["2330", "ASML"])) == "agent"
    # 逐家判斷對時效窗一樣生效：窗 <= 7 天時門檻收緊到當天，ASML 的 2 天就不夠新
    assert route_after_tools(_state([_search(both_fresh)], 7, ["2330", "ASML"])) == "agent"
    # 補抓後的重查：新資料入庫，兩家都夠新就收工。
    # 重查是對整題重跑一次檢索，兩家的 chunk 都會回來，不是只回補抓的那家。
    assert route_after_tools(_state([
        _search(mixed, "1"),
        ToolMessage(content="新聞更新完成", name="fetch_company_data", tool_call_id="2"),
        _search([_doc("news", 0, 4, "ASML"), _doc("news", 1, 5, "2330")], "3"),
    ], companies=["2330", "ASML"])) == "assemble"
    # 單標的維持原行為：合併取 min，不受逐家邏輯影響
    fresh = [REPORT, _doc("news", 0, 1, "2330")]  # 過濾後只認本題標的的新聞
    assert route_after_tools(_state([_search(fresh)], companies=["2330"])) == "assemble"


def test_route_no_tool_messages_defers_to_llm():
    # 完全沒有 tool 訊息（理論上不會走到）→ 交給 LLM
    assert route_after_tools(_state([HumanMessage(content="seed"), AIMessage(content="x")])) == "agent"


def test_stale_companies_shared_logic():
    # --- _stale_companies：route_after_tools 與 agent 共用的逐家判斷 ---
    # 兩處用同一個函式才不會漂移：條件邊決定「要不要回」，agent 決定「訊息裡指名誰」。
    mixed = [_doc("news", 0, 1), _doc("news", 1, 2, "2330"), _doc("news", 65, 3, "ASML")]
    both_fresh = [_doc("news", 0, 1), _doc("news", 1, 2, "2330"), _doc("news", 2, 3, "ASML")]
    only_one = [_doc("news", 0, 1), _doc("news", 1, 2, "2330")]

    stale, missing = _stale_companies(_state([_search(mixed)], companies=["2330", "ASML"]))
    assert stale == [("ASML", 65)], stale        # 只有過期的那家，且帶天數
    assert missing == [], missing
    # 兩家都夠新 → 都不列入
    assert _stale_companies(_state([_search(both_fresh)], companies=["2330", "ASML"])) == ([], [])
    # 完全沒檢索到的家歸 missing，不是 stale——兩者的處置不同（後者才要指名補抓）
    assert _stale_companies(
        _state([_search(only_one)], companies=["2330", "ASML"])
    ) == ([], ["ASML"])
    # 時效窗收緊（門檻 0 天）時，1 天的 2330 與 2 天的 ASML 都算過期，兩家都要指名
    assert _stale_companies(
        _state([_search(both_fresh)], 7, ["2330", "ASML"])
    )[0] == [("2330", 1), ("ASML", 2)]
    # 補抓並重查後：只認補抓之後的那次檢索。原本以為新 chunk 會讓 min 自然下降，
    # 實測不成立——舊那次的 65 天留在訊息串裡，min 永遠是 65，同一家被重複指名到
    # 輪數上限。改以最後一次 fetch_company_data 為界，補抓前的結果一律不計入。
    assert _stale_companies(_state([
        _search(mixed, "1"),
        ToolMessage(content="新聞更新完成", name="fetch_company_data", tool_call_id="2"),
        _search([_doc("news", 0, 4, "ASML"), _doc("news", 1, 5, "2330")], "3"),
    ], companies=["2330", "ASML"])) == ([], [])


def _run_agent(state):
    # --- agent 節點把過期標的的代號寫進訊息 ---
    # 實測：模型讀到「該補抓」會照做卻補錯家（補了距今 1 天的 NVDA，漏了 18 天的 2454）。
    # 程式端已經知道是哪一家，直接指名。這裡只驗訊息內容與是否寫回 state，不呼叫 LLM。
    reply = AIMessage(content="ok")
    fake = MagicMock()  # bind_tools 是同步的，用 AsyncMock 會回 coroutine
    fake.bind_tools.return_value.ainvoke = AsyncMock(return_value=reply)
    with patch.object(graph, "_mcp_client") as client, \
         patch.object(graph, "_llms", return_value={"tool": fake}):
        client.get_tools = AsyncMock(return_value=[])
        out = asyncio.run(graph.agent(state))
    return out, fake.bind_tools.return_value.ainvoke.call_args[0][0]


def test_agent_names_stale_company_in_directive():
    mixed = [_doc("news", 0, 1), _doc("news", 1, 2, "2330"), _doc("news", 65, 3, "ASML")]
    st = _state([_search(mixed)], companies=["2330", "ASML"])
    out, sent = _run_agent(st)
    assert "ASML" in sent[-1].content and "65 天" in sent[-1].content, sent[-1].content
    assert "fetch_company_data" in sent[-1].content
    assert "2330" not in sent[-1].content, sent[-1].content  # 夠新的那家不該被指名
    # 指名訊息必須寫回 state：只塞給這次呼叫的話，下一輪歷史裡沒有它，模型又會補錯家
    assert len(out["messages"]) == 2 and out["messages"][0] is sent[-1]


def test_agent_no_directive_when_all_fresh():
    both_fresh = [_doc("news", 0, 1), _doc("news", 1, 2, "2330"), _doc("news", 2, 3, "ASML")]
    # 都夠新時不加任何訊息，也不改變 state 的形狀
    out, sent = _run_agent(_state([_search(both_fresh)], companies=["2330", "ASML"]))
    assert len(sent) == 1 and len(out["messages"]) == 1


def test_agent_directive_handles_content_blocks():
    mixed = [_doc("news", 0, 1), _doc("news", 1, 2, "2330"), _doc("news", 65, 3, "ASML")]
    # content block 陣列（MCP 的真實形狀）要和字串走同一條路：兩處判斷都不能靜默退化
    blocks_st = _state([_search_blocks(mixed)], companies=["2330", "ASML"])
    assert route_after_tools(blocks_st) == "agent"
    out, sent = _run_agent(blocks_st)
    assert "ASML" in sent[-1].content and "2330" not in sent[-1].content, sent[-1].content


def test_agent_directive_ignores_stale_data_before_refetch():
    mixed = [_doc("news", 0, 1), _doc("news", 1, 2, "2330"), _doc("news", 65, 3, "ASML")]
    # 補抓後重查到新的新聞 → 舊那次的過期天數不得再列入，否則會重複指名到輪數上限
    refetched = [
        _search(mixed),
        ToolMessage(content="新聞更新完成", name="fetch_company_data", tool_call_id="2"),
        _search([_doc("news", 0, 20, "ASML"), _doc("news", 0, 21, "2330")], cid="3"),
    ]
    out, sent = _run_agent(_state(refetched, companies=["2330", "ASML"]))
    assert len(sent) == 3 and len(out["messages"]) == 1, sent[-1].content
    assert route_after_tools(_state(refetched, companies=["2330", "ASML"])) == "assemble"

    # 剛補抓完、還沒重查 → 沒有檢索結果可判斷，交還 LLM 且不得憑舊結果指名
    just_fetched = refetched[:2]
    assert route_after_tools(_state(just_fetched, companies=["2330", "ASML"])) == "agent"
    out, sent = _run_agent(_state(just_fetched, companies=["2330", "ASML"]))
    assert len(sent) == 2 and len(out["messages"]) == 1, sent[-1].content


# --- 輪數上限何時會被觸及：五題十樣本實測全部 ≤3 輪，這裡固定住原因 ---
# 上限在 agent_route 執行（數 messages 裡帶 tool_calls 的 AIMessage），
# route_after_tools 本身沒有輪數概念。能一路撞到上限的只有一種路徑：
# 補抓後重查「仍然」過期，stale 不消失，agent → tools → agent 無限繞。
# 864e7ad 指名過期標的之後，補抓一次就補對，重查變 0 天，循環當場斷掉——
# 這就是實測摸不到上限 4 的原因，不是運氣。


def _ai_call(name, cid):
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": cid}])


def test_round_limit_broken_by_fresh_refetch():
    mixed = [_doc("news", 0, 1), _doc("news", 1, 2, "2330"), _doc("news", 65, 3, "ASML")]
    # 補抓成功 → 重查夠新 → stale 清空 → route 收工，循環斷在第 2 輪
    fixed = [
        _search(mixed, "1"),
        _ai_call("fetch_company_data", "2"),
        ToolMessage(content="新聞更新完成", name="fetch_company_data", tool_call_id="2"),
        _search([_doc("news", 0, 30, "ASML"), _doc("news", 0, 31, "2330")], "3"),
    ]
    assert _stale_companies(_state(fixed, companies=["2330", "ASML"])) == ([], [])
    assert route_after_tools(_state(fixed, companies=["2330", "ASML"])) == "assemble"


def test_round_limit_not_broken_when_still_stale():
    mixed = [_doc("news", 0, 1), _doc("news", 1, 2, "2330"), _doc("news", 65, 3, "ASML")]
    # 補抓「補不新」→ 重查仍過期 → 每輪都重新指名，這才是會撞上限的情境。
    # 只讀最後一次 fetch 之後的檢索，所以舊天數不是主因，是重查真的還舊。
    still_stale = [
        _search(mixed, "1"),
        _ai_call("fetch_company_data", "2"),
        ToolMessage(content="新聞更新完成", name="fetch_company_data", tool_call_id="2"),
        _search([_doc("news", 65, 32, "ASML"), _doc("news", 1, 33, "2330")], "3"),
    ]
    assert _stale_companies(_state(still_stale, companies=["2330", "ASML"]))[0] == [("ASML", 65)]
    assert route_after_tools(_state(still_stale, companies=["2330", "ASML"])) == "agent"
    # 且 agent 會再次指名同一家——循環就是這樣成立的
    out, sent = _run_agent(_state(still_stale, companies=["2330", "ASML"]))
    assert "ASML" in sent[-1].content and "65 天" in sent[-1].content


def test_round_limit_forces_assemble():
    # 上限是這個循環唯一的出口：湊滿 _MAX_TOOL_ROUNDS 輪就強制收工，
    # 不論最後一輪是不是還想呼叫工具（否則每輪都是真實外部請求）。
    at_limit = [_ai_call("fetch_company_data", str(i)) for i in range(graph._MAX_TOOL_ROUNDS)]
    assert agent_route({"messages": at_limit}) == "assemble"
    # 差一輪時不收工，確認上限值本身有生效而不是恆為 assemble
    under = at_limit[:-1] + [_ai_call("search_knowledge_base", "x")]
    assert agent_route({"messages": under[:graph._MAX_TOOL_ROUNDS - 1]}) == "tools"
