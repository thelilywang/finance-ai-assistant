"""_ollama_usage 從 AIMessage.response_metadata 取 token/耗時，缺的欄位不補假值。
截斷 warning（_warn_if_truncated）用 num_ctx 一半當門檻，附帶驗證 caplog 能收到 log.warning。
"""
import logging

from langchain_core.messages import AIMessage

from src import config
from src.graph import _ollama_usage, _warn_if_truncated

FULL_META = {
    "prompt_eval_count": 1234,
    "eval_count": 56,
    "done_reason": "stop",
    "prompt_eval_duration": 608_965_000,   # 奈秒
    "eval_duration": 1_166_675_000,
    "load_duration": 12_271_756_000,
}


def test_ollama_usage_full_metadata():
    msg = AIMessage(content="x", response_metadata=FULL_META)
    usage = _ollama_usage(msg)
    assert usage == {
        "prompt_tokens": 1234,
        "output_tokens": 56,
        "done_reason": "stop",
        "prefill_ms": 609,   # 608_965_000 ns -> round(608.965) ms
        "decode_ms": 1167,
        "load_ms": 12272,
    }


def test_ollama_usage_missing_fields():
    # 只有部分欄位（例如 stub LLM 或非 Ollama provider）時，缺的欄位不放進回傳值
    msg = AIMessage(content="x", response_metadata={"prompt_eval_count": 10})
    usage = _ollama_usage(msg)
    assert usage == {"prompt_tokens": 10}


def test_ollama_usage_empty_response_metadata():
    msg = AIMessage(content="x")  # response_metadata 預設是 {}
    assert _ollama_usage(msg) == {}


def test_warn_if_truncated_triggers_at_threshold(monkeypatch, caplog):
    monkeypatch.setattr(config, "OLLAMA_NUM_CTX", 4096)  # 門檻 = 4096//2 - 8 = 2040
    with caplog.at_level(logging.WARNING, logger="graph"):
        _warn_if_truncated("generate", "abcd1234", {"prompt_tokens": 2040})
    assert any("截斷" in r.message for r in caplog.records)
    fields = caplog.records[-1].fields
    assert fields == {"node": "generate", "qid": "abcd1234",
                       "prompt_tokens": 2040, "num_ctx": 4096}


def test_warn_if_truncated_below_threshold_is_silent(monkeypatch, caplog):
    monkeypatch.setattr(config, "OLLAMA_NUM_CTX", 4096)
    with caplog.at_level(logging.WARNING, logger="graph"):
        _warn_if_truncated("generate", "abcd1234", {"prompt_tokens": 2039})
    assert caplog.records == []


def test_warn_if_truncated_no_prompt_tokens_is_silent(caplog):
    # extract_filters 目前拿不到 usage，usage 可能是空 dict
    with caplog.at_level(logging.WARNING, logger="graph"):
        _warn_if_truncated("extract_filters", "abcd1234", {})
    assert caplog.records == []
