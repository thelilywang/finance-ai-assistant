"""fetch_missing_data 收集各來源結果訊息，單一來源失敗不中斷、不吞訊息，
且每筆耗時 log 帶正確的 company／source（市場總覽新聞不掛在當次查詢的公司名下）。

原本的 route_after_retrieve/needs_refetch 測試已隨函式移除——「資料夠不夠新、要不要補抓」
現在由 LLM 依 MCP tool 說明自行判斷（見 src/mcp_server.py 的 docstring），沒有確定性路由可測。
"""
import asyncio
import json

import pytest

import src.graph as graph
import src.update as update
from src.graph import fetch_missing_data
from src.update import FetchResult


@pytest.fixture
def logged(monkeypatch):
    # 攔 log_duration 收欄位：驗 company/source 標籤有沒有貼錯到隔壁那筆
    records = []
    monkeypatch.setattr(graph, "log_duration", lambda log, event, started, **f: records.append(f))
    return records


@pytest.fixture(autouse=True)
def _stub_fetch_sources(monkeypatch):
    # 台股財報兩軌：官方 API 與 MOPS 各自獨立成敗，都要 patch 掉否則會真的連外
    monkeypatch.setattr(update, "fetch_tw_financials", lambda co_id: FetchResult(True, "已匯入 2330 115Q2 財報數字"))
    monkeypatch.setattr(update, "fetch_mops", lambda co_id: FetchResult(False, "MOPS 查無財報"))
    monkeypatch.setattr(update, "fetch_news", lambda company, limit=10: FetchResult(True, "已寫入 3 筆"))
    monkeypatch.setattr(update, "fetch_market_news", lambda limit_per_source=10: FetchResult(True, "已寫入 2 筆"))
    # 美股分支雖未在本測試中走到，但 fetch_missing_data 會 import 到，不 patch 會真的連外
    monkeypatch.setattr(update, "fetch_sec_financials", lambda ticker: FetchResult(True, "已匯入 AAPL XBRL 財報數字"))


def test_fetch_missing_data_keeps_all_source_messages(logged):
    results = fetch_missing_data("2330", has_report=False)
    # 一軌失敗一軌成功：兩則訊息都要保留，不因其中一軌掛掉就少一則
    assert results == ["已匯入 2330 115Q2 財報數字", "MOPS 查無財報", "已寫入 3 筆", "已寫入 2 筆"]


