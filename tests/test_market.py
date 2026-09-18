"""最小 self-check：format_snapshot 純函式，不碰網路。
執行：python tests/test_market.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.market import format_snapshot

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

partial = format_snapshot({"currentPrice": 211.16})
assert "currentPrice" in partial
assert "52w" not in partial
assert "change" not in partial

assert format_snapshot({}) == ""

# 已知漲跌幅計算
known = format_snapshot({"currentPrice": 110, "previousClose": 100})
assert "+10.00%" in known

# 公司名：info 有 longName 才輸出 name: 行
named = format_snapshot({"currentPrice": 100, "longName": "Taiwan Semiconductor Manufacturing"})
assert named.startswith("name: Taiwan Semiconductor Manufacturing")
assert "name: " not in format_snapshot({"currentPrice": 100})
# longName 缺席時退回 shortName
assert format_snapshot({"shortName": "TSMC"}) == "name: TSMC"

# 幣別：有 currency 才輸出，且要在價格之前（模型讀到數字時單位已知）
cur = format_snapshot({"currency": "USD", "currentPrice": 182.4})
assert cur.index("currency: USD") < cur.index("currentPrice: 182.4")
assert "currency: " not in format_snapshot({"currentPrice": 100})

print("market self-check OK")
