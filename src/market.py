"""即時行情快照（yfinance），只進 prompt 不入庫。"""
from __future__ import annotations

import sys


def format_snapshot(info: dict) -> str:
    lines = []
    price = info.get("currentPrice")
    prev = info.get("previousClose")
    if price is not None:
        lines.append(f"currentPrice: {price}")
    if prev is not None:
        lines.append(f"previousClose: {prev}")
    if price is not None and prev is not None:
        change = (price - prev) / prev * 100
        lines.append(f"change vs prev close: {change:+.2f}%")

    low = info.get("fiftyTwoWeekLow")
    high = info.get("fiftyTwoWeekHigh")
    if low is not None and high is not None:
        lines.append(f"52w range: {low} - {high}")

    for key in ("marketCap", "trailingPE", "forwardPE", "targetMeanPrice", "recommendationKey"):
        val = info.get(key)
        if val is not None:
            lines.append(f"{key}: {val}")

    return "\n".join(lines)


def get_market_snapshot(company: str) -> str | None:
    symbol = f"{company}.TW" if company.isdigit() and len(company) == 4 else company.upper()
    try:
        import yfinance  # 延遲 import，缺套件時 module import 不受影響

        # ponytail: 每問抓一次不快取，單人本地 app 夠用
        info = yfinance.Ticker(symbol).get_info()
        text = format_snapshot(info)
        return text or None
    except Exception as e:  # noqa: BLE001
        print(f"[market] 行情取得失敗：{e}")
        return None


if __name__ == "__main__":
    print(get_market_snapshot(sys.argv[1]))
