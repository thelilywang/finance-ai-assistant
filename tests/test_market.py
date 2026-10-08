"""format_snapshot / format_adr_premium 純函式，不碰網路。"""
from datetime import date

from src.market import _covered_quarter, format_adr_premium, format_consensus, format_snapshot


def test_format_snapshot_full():
    full = {
        "currentPrice": 211.16,
        "previousClose": 208.55,
        "fiftyTwoWeekLow": 168.99,
        "fiftyTwoWeekHigh": 260.10,
        "marketCap": 3123456789012,
        "trailingPE": 32.5,
        "forwardPE": 28.9,
        "targetMeanPrice": 235.2,
        "recommendationKey": "buy",
    }
    result = format_snapshot(full)
    assert "currentPrice" in result
    assert "52w range: 168.99 - 260.1" in result
    assert "+" in result or "-" in result


def test_format_snapshot_partial_and_empty():
    partial = format_snapshot({"currentPrice": 211.16})
    assert "currentPrice" in partial
    assert "52w" not in partial
    assert "change" not in partial

    assert format_snapshot({}) == ""


def test_format_snapshot_change_percent():
    # 已知漲跌幅計算
    known = format_snapshot({"currentPrice": 110, "previousClose": 100})
    assert "+10.00%" in known


def test_format_snapshot_company_name():
    # 公司名：info 有 longName 才輸出 name: 行
    named = format_snapshot({"currentPrice": 100, "longName": "Taiwan Semiconductor Manufacturing"})
    assert named.startswith("name: Taiwan Semiconductor Manufacturing")
    assert "name: " not in format_snapshot({"currentPrice": 100})
    # longName 缺席時退回 shortName
    assert format_snapshot({"shortName": "TSMC"}) == "name: TSMC"


def test_format_snapshot_currency():
    # 幣別：有 currency 才輸出，且要在價格之前（模型讀到數字時單位已知）
    cur = format_snapshot({"currency": "USD", "currentPrice": 182.4})
    assert cur.index("currency: USD") < cur.index("currentPrice: 182.4")
    assert "currency: " not in format_snapshot({"currentPrice": 100})


# --- format_adr_premium：計畫附的容器內實測值（2026-09-24），TSM/2330/USD-TWD ---
_TW_INFO = {"currentPrice": 2480.0}
_US_INFO = {"currentPrice": 446.57}
_FX_INFO = {"regularMarketPrice": 31.802}  # TWD=X 只有 regularMarketPrice，沒有 currentPrice

# --- EPS 等值：計畫附的容器內實測值（10-07），同一天公布同一季 ---
_TW_EPS = (date(2026, 7, 16), 27.25)
_US_EPS = (date(2026, 7, 16), 4.31)


def test_format_adr_premium_known_values():
    # 446.57 * 31.802 / 5 = 2840.36；2840.36 / 2480.0 - 1 = +14.53%
    text, metrics = format_adr_premium("2330", "TSM", _TW_INFO, _US_INFO, _FX_INFO, ratio=5)
    assert text is not None
    assert "TSM price per 2330 share: 446.57 / 5 × 31.802 = 2840.36 TWD (share price, not EPS)" in text
    assert "TWD (vs" not in text  # 價格行不能被 bench 的 EPS 換算 regex 命中
    assert "ADR figure → per 2330 share: ÷ 5, then × USD/TWD" in text
    assert "+14.53%" in text
    assert "1 TSM = 5 shares of 2330" in text
    assert metrics == {"premium_pct": 14.53}


def test_format_adr_premium_fx_regular_market_price_only():
    # TWD=X 只有 regularMarketPrice（currentPrice 為 None）也要能算，不能因此回 None
    text, _ = format_adr_premium("2330", "TSM", _TW_INFO, _US_INFO,
                                  {"currentPrice": None, "regularMarketPrice": 31.802}, ratio=5)
    assert text is not None
    assert "31.802" in text


def test_format_adr_premium_missing_price_returns_none():
    assert format_adr_premium("2330", "TSM", {}, _US_INFO, _FX_INFO, ratio=5) == (None, {})
    assert format_adr_premium("2330", "TSM", _TW_INFO, {}, _FX_INFO, ratio=5) == (None, {})
    assert format_adr_premium("2330", "TSM", _TW_INFO, _US_INFO, {}, ratio=5) == (None, {})


def test_format_adr_premium_eps_equiv_same_quarter():
    # 4.31 / 5 * 31.802 = 27.41；27.41 / 27.25 - 1 = +0.60%
    text, metrics = format_adr_premium("2330", "TSM", _TW_INFO, _US_INFO, _FX_INFO, ratio=5,
                                        tw_eps=_TW_EPS, us_eps=_US_EPS)
    assert text is not None
    assert "27.25 TWD" in text and "4.31 USD" in text
    assert "27.41 TWD" in text
    assert metrics["eps_equiv_diff_pct"] == 0.6


