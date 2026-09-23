"""_trim_for_history 兩種情況（含 ## 📈 段落／超長字串）。"""
from src import config
from src.app import _trim_for_history


def test_trim_for_history_strips_trend_section():
    # 含趨勢觀點段落：應被整段去掉
    answer = "營收成長 10%。\n\n## 📈 投資趨勢觀點\n(略) \n\n免責聲明"
    result = _trim_for_history(answer)
    assert "## 📈" not in result
    assert result == "營收成長 10%。"


def test_trim_for_history_truncates_long_string():
    # 超長字串（無趨勢段落）：應截到 HISTORY_ANSWER_MAX_CHARS 字
    long_answer = "A" * (config.HISTORY_ANSWER_MAX_CHARS + 100)
    result = _trim_for_history(long_answer)
    assert len(result) == config.HISTORY_ANSWER_MAX_CHARS
