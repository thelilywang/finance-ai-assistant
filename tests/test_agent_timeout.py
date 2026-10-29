"""agent 節點的 LLM 逾時處理：逾時不重試，直接收工走 assemble。"""
import asyncio
import contextlib

import httpx

from src import config, graph
from src.i18n import t


class _TimeoutLLM:
    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        raise httpx.ReadTimeout("x")


async def _no_tools():
    return []


def test_agent_timeout_falls_through_to_assemble(monkeypatch):
    monkeypatch.setattr(graph, "_llms", lambda model: {"tool": _TimeoutLLM()})
    monkeypatch.setattr(graph._mcp_client, "get_tools", _no_tools)
    state = {"question": "TSLA 最近", "companies": ["TSLA"], "messages": [],
             "news_since_days": None, "model": ""}
    result = asyncio.run(graph.agent(state))
    last = result["messages"][-1]
    assert isinstance(last, graph.AIMessage) and not last.tool_calls
    assert graph.agent_route(result) == "assemble"


def test_llms_carry_timeout():
    graph._llms.cache_clear()
    try:
        llms = graph._llms("m")
        assert llms["tool"].client_kwargs["timeout"] == config.OLLAMA_TIMEOUT_SECONDS
    finally:
        graph._llms.cache_clear()


def test_llms_carry_num_predict():
    graph._llms.cache_clear()
    try:
        llms = graph._llms("m")
        assert llms["llm"].bound.num_predict == config.OLLAMA_NUM_PREDICT
        assert llms["tool"].num_predict == config.OLLAMA_NUM_PREDICT
    finally:
        graph._llms.cache_clear()


class _FakeLLM:
    def invoke(self, prompt):
        raise httpx.ReadTimeout("x")


def test_with_retry_skips_timeout_but_retries_connect_error():
    from langchain_core.runnables import RunnableLambda
    calls = {"n": 0}

    def boom(exc):
        def f(_):
            calls["n"] += 1
            raise exc
        return RunnableLambda(f).with_retry(
            retry_if_exception_type=graph._RETRYABLE, stop_after_attempt=3, wait_exponential_jitter=False)

    for exc, expected in ((httpx.ReadTimeout("x"), 1), (httpx.ConnectError("x"), 3)):
        calls["n"] = 0
        with contextlib.suppress(httpx.HTTPError):
            boom(exc).invoke("p")
        assert calls["n"] == expected


def test_rewrite_timeout_keeps_original_question(monkeypatch):
    monkeypatch.setattr(graph, "_llms", lambda model: {"llm": _FakeLLM()})
    state = {"question": "那毛利率呢？", "history": [("TSMC 營收", "ok")], "model": ""}
    assert graph.rewrite_question(state)["question"] == "那毛利率呢？"


def test_generate_timeout_returns_fallback_answer(monkeypatch):
    monkeypatch.setattr(graph, "_llms", lambda model: {"llm": _FakeLLM()})
    monkeypatch.setattr(graph, "get_market_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(graph, "get_market_snapshots", lambda *a, **k: {})
    state = {"question": "TSLA 如何", "companies": ["TSLA"], "lang": "zh", "model": "",
             "retrieved": [{"source": "s1", "content": "c", "company": "TSLA"}]}
    out = graph.generate(state)
    assert t("zh", "generate_timeout") in out["answer"]


def test_generate_truncated_flags_and_notices(monkeypatch):
    # done_reason=length：答案是半截的，answer 要帶截斷說明、state 要帶旗標給 app 串流端
    resp = graph.AIMessage(content="半截", response_metadata={"done_reason": "length", "eval_count": 4096})
    monkeypatch.setattr(graph, "_llms", lambda model: {"llm": type("L", (), {"invoke": lambda s, p: resp})()})
    monkeypatch.setattr(graph, "get_market_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(graph, "get_market_snapshots", lambda *a, **k: {})
    state = {"question": "TSLA 如何", "companies": ["TSLA"], "lang": "zh", "model": "",
             "retrieved": [{"source": "s1", "content": "c", "company": "TSLA"}]}
    out = graph.generate(state)
    assert out["generate_truncated"] is True
    assert out["answer"].startswith("半截\n\n" + t("zh", "generate_truncated"))
