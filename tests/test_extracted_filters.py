"""ExtractedFilters 的 news_since_days 夾取。

這個值會直接進 similarity_search 的 SQL 日期比較，本地模型回 0 或負數會讓條件
變成「未來的新聞」而查出空結果，所以邊界要固定住。
"""
import logging

from langchain_core.messages import AIMessage

import src.config as config
import src.graph as graph
from src.graph import ExtractedFilters


def test_news_since_days_default_none():
    # 沒指定時效 → None（不過濾）
    assert ExtractedFilters().news_since_days is None
    assert ExtractedFilters(news_since_days=None).news_since_days is None


def test_news_since_days_normal_range():
    # 正常範圍原樣保留
    assert ExtractedFilters(news_since_days=1).news_since_days == 1
    assert ExtractedFilters(news_since_days=90).news_since_days == 90
    assert ExtractedFilters(news_since_days=365).news_since_days == 365


def test_news_since_days_clamped():
    # 越界夾回範圍內：0 與負數不能讓 SQL 變成查未來的新聞
    assert ExtractedFilters(news_since_days=0).news_since_days == 1
    assert ExtractedFilters(news_since_days=-7).news_since_days == 1
    assert ExtractedFilters(news_since_days=9999).news_since_days == 365


def test_companies_normalization_unaffected():
    # companies 的正規化不受影響（同一個 model 上兩個 validator）
    assert ExtractedFilters(companies=["台積電"], news_since_days=7).news_since_days == 7

    # 「台積電」不是合法代號格式，normalize_ticker 認不得就丟掉
    assert ExtractedFilters(companies=["台積電"]).companies == []

    # 多標的：逐項正規化並去重、保序；認不得的代號丟掉
    assert ExtractedFilters(companies=["aapl", "2330.TW", "AAPL", "台積電"]).companies == ["AAPL", "2330"]


def test_extract_filters_model_switch(monkeypatch):
    """extract_filters 的模型選擇（A/B 開關）。

    換小模型的臂靠 config.FILTERS_MODEL 切換。抽錯代號會讓整條流程查錯公司，
    所以這裡固定住「空值沿用主模型、有值才覆蓋」，避免開關寫錯時兩臂其實跑同一個模型
    而量出假的「沒有差異」。
    """
    calls = []

    class _FakeFilters:
        def invoke(self, prompt):
            return {"raw": AIMessage(content=""), "parsed": ExtractedFilters(companies=["AAPL"]),
                    "parsing_error": None}

    def _fake_llms(model):
        calls.append(model)
        return {"filters": _FakeFilters()}

    monkeypatch.setattr(graph, "_llms", _fake_llms)

    state = {"question": "蘋果最近的財報表現如何？", "companies": [], "market": None,
             "model": "main-model"}

    # 空值：沿用該輪的主模型（UI 選單選的那個）
    monkeypatch.setattr(config, "FILTERS_MODEL", "")
    graph.extract_filters(dict(state))
    assert calls[-1] == "main-model", calls

    # 有值：覆蓋主模型，兩臂才真的不同
    monkeypatch.setattr(config, "FILTERS_MODEL", "small-model")
    graph.extract_filters(dict(state))
    assert calls[-1] == "small-model", calls

    # 主模型留空（舊呼叫端沒帶 model）時仍退回預設，不會傳空字串給 Ollama
    monkeypatch.setattr(config, "FILTERS_MODEL", "")
    graph.extract_filters({**state, "model": ""})
    assert calls[-1] == config.LLM_MODEL, calls


def _run_filters(monkeypatch, out, question="蘋果財報？"):
    monkeypatch.setattr(graph, "_llms", lambda m: {"filters": type(
        "F", (), {"invoke": lambda self, p: out})()})
    return graph.extract_filters({"question": question, "companies": [], "market": None,
                                  "model": "m"})


def test_extract_filters_truncated_output_warns_and_degrades(monkeypatch, caplog):
    # 撞 num_predict 上限：殘缺 JSON 實測會被寬鬆解析成功（無 parsing_error），
    # 仍要降級且留下截斷警告
    raw = AIMessage(content='{"companies": ["233',
                    response_metadata={"done_reason": "length", "eval_count": 4096})
    with caplog.at_level(logging.WARNING, logger="graph"):
        res = _run_filters(monkeypatch, {"raw": raw, "parsed": ExtractedFilters(companies=["2330"]),
                                         "parsing_error": None})
    assert res["companies"] == [] and res["in_scope"] is True and res["answer_shape"] == "full"
    assert any(
        getattr(r, "fields", {}).get("node") == "extract_filters"
        and r.fields.get("output_tokens") == 4096 for r in caplog.records), caplog.records


def _truncated(monkeypatch, question):
    raw = AIMessage(content='{"companies": ["233',
                    response_metadata={"done_reason": "length", "eval_count": 4096})
    return _run_filters(monkeypatch, {"raw": raw, "parsed": None, "parsing_error": None}, question)


def test_degraded_dual_listed_still_asks_market(monkeypatch):
    # 降級仍撿回雙掛牌公司，resolve_market 才會反問而不是跨市場檢索
    res = _truncated(monkeypatch, "台積電營收多少？")
    assert res["companies"] == ["2330"]
    assert graph.resolve_market(res)["ask_market"] is True


def test_degraded_dual_listed_keeps_stated_market(monkeypatch):
    res = graph.resolve_market(_truncated(monkeypatch, "台積電美股營收"))
    assert res["companies"] == ["TSM"] and res["market"] == "us"


def test_extract_filters_normal_no_warning(monkeypatch, caplog):
    raw = AIMessage(content="", response_metadata={"done_reason": "stop", "eval_count": 20})
    with caplog.at_level(logging.WARNING, logger="graph"):
        res = _run_filters(monkeypatch, {"raw": raw, "parsed": ExtractedFilters(companies=["AAPL"]),
                                         "parsing_error": None})
    assert res["companies"] == ["AAPL"]
    assert caplog.records == []
