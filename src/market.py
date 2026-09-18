"""即時行情快照（yfinance），只進 prompt 不入庫。"""
from __future__ import annotations

import logging
import sys

from .tickers import is_tw_ticker

log = logging.getLogger("market")


def format_snapshot(info: dict) -> str:
    lines = []
    name = info.get("longName") or info.get("shortName")
    if name is not None:
        lines.append(f"name: {name}")
    # 幣別要隨數字進 prompt：多標的跨市場時模型無從由代號推斷，只能猜
    currency = info.get("currency")
    if currency is not None:
        lines.append(f"currency: {currency}")
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


def format_consensus(ticker) -> str:
    """組分析師共識區塊（下次財報日、當季共識、近 4 季 beat/miss），各段獨立容錯。"""
    lines = []

    try:  # 下次財報日 + 當季 EPS/營收共識（calendar 是 dict）
        cal = ticker.calendar or {}
        dates = cal.get("Earnings Date")
        if dates:
            lines.append(f"next earnings date: {dates[0]}")
        for label, key in (
            ("EPS consensus (avg/low/high)", "Earnings"),
            ("Revenue consensus (avg/low/high)", "Revenue"),
        ):
            avg, low, high = (cal.get(f"{key} Average"), cal.get(f"{key} Low"), cal.get(f"{key} High"))
            if avg is not None:
                lines.append(f"{label}: {avg} / {low} / {high}")
    except Exception as e:  # noqa: BLE001
        log.warning("calendar 取得失敗", extra={"fields": {
            "symbol": getattr(ticker, "ticker", None), "field": "calendar",
            "reason": "market_failed", "error": str(e)}})

    try:  # 當季分析師人數
        n = ticker.earnings_estimate.loc["0q"]["numberOfAnalysts"]
        lines.append(f"numberOfAnalysts (current quarter): {int(n)}")
    except Exception as e:  # noqa: BLE001
        log.warning("earnings_estimate 取得失敗", extra={"fields": {
            "symbol": getattr(ticker, "ticker", None), "field": "earnings_estimate",
            "reason": "market_failed", "error": str(e)}})

    try:  # 近 4 季 EPS 預估 vs 實際 vs surprise
        df = ticker.earnings_dates
        df = df[df["Reported EPS"].notna()].head(4)
        for idx, row in df.iterrows():
            lines.append(
                f"past quarter {idx.date()}: est {row['EPS Estimate']} / "
                f"actual {row['Reported EPS']} / surprise {row['Surprise(%)']:+.2f}%"
            )
    except Exception as e:  # noqa: BLE001
        log.warning("earnings_dates 取得失敗", extra={"fields": {
            "symbol": getattr(ticker, "ticker", None), "field": "earnings_dates",
            "reason": "market_failed", "error": str(e)}})

    if not lines:
        return ""
    return "--- analyst consensus (Yahoo Finance) ---\n" + "\n".join(lines)


def to_symbol(company: str) -> str:
    """台股代號加 .TW，其他視為美股 ticker。"""
    return f"{company}.TW" if is_tw_ticker(company) else company.upper()


def get_market_snapshot(company: str) -> str | None:
    try:
        import yfinance  # 延遲 import，缺套件時 module import 不受影響

        # ponytail: 每問抓一次不快取，單人本地 app 夠用
        ticker = yfinance.Ticker(to_symbol(company))
        text = format_snapshot(ticker.get_info())
        consensus = format_consensus(ticker)
        if consensus:
            text = f"{text}\n{consensus}" if text else consensus
        return text or None
    except Exception as e:  # noqa: BLE001
        log.warning("行情取得失敗", extra={"fields": {
            "company": company, "reason": "market_failed", "error": str(e)}})
        return None


def get_market_snapshots(companies: list[str]) -> dict[str, str]:
    """多標的並行取行情，只回成功的家數（失敗的 key 不存在）。

    形狀對齊 graph.py 的 _retrieve_parallel：抓 N 家的總耗時約等於最慢一家。
    公司名隨快照文字帶出（format_snapshot 的 name: 欄），不需第二趟網路呼叫。
    """
    if not companies:
        return {}

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(len(companies), 3),
                            thread_name_prefix="market") as executor:
        texts = executor.map(get_market_snapshot, companies)
        return {c: text for c, text in zip(companies, texts) if text}


if __name__ == "__main__":
    print(get_market_snapshot(sys.argv[1]))
