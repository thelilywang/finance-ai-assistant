"""Langfuse 可觀測性：把 LangGraph 的 LLM 呼叫送到 Langfuse。

追蹤是附屬功能，絕不能拖垮問答主流程，因此本模組所有進入點都不對外拋例外：
金鑰沒設、Langfuse 沒起、網路不通，都只會少一筆 trace。

用法（app.py 已接好，其他呼叫端照同一個模式）：

    from .tracing import callbacks, flush
    graph.astream(state, config=callbacks(session_id=..., user_id=...))
    flush()   # 只有 CLI / script 這類短生命週期程式需要

節點層級不必逐一加 decorator：LangChain callback handler 會跟著 graph 傳下去，
rewrite_question / extract_filters / agent / generate 四個 LLM 節點都會自動成為
同一個 trace 底下的 observation，input/output/token/延遲由 SDK 直接帶走。
"""
from __future__ import annotations

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