def test_fetch_missing_data_source_exception_does_not_abort(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("網路逾時")

    monkeypatch.setattr(update, "fetch_mops", _boom)
    results = fetch_missing_data("2330", has_report=False)
    assert results[1] == "抓取失敗：網路逾時"  # 例外不中斷後續來源
    assert results[0] == "已匯入 2330 115Q2 財報數字"  # 另一軌不受影響
    assert results[2:] == ["已寫入 3 筆", "已寫入 2 筆"]


def test_fetch_missing_data_has_report_skips_financial_tracks():
    # has_report=True 只補新聞，兩軌財報都不重抓（依賴新聞排在最後）
    results = fetch_missing_data("2330", has_report=True)
    assert results == ["已寫入 3 筆", "已寫入 2 筆"]


def test_fetch_missing_data_logs_correct_company_and_source(logged):
    # 市場總覽新聞與特定公司無關，記成 company=None 才不會灌水該公司的抓取成功率
    fetch_missing_data("2330", has_report=False)
    assert [(f["company"], f["source"], f["ok"]) for f in logged] == [
        ("2330", "fetch_tw_financials", True),
        ("2330", "fetch_mops", False),
        ("2330", "fetch_news", True),
        (None, "fetch_market_news", True),
    ]


def test_fetch_missing_data_logs_correct_labels_on_exception_path(monkeypatch, logged):
    # 例外那條路徑也要帶對標籤（成功/失敗兩處 log_duration 各自帶參數，容易漏改一邊）
    def _boom(*a, **k):
        raise RuntimeError("網路逾時")

    monkeypatch.setattr(update, "fetch_mops", _boom)
    fetch_missing_data("2330", has_report=False)
    assert (logged[1]["company"], logged[1]["source"], logged[1]["ok"]) == ("2330", "fetch_mops", False)
    assert logged[-1]["company"] is None


# --- agent() 的 directive 要同時指名 stale 與 missing ---
# 迴歸防線：修前 `if stale := _stale_companies(state)[0]:` 丟掉了 missing，
# 零新聞的標的（如 TSM）永遠進不了 directive，補抓從未被觸發（見待辦4）。
#
# missing 的正確語意是「查過庫、結果裡沒有該公司的新聞」，不是「還沒查」。
# 首輪（messages=[]）根本沒有檢索結果可判斷，若仍把每家都塞進 missing，
# 會產生「TSM 完全沒有檢索到新聞」的 directive，叫模型去重抓剛抓完的公司、
# 或在第一輪都還沒查庫時就搶先補抓（一次 1-3 分鐘）。這種「無從判斷」的情況
# 要交還 LLM 依 tool 說明自行先查庫，不該指名任何公司。
class _FakeToolLLM:
    """假 bind_tools 鏈：回一則沒有 tool_calls 的訊息，讓 agent() 立刻收工。"""

    def __init__(self, sent_messages):
        self._sent_messages = sent_messages

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self._sent_messages.clear()
        self._sent_messages.extend(messages)
        return graph.AIMessage(content="ok")


async def _fake_get_tools():
    return []


@pytest.fixture
def _stub_agent_llm(monkeypatch):
    sent_messages: list = []
    monkeypatch.setattr(graph, "_llms", lambda model: {"tool": _FakeToolLLM(sent_messages)})
    monkeypatch.setattr(graph._mcp_client, "get_tools", _fake_get_tools)
    return sent_messages


def test_agent_directive_case_a_first_turn_no_retrieval_yet(_stub_agent_llm):
    # 案例 A：首輪、完全還沒檢索 → 無從判斷，不該指名任何公司
    sent_messages = _stub_agent_llm
    state = {
        "question": "TSM 最近新聞", "companies": ["TSM"], "messages": [],
        "news_since_days": None, "model": "",
    }
    result = asyncio.run(graph.agent(state))
    directive_msgs = [m for m in result["messages"] if isinstance(m, graph.HumanMessage)]
    assert not directive_msgs, f"首輪未檢索不該有 directive，卻收到：{directive_msgs}"
    assert not any("完全沒有檢索到新聞" in getattr(m, "content", "") for m in sent_messages), sent_messages


def test_agent_directive_case_b_retrieved_but_missing_company(_stub_agent_llm):
    # 案例 B：檢索過，但結果裡沒有 TSM 的新聞 → 這才是真正的 missing
    sent_messages = _stub_agent_llm
    other_company_chunk = {
        "id": 1, "source": "s1", "doc_type": "news", "company": "NVDA",
        "published_at": graph.dt.date.today().isoformat(), "content": "內容",
    }
    state = {
        "question": "TSM 最近新聞", "companies": ["TSM"],
        "messages": [graph.ToolMessage(
            content=json.dumps({"summary_for_llm": "x", "chunks": [other_company_chunk]}),
            name="search_knowledge_base", tool_call_id="1")],
        "news_since_days": None, "model": "",
    }
    result = asyncio.run(graph.agent(state))
    directive_msgs = [m for m in result["messages"] if isinstance(m, graph.HumanMessage)]
    assert directive_msgs, "零新聞標的應觸發 directive，結果卻是空的"
    text = directive_msgs[0].content
    assert "TSM" in text and "完全沒有檢索到新聞" in text, text
    # 送進模型的訊息裡也要看得到 directive，否則模型收不到指名
    assert any("TSM" in getattr(m, "content", "") for m in sent_messages), "directive 沒送進模型"
