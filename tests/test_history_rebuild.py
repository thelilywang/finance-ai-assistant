"""最小 self-check：_rebuild_history 把 ThreadDict["steps"] 還原成 on_message 用的 history。
執行：python tests/test_history_rebuild.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app import _rebuild_history


def step(step_type, output=None):
    d = {"type": step_type}
    if output is not None:
        d["output"] = output
    return d


# 交錯的 user/assistant，夾一個 tool step（應被跳過）
steps = [
    step("user_message", "第一題"),
    step("tool"),
    step("assistant_message", "第一答"),
    step("user_message", "第二題"),
    step("assistant_message", "第二答"),
]
result = _rebuild_history(steps)
assert result == [("第一題", "第一答"), ("第二題", "第二答")]

# assistant step 缺 "output"（StepDict 為 total=False）：視為空字串，不整段跳過
steps_missing_output = [
    step("user_message", "問題"),
    step("assistant_message"),  # 無 output
]
result = _rebuild_history(steps_missing_output)
assert result == [("問題", "")]

# 落單的 user step（配不成對）直接丟棄
steps_dangling = [
    step("user_message", "第一題"),
    step("assistant_message", "第一答"),
    step("user_message", "沒人回answer的問題"),
]
result = _rebuild_history(steps_dangling)
assert result == [("第一題", "第一答")]

# 超過 5 輪只留最後 5 筆，與 on_message 的 history[-5:] 一致
steps_many = []
for i in range(7):
    steps_many.append(step("user_message", f"問{i}"))
    steps_many.append(step("assistant_message", f"答{i}"))
result = _rebuild_history(steps_many)
assert len(result) == 5
assert result == [(f"問{i}", f"答{i}") for i in range(2, 7)]

print("_rebuild_history self-check OK")
