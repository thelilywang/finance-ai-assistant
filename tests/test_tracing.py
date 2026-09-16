"""自檢 tracing：關閉時安靜退場、開啟時產生可用的 config、失敗絕不往上拋。

執行：PYTHONDONTWRITEBYTECODE=1 python tests/test_tracing.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, tracing


def reset():
    tracing._client = None
    tracing._init_failed = False


# 關閉追蹤（沒設公鑰）：callbacks() 回空 dict，flush() 不炸
original = config.LANGFUSE_ENABLED
config.LANGFUSE_ENABLED = False
reset()
assert tracing.callbacks(session_id="s1") == {}, "關閉時應回空 config"
tracing.flush()  # 不應拋例外

# 開啟但 client 建立失敗：同樣要安靜回空 dict，不能讓主流程掛掉
config.LANGFUSE_ENABLED = True
reset()
tracing._init_failed = True  # 模擬初始化失敗後的狀態
assert tracing.callbacks(session_id="s1") == {}, "初始化失敗時應回空 config"
tracing.flush()

# 開啟且 SDK 正常：config 要帶得動 callbacks 與歸因用 metadata
config.LANGFUSE_ENABLED = original
reset()
if config.LANGFUSE_ENABLED:
    cfg = tracing.callbacks(session_id="s1", user_id="u1", model="qwen3.5:9b", lang="zh")
    assert cfg.get("callbacks"), "開啟時應帶 callback handler"
    meta = cfg["metadata"]
    assert meta["langfuse_session_id"] == "s1"
    assert meta["langfuse_user_id"] == "u1"
    assert meta["langfuse_release"], "release 不可為空，否則 UI 無法歸因版本"
    assert "qwen3.5:9b" in meta["langfuse_tags"]
    # None 欄位要被濾掉，不能送出一堆 null
    assert "s2" not in str(tracing.callbacks(session_id=None).get("metadata", {}))
else:
    print("（未設 LANGFUSE_PUBLIC_KEY，略過啟用路徑）")

# _release 任何情況都要回非空字串
assert tracing._release(), "_release 不可回空字串"


# --- _brief：節點 I/O 摘要 ---
# 長字串要截斷，否則整份 prompt / 回答會被送進 Langfuse 把 UI 塞爆
brief = tracing._brief({"question": "x" * 900, "companies": ["2330"], "lang": "zh"})
assert len(brief["question"]) == tracing._MAX_IO_CHARS, "長字串應截斷"
assert brief["companies"] == ["2330"]

# 大宗欄位只留筆數，不送內容
brief = tracing._brief({"retrieved": [{"id": 1}, {"id": 2}], "messages": [1, 2, 3]})
assert brief["retrieved_count"] == 2 and brief["messages_count"] == 3
assert "retrieved" not in brief and "messages" not in brief, "chunk/訊息內容不可送出"

# None 欄位濾掉；非 dict（理論上不該發生）也不能炸
assert "companies" not in tracing._brief({"companies": None})
assert tracing._brief("abc") == {"value": "abc"}

# fetch_results 每則各自截斷
brief = tracing._brief({"fetch_results": ["y" * 900]})
assert len(brief["fetch_results"][0]) == tracing._MAX_IO_CHARS


# --- node_span：關閉時零成本，開啟時不改變節點行為 ---
def _sample_node(state):
    return {**state, "answer": "ok"}


config.LANGFUSE_ENABLED = False
reset()
assert tracing.node_span(_sample_node) is _sample_node, "關閉時應原樣回傳，不付包裝成本"

config.LANGFUSE_ENABLED = original
reset()
if config.LANGFUSE_ENABLED:
    wrapped = tracing.node_span(_sample_node)
    # span 名取自 __name__，functools.wraps 沒包好的話 Langfuse 上會變成 wrapper
    assert wrapped.__name__ == "_sample_node", "節點名要保留，否則 span 名會錯"
    assert wrapped({"question": "q"})["answer"] == "ok", "包裝不得改變節點回傳值"

print("test_tracing OK")
