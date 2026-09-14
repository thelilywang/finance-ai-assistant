"""Langfuse 可觀測性：把 LangGraph 的 LLM 呼叫送到 Langfuse。

追蹤是附屬功能，絕不能拖垮問答主流程，因此本模組所有進入點都不對外拋例外：
金鑰沒設、Langfuse 沒起、網路不通，都只會少一筆 trace。

用法（app.py 已接好，其他呼叫端照同一個模式）：

    from .tracing import callbacks, flush
    graph.astream(state, config=callbacks(session_id=..., user_id=...))
    flush()   # 只有 CLI / script 這類短生命週期程式需要

一次問答＝一個 trace：callbacks() 只在 app.py / cli.py 的進入點掛一次，
整張 graph 跑完都在同一個 trace 底下。

節點層級則由 build_graph() 用 node_span() 逐一包起來（見該函式說明）——
只靠 callback handler 的話，Langfuse 上看到的全是底層 ChatOllama 呼叫，
每個節點名字、內容都長一樣，而 resolve_market / assemble 這類不呼叫 LLM 的
節點根本不會出現。包過之後每個節點是一個具名 span，LLM generation 會靠
OTel context 自動掛在所屬節點底下，節點的 input/output 另外送截斷過的摘要。
"""
from __future__ import annotations

import functools
import inspect
import logging
import subprocess

from . import config

log = logging.getLogger("tracing")

_client = None
_init_failed = False


def _release() -> str:
    """版本識別。沒設環境變數就用當前 git commit，退無可退才回 unknown。"""
    if config.LANGFUSE_RELEASE:
        return config.LANGFUSE_RELEASE
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2, check=True,
        ).stdout.strip() or "unknown"
    except Exception:  # 容器內沒有 .git，屬正常情況
        return "unknown"


def _get_client():
    """取得 Langfuse client（單例）。失敗只記一次 warning，之後靜默跳過。"""
    global _client, _init_failed
    if _client is not None or _init_failed:
        return _client
    if not config.LANGFUSE_ENABLED:
        _init_failed = True
        return None
    try:
        from langfuse import get_client

        # 金鑰與 base_url 由 SDK 自己讀 LANGFUSE_* 環境變數（.env 已由 config 載入）
        _client = get_client()
    except Exception as e:
        _init_failed = True
        log.warning("Langfuse 初始化失敗，本次執行不送追蹤：%s", e)
    return _client


def callbacks(
    *, session_id: str | None = None, user_id: str | None = None,
    model: str | None = None, lang: str | None = None, **tags,
) -> dict:
    """回傳可直接餵給 graph.astream/invoke 的 config dict。

    追蹤關掉或初始化失敗時回傳 {}，呼叫端不必判斷——多傳一個空 config 對 LangGraph
    沒有副作用。session_id 用 chainlit 的 thread id，UI 上同一串對話才會收在一起。
    """
    if _get_client() is None:
        return {}
    try:
        from langfuse.langchain import CallbackHandler

        metadata = {
            "langfuse_session_id": session_id,
            "langfuse_user_id": user_id,
            "langfuse_release": _release(),
            "langfuse_tags": [t for t in (model, lang) if t],
        }
        metadata.update(tags)
        return {
            "callbacks": [CallbackHandler()],
            "metadata": {k: v for k, v in metadata.items() if v is not None},
        }
    except Exception as e:
        log.warning("Langfuse callback 建立失敗，本輪不送追蹤：%s", e)
        return {}


_MAX_IO_CHARS = 500


def _brief(state) -> dict:
    """節點的 input/output 摘要。只留看得懂流程的欄位，長值截斷。

    刻意不直接送整個 GraphState：retrieved 的 chunk 全文與 messages 往返動輒數千字，
    送進 Langfuse 只會把 UI 塞爆，而判斷流程走向靠的是下面這幾個欄位。
    """
    if not isinstance(state, dict):
        return {"value": str(state)[:_MAX_IO_CHARS]}
    brief = {}
    for key in ("question", "company", "doc_type", "market", "lang", "model",
                "news_since_days", "in_scope", "off_topic", "ask_market",
                "fetched", "answer"):
        if (value := state.get(key)) is not None:
            brief[key] = str(value)[:_MAX_IO_CHARS] if isinstance(value, str) else value
    if (retrieved := state.get("retrieved")) is not None:
        brief["retrieved_count"] = len(retrieved)
    if (messages := state.get("messages")) is not None:
        brief["messages_count"] = len(messages)
    if fetch_results := state.get("fetch_results"):
        brief["fetch_results"] = [str(r)[:_MAX_IO_CHARS] for r in fetch_results]
    return brief


def node_span(func):
    """把 LangGraph 節點包成一個具名 span，帶截斷過的 input/output。

    Langfuse 自動追蹤只看得到底層的 ChatOllama 呼叫，UI 上每個節點長得一模一樣，
    也完全看不到 resolve_market/assemble 這些不呼叫 LLM 的節點。包一層之後，
    節點名就是 span 名，LLM generation 靠 OTel context 自動掛在該節點底下。

    追蹤未啟用時原樣回傳，不付任何代價，也不會因為 Langfuse 有問題而拖垮節點。
    """
    client = _get_client()
    if client is None:
        return func

    # 刻意不用 @observe：它的 span 在函式回傳時就關了，之後再寫 input/output 會落到
    # 父層（實測會全部疊在 trace 根上互相覆蓋，正是「每個節點 output 都一樣」的成因）。
    # 自己開 span 才能在 span 還活著的時候把 output 寫進去。
    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def wrapper(state, *args, **kwargs):
            with client.start_as_current_observation(
                name=func.__name__, input=_brief(state)
            ) as span:
                result = await func(state, *args, **kwargs)
                span.update(output=_brief(result))
                return result
    else:
        @functools.wraps(func)
        def wrapper(state, *args, **kwargs):
            with client.start_as_current_observation(
                name=func.__name__, input=_brief(state)
            ) as span:
                result = func(state, *args, **kwargs)
                span.update(output=_brief(result))
                return result
    return wrapper


def flush() -> None:
    """把待送的 trace 送出。長駐服務（chainlit）靠背景批次，不需呼叫；
    CLI / script 結束前要呼叫一次，否則程序結束時 trace 會遺失。"""
    client = _get_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception as e:  # flush 失敗不能讓主流程跟著收掉
        log.warning("Langfuse flush 失敗，可能遺失追蹤：%s", e)
