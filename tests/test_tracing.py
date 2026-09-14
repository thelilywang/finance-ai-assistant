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

print("test_tracing OK")
