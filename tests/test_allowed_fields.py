"""allowed_fields 的 answer_shape × evidence 判準矩陣。"""
from src import config
from src.graph import allowed_fields

FULL_ONLY = {"valuation", "consensus", "scenario", "earnings_call", "recommendation"}
UNCONDITIONAL = {"conclusion", "facts", "inference", "upside", "risk"}

NEWS_DATED = [{"id": 1, "doc_type": "news", "published_at": "2026-09-01"}]
NEWS_UNDATED = [{"id": 1, "doc_type": "news"}]
FINANCIAL = [{"id": 2, "doc_type": "financial_report"}]
FINANCIAL_AND_NEWS = FINANCIAL + NEWS_DATED


def test_news_shape_with_dated_news():
    # 1: news + 新聞含日期 + no market -> 8 個無條件/optional 欄，無 5 個 full-only 欄
    fields = set(allowed_fields({"answer_shape": "news", "retrieved": NEWS_DATED}, has_market=False))
    assert fields == UNCONDITIONAL | {"trigger", "next_event", "tracking_indicators"}, fields
    assert not (fields & FULL_ONLY)


def test_news_shape_without_date():
    # 2: news + 新聞無日期 -> 無 next_event，其餘同 #1
    fields = set(allowed_fields({"answer_shape": "news", "retrieved": NEWS_UNDATED}, has_market=False))
    assert fields == UNCONDITIONAL | {"trigger", "tracking_indicators"}, fields
    assert "next_event" not in fields


def test_news_shape_empty_retrieved():
    # 3: news + 空 retrieved -> 僅 5 個無條件欄
    fields = set(allowed_fields({"answer_shape": "news", "retrieved": []}, has_market=False))
    assert fields == UNCONDITIONAL, fields


def test_full_shape_financial_and_news_with_market():
    # 4: full + 財報+新聞 + has_market=True -> 全欄含 recommendation
    fields = set(allowed_fields({"answer_shape": "full", "retrieved": FINANCIAL_AND_NEWS}, has_market=True))
    assert fields == UNCONDITIONAL | FULL_ONLY | {"trigger", "next_event", "tracking_indicators"}, fields
    assert "recommendation" in fields


def test_full_shape_news_only_missing_earnings_call():
    # 5: full + 僅新聞 + has_market=True -> 無 earnings_call、無 recommendation（三要件不齊）
    fields = set(allowed_fields({"answer_shape": "full", "retrieved": NEWS_DATED}, has_market=True))
    assert "earnings_call" not in fields
    assert "recommendation" not in fields
    assert {"valuation", "consensus", "scenario"} <= fields


def test_full_shape_no_market_excludes_market_fields():
    # 6: full + 財報+新聞 + has_market=False -> 無 valuation/consensus/scenario/recommendation
    fields = set(allowed_fields({"answer_shape": "full", "retrieved": FINANCIAL_AND_NEWS}, has_market=False))
    assert not ({"valuation", "consensus", "scenario", "recommendation"} & fields), fields


def test_full_shape_market_none_is_candidate():
    # 7: full + 財報+新聞 + has_market=None（第一段）-> valuation/consensus/scenario 在候選集內
    fields = set(allowed_fields({"answer_shape": "full", "retrieved": FINANCIAL_AND_NEWS}, has_market=None))
    assert {"valuation", "consensus", "scenario"} <= fields, fields


def test_missing_answer_shape_defaults_to_full():
    # 8: 缺 answer_shape（None）-> 等同 full（驗證 state.get("answer_shape") or "full"）
    fields = set(allowed_fields({"retrieved": FINANCIAL_AND_NEWS}, has_market=True))
    assert fields == UNCONDITIONAL | FULL_ONLY | {"trigger", "next_event", "tracking_indicators"}, fields


def test_gating_off_returns_all_fields(monkeypatch):
    # 9: 開關 off -> 回傳現行全欄，與 answer_shape/evidence 無關（單一公司題仍不含 comparison）
    monkeypatch.setattr(config, "ANSWER_SHAPE_GATING", False)
    fields = set(allowed_fields({"answer_shape": "news", "retrieved": []}, has_market=False))
    assert fields == UNCONDITIONAL | FULL_ONLY | {"trigger", "next_event", "tracking_indicators"}, fields


def test_unconditional_fields_always_subset():
    # 10: 所有組合下，5 個無條件欄恆為子集（不整段棄權迴歸防線）
    combos = [
        {"answer_shape": s, "retrieved": r}
        for s in ("news", "full", None)
        for r in ([], NEWS_DATED, NEWS_UNDATED, FINANCIAL, FINANCIAL_AND_NEWS)
    ]
    for hm in (None, True, False):
        for state in combos:
            fields = set(allowed_fields(state, has_market=hm))
            assert UNCONDITIONAL <= fields, (state, hm, fields)


def test_impact_field_never_present():
    # 11: 任何組合下回傳值中永不出現 "impact"
    combos = [
        {"answer_shape": s, "retrieved": r}
        for s in ("news", "full", None)
        for r in ([], NEWS_DATED, NEWS_UNDATED, FINANCIAL, FINANCIAL_AND_NEWS)
    ]
    for hm in (None, True, False):
        for state in combos:
            assert "impact" not in allowed_fields(state, has_market=hm)


def test_comparison_field_gating():
    # 12: comparison 閘門（多標的專屬欄）
    two = {"companies": ["2330", "2454"], "answer_shape": "full", "retrieved": FINANCIAL_AND_NEWS}
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


def test_comparison_field_gating_fallback_path(monkeypatch):
    # 12e: 回退路徑也要濾家數——開關 off 時單一公司題不得出現無對象的比較表
    two = {"companies": ["2330", "2454"], "answer_shape": "full", "retrieved": FINANCIAL_AND_NEWS}
    monkeypatch.setattr(config, "ANSWER_SHAPE_GATING", False)
    assert "comparison" not in allowed_fields({**two, "companies": ["2330"]}, has_market=True)
    assert "comparison" in allowed_fields(two, has_market=True)
