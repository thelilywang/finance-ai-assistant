"""_compose_final_content：串流半截內容 + 逾時說明 + 免責聲明的組字串。"""
from src.app import _compose_final_content
from src.graph import append_disclaimer
from src.i18n import t


def test_partial_and_timed_out_keeps_partial_with_notice_and_disclaimer():
    out = _compose_final_content("半截內容", "逾時文案", True, "zh")
    assert out.startswith("半截內容")
    assert t("zh", "generate_timeout_partial") in out
    assert out == append_disclaimer("半截內容\n\n" + t("zh", "generate_timeout_partial"), "zh")
    assert out.index("半截內容") < out.index(t("zh", "generate_timeout_partial"))


def test_partial_not_timed_out_unchanged():
    assert _compose_final_content("完整回答", "x", False, "en") == append_disclaimer("完整回答", "en")


def test_empty_stream_uses_answer():
    assert _compose_final_content("", "answer", True, "zh") == "answer"
    assert _compose_final_content("", "answer", False, "zh") == "answer"
