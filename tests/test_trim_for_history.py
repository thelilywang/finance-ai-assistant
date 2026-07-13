"""最小 self-check：_trim_for_history 兩種情況（含 ## 📈 段落／超長字串）。
執行：python tests/test_trim_for_history.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.app import _trim_for_history

# 含趨勢觀點段落：應被整段去掉
answer = "營收成長 10%。\n\n## 📈 投資趨勢觀點\n(略) \n\n免責聲明"
result = _trim_for_history(answer)
assert "## 📈" not in result
assert result == "營收成長 10%。"

# 超長字串（無趨勢段落）：應截到 HISTORY_ANSWER_MAX_CHARS 字
long_answer = "A" * (config.HISTORY_ANSWER_MAX_CHARS + 100)
result = _trim_for_history(long_answer)
assert len(result) == config.HISTORY_ANSWER_MAX_CHARS

print("_trim_for_history self-check OK")