def test_format_adr_premium_eps_different_quarter_separate_line():
    # 公布日落在不同曆法季度：分開陳述 + 無 vs 的換算行，不比較
    us_eps_other_quarter = (date(2026, 10, 2), 4.31)
    text, metrics = format_adr_premium("2330", "TSM", _TW_INFO, _US_INFO, _FX_INFO, ratio=5,
                                        tw_eps=_TW_EPS, us_eps=us_eps_other_quarter)
    assert text is not None
    assert ("latest reported single-quarter EPS (different quarters, do not compare): "
            "2330 27.25 TWD (Q2 2026 results (quarter ended 2026-06-30), reported 2026-07-16) / "
            "TSM 4.31 USD (Q3 2026 results (quarter ended 2026-09-30), reported 2026-10-02)") in text
    assert ("TSM EPS per 2330 share: 4.31 / 5 × ") in text
    assert "TSM Q3 2026 results (quarter ended 2026-09-30), reported 2026-10-02; different quarter from 2330, do not compare)" in text
    assert "TWD (vs" not in text
    assert "eps_equiv_diff_pct" not in metrics


def test_format_adr_premium_eps_same_calendar_quarter_5_days_apart():
    # 台 7/16、美 7/21 同屬 Q3：視為同季，附 vs 比較
    text, metrics = format_adr_premium("2330", "TSM", _TW_INFO, _US_INFO, _FX_INFO, ratio=5,
                                        tw_eps=_TW_EPS, us_eps=(date(2026, 7, 21), 4.31))
    assert "TWD (vs" in text and "different quarters" not in text
    assert "eps_equiv_diff_pct" in metrics


def test_format_adr_premium_eps_missing_one_side_separate_line():
    text, metrics = format_adr_premium("2330", "TSM", _TW_INFO, _US_INFO, _FX_INFO, ratio=5,
                                        tw_eps=_TW_EPS, us_eps=None)
    assert text is not None
    assert "2330 27.25 TWD (Q2 2026 results (quarter ended 2026-06-30), reported 2026-07-16)" in text
    assert "TSM has no data" in text and "do not compare" in text
    assert "TWD (vs" not in text
    assert "eps_equiv_diff_pct" not in metrics

    text, _ = format_adr_premium("2330", "TSM", _TW_INFO, _US_INFO, _FX_INFO, ratio=5,
                                  tw_eps=None, us_eps=_US_EPS)
    assert "TSM 4.31 USD (Q2 2026 results" in text and "2330 has no data" in text

    text, _ = format_adr_premium("2330", "TSM", _TW_INFO, _US_INFO, _FX_INFO, ratio=5)
    assert "latest reported single-quarter EPS" not in text  # 兩邊都沒有就不輸出


class _FakeTicker:
    """只給 calendar；earnings_estimate / earnings_dates 存取即 raise，由 format_consensus 容錯。"""
    ticker = "FAKE"
    calendar = {"Earnings Average": 1.5, "Earnings Low": 1.2, "Earnings High": 1.8, "Revenue Average": 100}

    @property
    def earnings_estimate(self):
        raise RuntimeError("no data")

    @property
    def earnings_dates(self):
        raise RuntimeError("no data")


def test_format_consensus_labels_next_quarter_estimate():
    # 標籤要讓模型看得出是下一季預估而非已公布 EPS
    text = format_consensus(_FakeTicker())
    assert "next-quarter EPS estimate, not yet reported (avg/low/high): 1.5 / 1.2 / 1.8" in text
    assert "next-quarter revenue estimate, not yet reported (in 億 = 1e8)" in text
    assert "EPS consensus" not in text


def test_format_consensus_currency_and_yi_conversion():
    # 13 位數營收要轉成億並標幣別；EPS 用 info["currency"]，營收用 financialCurrency
    t = _FakeTicker()
    t.calendar = {"Earnings Average": 1.5, "Earnings Low": 1.2, "Earnings High": 1.8,
                  "Revenue Average": 1455552055340, "Revenue Low": 1423000000000,
                  "Revenue High": 1482697859000}
    text = format_consensus(t, {"currency": "USD", "financialCurrency": "TWD"})
    rev = next(x for x in text.splitlines() if "revenue" in x)
    eps = next(x for x in text.splitlines() if "EPS" in x)
    assert "14,555.5 億" in rev and "TWD" in rev and "USD" not in rev
    assert "USD per share" in eps


def test_format_consensus_no_info_omits_currency_and_tolerates_none():
    t = _FakeTicker()  # Revenue Low/High 缺 -> n/a
    text = format_consensus(t)
    assert "n/a / n/a" in text
    assert "USD" not in text and "TWD" not in text and "per share" not in text


def test_covered_quarter_is_quarter_before_report_date():
    # 7 月公布是 Q2 結果；1 月公布跨年是上一年 Q4
    assert _covered_quarter(date(2026, 7, 16)) == (2026, 2, date(2026, 6, 30))
    assert _covered_quarter(date(2027, 1, 15)) == (2026, 4, date(2026, 12, 31))
    text, _ = format_adr_premium("2330", "TSM", _TW_INFO, _US_INFO, _FX_INFO, ratio=5,
                                  tw_eps=(date(2027, 1, 15), 1.0), us_eps=(date(2027, 1, 16), 1.0))
    assert "Q4 2026 results (quarter ended 2026-12-31), reported 2027-01-16" in text
    assert "TWD (vs" in text
