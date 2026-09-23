"""_rebuild_history 把 ThreadDict["steps"] 還原成 on_message 用的 history。"""
from src.app import _rebuild_history


def _step(step_type, output=None):
    d = {"type": step_type}
    if output is not None:
        d["output"] = output
    return d


def test_rebuild_history_skips_tool_steps():
    # 交錯的 user/assistant，夾一個 tool step（應被跳過）
    steps = [
        _step("user_message", "第一題"),
        _step("tool"),
        _step("assistant_message", "第一答"),
        _step("user_message", "第二題"),
        _step("assistant_message", "第二答"),
    ]
    result = _rebuild_history(steps)
    assert result == [("第一題", "第一答"), ("第二題", "第二答")]


def test_rebuild_history_missing_output():
    # assistant step 缺 "output"（StepDict 為 total=False）：視為空字串，不整段跳過
    steps_missing_output = [
        _step("user_message", "問題"),
        _step("assistant_message"),  # 無 output
    ]
    result = _rebuild_history(steps_missing_output)
    assert result == [("問題", "")]


def test_rebuild_history_dangling_user_step():
    # 落單的 user step（配不成對）直接丟棄
    steps_dangling = [
        _step("user_message", "第一題"),
        _step("assistant_message", "第一答"),
        _step("user_message", "沒人回answer的問題"),
    ]
    result = _rebuild_history(steps_dangling)
    assert result == [("第一題", "第一答")]


def test_rebuild_history_keeps_last_five_turns():
    # 超過 5 輪只留最後 5 筆，與 on_message 的 history[-5:] 一致
    steps_many = []
    for i in range(7):
        steps_many.append(_step("user_message", f"問{i}"))
        steps_many.append(_step("assistant_message", f"答{i}"))
    result = _rebuild_history(steps_many)
    assert len(result) == 5
    assert result == [(f"問{i}", f"答{i}") for i in range(2, 7)]
