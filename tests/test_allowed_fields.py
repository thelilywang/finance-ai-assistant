"""最小 self-check：allowed_fields 的 answer_shape × evidence 判準矩陣。
執行：python tests/test_allowed_fields.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.graph import allowed_fields

FULL_ONLY = {"valuation", "consensus", "scenario", "earnings_call", "recommendation"}
UNCONDITIONAL = {"conclusion", "facts", "inference", "upside", "risk"}

news_dated = [{"id": 1, "doc_type": "news", "published_at": "2026-09-01"}]
news_undated = [{"id": 1, "doc_type": "news"}]
financial = [{"id": 2, "doc_type": "financial_report"}]
financial_and_news = financial + news_dated

# 1: news + 新聞含日期 + no market -> 8 個無條件/optional 欄，無 5 個 full-only 欄
fields = set(allowed_fields({"answer_shape": "news", "retrieved": news_dated}, has_market=False))
assert fields == UNCONDITIONAL | {"trigger", "next_event", "tracking_indicators"}, fields
assert not (fields & FULL_ONLY)

# 2: news + 新聞無日期 -> 無 next_event，其餘同 #1
fields = set(allowed_fields({"answer_shape": "news", "retrieved": news_undated}, has_market=False))
assert fields == UNCONDITIONAL | {"trigger", "tracking_indicators"}, fields
assert "next_event" not in fields

# 3: news + 空 retrieved -> 僅 5 個無條件欄
fields = set(allowed_fields({"answer_shape": "news", "retrieved": []}, has_market=False))
assert fields == UNCONDITIONAL, fields

# 4: full + 財報+新聞 + has_market=True -> 全欄含 recommendation
fields = set(allowed_fields({"answer_shape": "full", "retrieved": financial_and_news}, has_market=True))
assert fields == UNCONDITIONAL | FULL_ONLY | {"trigger", "next_event", "tracking_indicators"}, fields
assert "recommendation" in fields

# 5: full + 僅新聞 + has_market=True -> 無 earnings_call、無 recommendation（三要件不齊）
fields = set(allowed_fields({"answer_shape": "full", "retrieved": news_dated}, has_market=True))
assert "earnings_call" not in fields
assert "recommendation" not in fields
assert {"valuation", "consensus", "scenario"} <= fields

# 6: full + 財報+新聞 + has_market=False -> 無 valuation/consensus/scenario/recommendation
fields = set(allowed_fields({"answer_shape": "full", "retrieved": financial_and_news}, has_market=False))
assert not ({"valuation", "consensus", "scenario", "recommendation"} & fields), fields

# 7: full + 財報+新聞 + has_market=None（第一段）-> valuation/consensus/scenario 在候選集內
fields = set(allowed_fields({"answer_shape": "full", "retrieved": financial_and_news}, has_market=None))
assert {"valuation", "consensus", "scenario"} <= fields, fields

# 8: 缺 answer_shape（None）-> 等同 full（驗證 state.get("answer_shape") or "full"）
fields = set(allowed_fields({"retrieved": financial_and_news}, has_market=True))
assert fields == UNCONDITIONAL | FULL_ONLY | {"trigger", "next_event", "tracking_indicators"}, fields

# 9: 開關 off -> 回傳現行全欄，與 answer_shape/evidence 無關（單一公司題仍不含 comparison）
config.ANSWER_SHAPE_GATING = False
try:
    fields = set(allowed_fields({"answer_shape": "news", "retrieved": []}, has_market=False))
    assert fields == UNCONDITIONAL | FULL_ONLY | {"trigger", "next_event", "tracking_indicators"}, fields
finally:
    config.ANSWER_SHAPE_GATING = True

# 10: 所有組合下，5 個無條件欄恆為子集（不整段棄權迴歸防線）
combos = [
    {"answer_shape": s, "retrieved": r}
    for s in ("news", "full", None)
    for r in ([], news_dated, news_undated, financial, financial_and_news)
]
for hm in (None, True, False):
    for state in combos:
        fields = set(allowed_fields(state, has_market=hm))
        assert UNCONDITIONAL <= fields, (state, hm, fields)

# 11: 任何組合下回傳值中永不出現 "impact"
for hm in (None, True, False):
    for state in combos:
        assert "impact" not in allowed_fields(state, has_market=hm)

# 12: comparison 閘門（多標的專屬欄）
two = {"companies": ["2330", "2454"], "answer_shape": "full", "retrieved": financial_and_news}
assert "comparison" in allowed_fields(two, has_market=True)

# 12b: 多標的 + full + retrieved 為空 -> 不含（沒素材無法做定性對比）
assert "comparison" not in allowed_fields(
    {**two, "retrieved": []}, has_market=True)

# 12c: 多標的 + news shape -> 不含
assert "comparison" not in allowed_fields(
    {**two, "answer_shape": "news"}, has_market=True)

# 12d: 單一公司 + full + 有 retrieved -> 不含
assert "comparison" not in allowed_fields(
    {**two, "companies": ["2330"]}, has_market=True)

# 12e: 回退路徑也要濾家數——開關 off 時單一公司題不得出現無對象的比較表
config.ANSWER_SHAPE_GATING = False
try:
    assert "comparison" not in allowed_fields({**two, "companies": ["2330"]}, has_market=True)
    assert "comparison" in allowed_fields(two, has_market=True)
finally:
    config.ANSWER_SHAPE_GATING = True

print("allowed_fields self-check OK")
