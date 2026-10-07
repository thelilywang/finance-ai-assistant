"""format_snapshot / format_adr_premium 純函式，不碰網路。"""
from src.market import format_adr_premium, format_snapshot


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


def test_format_adr_premium_known_values():
    # 446.57 * 31.802 / 5 = 2840.36；2840.36 / 2480.0 - 1 = +14.53%
    result = format_adr_premium("2330", "TSM", _TW_INFO, _US_INFO, _FX_INFO, ratio=5)
    assert result is not None
    assert "2840.36 TWD" in result
    assert "+14.53%" in result
    assert "1 TSM = 5 shares of 2330" in result


def test_format_adr_premium_fx_regular_market_price_only():
    # TWD=X 只有 regularMarketPrice（currentPrice 為 None）也要能算，不能因此回 None
    result = format_adr_premium("2330", "TSM", _TW_INFO, _US_INFO,
                                 {"currentPrice": None, "regularMarketPrice": 31.802}, ratio=5)
    assert result is not None
    assert "31.802" in result


def test_format_adr_premium_missing_price_returns_none():
    assert format_adr_premium("2330", "TSM", {}, _US_INFO, _FX_INFO, ratio=5) is None
    assert format_adr_premium("2330", "TSM", _TW_INFO, {}, _FX_INFO, ratio=5) is None
    assert format_adr_premium("2330", "TSM", _TW_INFO, _US_INFO, {}, ratio=5) is None
