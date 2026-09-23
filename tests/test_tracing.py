"""自檢 tracing：關閉時安靜退場、開啟時產生可用的 config、失敗絕不往上拋。

「開啟」的案例一律換成假 client：真的 get_client() 會讀 .env 的金鑰，
測試結束時把 span 送到真的 Langfuse。
"""
from unittest.mock import MagicMock

from src import config, tracing


def _reset(monkeypatch):
    monkeypatch.setattr(tracing, "_client", None)
    monkeypatch.setattr(tracing, "_init_failed", False)


def test_tracing_disabled_returns_empty(monkeypatch):
    # 關閉追蹤（沒設公鑰）：callbacks() 回空 dict，flush() 不炸
    monkeypatch.setattr(config, "LANGFUSE_ENABLED", False)
    _reset(monkeypatch)
    assert tracing.callbacks(session_id="s1") == {}, "關閉時應回空 config"
    tracing.flush()  # 不應拋例外


def test_tracing_init_failed_returns_empty(monkeypatch):
    # 開啟但 client 建立失敗：同樣要安靜回空 dict，不能讓主流程掛掉
    monkeypatch.setattr(config, "LANGFUSE_ENABLED", True)
    _reset(monkeypatch)
    monkeypatch.setattr(tracing, "_init_failed", True)  # 模擬初始化失敗後的狀態
    assert tracing.callbacks(session_id="s1") == {}, "初始化失敗時應回空 config"
    tracing.flush()


def test_tracing_enabled_builds_config(monkeypatch):
    # 開啟且 SDK 正常：config 要帶得動 callbacks 與歸因用 metadata
    import langfuse.langchain
    _reset(monkeypatch)
    monkeypatch.setattr(config, "LANGFUSE_ENABLED", True)
    monkeypatch.setattr(tracing, "_client", MagicMock())
    # CallbackHandler() 內部也會自己 get_client()，一樣要換掉
    monkeypatch.setattr(langfuse.langchain, "CallbackHandler", MagicMock)
    cfg = tracing.callbacks(session_id="s1", user_id="u1", model="qwen3.5:9b", lang="zh")
    assert cfg.get("callbacks"), "開啟時應帶 callback handler"
    meta = cfg["metadata"]
    assert meta["langfuse_session_id"] == "s1"
    assert meta["langfuse_user_id"] == "u1"
    assert meta["langfuse_release"], "release 不可為空，否則 UI 無法歸因版本"
    assert "qwen3.5:9b" in meta["langfuse_tags"]
    # None 欄位要被濾掉，不能送出一堆 null
    assert "langfuse_session_id" not in tracing.callbacks(session_id=None)["metadata"]


def test_release_never_empty():
    # _release 任何情況都要回非空字串
    assert tracing._release(), "_release 不可回空字串"


def test_brief_truncates_long_strings():
    # 長字串要截斷，否則整份 prompt / 回答會被送進 Langfuse 把 UI 塞爆
    brief = tracing._brief({"question": "x" * 900, "companies": ["2330"], "lang": "zh"})
    assert len(brief["question"]) == tracing._MAX_IO_CHARS, "長字串應截斷"
    assert brief["companies"] == ["2330"]


def test_brief_summarizes_bulk_fields():
    # 大宗欄位只留筆數，不送內容
    brief = tracing._brief({"retrieved": [{"id": 1}, {"id": 2}], "messages": [1, 2, 3]})
    assert brief["retrieved_count"] == 2 and brief["messages_count"] == 3
    assert "retrieved" not in brief and "messages" not in brief, "chunk/訊息內容不可送出"


def test_brief_filters_none_and_handles_non_dict():
    # None 欄位濾掉；非 dict（理論上不該發生）也不能炸
    assert "companies" not in tracing._brief({"companies": None})
    assert tracing._brief("abc") == {"value": "abc"}


def test_brief_truncates_fetch_results():
    # fetch_results 每則各自截斷
    brief = tracing._brief({"fetch_results": ["y" * 900]})
    assert len(brief["fetch_results"][0]) == tracing._MAX_IO_CHARS


def test_node_span_disabled_returns_same_function(monkeypatch):
    def _sample_node(state):
        return {**state, "answer": "ok"}

    monkeypatch.setattr(config, "LANGFUSE_ENABLED", False)
    _reset(monkeypatch)
    assert tracing.node_span(_sample_node) is _sample_node, "關閉時應原樣回傳，不付包裝成本"


def test_node_span_enabled_preserves_behavior(monkeypatch):
    def _sample_node(state):
        return {**state, "answer": "ok"}

    _reset(monkeypatch)
    monkeypatch.setattr(config, "LANGFUSE_ENABLED", True)
    client = MagicMock()
    monkeypatch.setattr(tracing, "_client", client)
    wrapped = tracing.node_span(_sample_node)
    # span 名取自 __name__，functools.wraps 沒包好的話 Langfuse 上會變成 wrapper
    assert wrapped.__name__ == "_sample_node", "節點名要保留，否則 span 名會錯"
    assert wrapped({"question": "q"})["answer"] == "ok", "包裝不得改變節點回傳值"
    assert client.start_as_current_observation.call_args.kwargs["name"] == "_sample_node"
