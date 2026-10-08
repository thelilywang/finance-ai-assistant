"""即時行情快照（yfinance），只進 prompt 不入庫。"""
from __future__ import annotations

import calendar
import logging
import sys
import time
from datetime import date, datetime, timezone

from . import config
from .logging_setup import log_duration
from .tickers import ADR_RATIO, is_tw_ticker

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


def _yi(v) -> str:
    """換成「億」(1e8)、一位小數＋千分位；13 位數原樣給模型會被讀小 10 倍。"""
    return "n/a" if v is None else f"{v / 1e8:,.1f} 億"


def format_consensus(ticker, info: dict | None = None) -> str:
    """組分析師共識區塊（下次財報日、當季共識、近 4 季 beat/miss），各段獨立容錯。

    幣別：EPS 用 info["currency"]（ADR 為 USD），營收用 financialCurrency（TSM 為 TWD）；
    查不到就不標，不猜。
    """
    info = info or {}
    eps_cur = info.get("currency")
    rev_cur = info.get("financialCurrency") or eps_cur
    lines = []

    try:  # 下次財報日 + 當季 EPS/營收共識（calendar 是 dict）
        cal = ticker.calendar or {}
        dates = cal.get("Earnings Date")
        if dates:
            lines.append(f"next earnings date: {dates[0]}")
        eps = tuple(cal.get(f"Earnings {k}") for k in ("Average", "Low", "High"))
        if eps[0] is not None:
            tag = f" ({eps_cur} per share)" if eps_cur else ""
            lines.append(f"next-quarter EPS estimate, not yet reported{tag} (avg/low/high): "
                         f"{eps[0]} / {eps[1]} / {eps[2]}")
        rev = tuple(cal.get(f"Revenue {k}") for k in ("Average", "Low", "High"))
        if rev[0] is not None:
            tag = f" ({rev_cur}, in 億 = 1e8)" if rev_cur else " (in 億 = 1e8)"
            lines.append(f"next-quarter revenue estimate, not yet reported{tag} (avg/low/high): "
                         f"{_yi(rev[0])} / {_yi(rev[1])} / {_yi(rev[2])}")
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
        cur_tag = f" ({eps_cur})" if eps_cur else ""
        for idx, row in df.iterrows():
            lines.append(
                f"past quarter reported {idx.date()}{cur_tag}: est {row['EPS Estimate']} / "
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
        info = ticker.get_info()
        text = format_snapshot(info)
        consensus = format_consensus(ticker, info)
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


def _fmt_time(info: dict) -> str:
    """把 regularMarketTime（epoch 秒）轉成 UTC 可讀字串；缺欄位回空字串。"""
    ts = info.get("regularMarketTime")
    if ts is None:
        return ""
    return f" (as of {datetime.fromtimestamp(ts, timezone.utc):%Y-%m-%d %H:%M} UTC)"


def _latest_reported_eps(ticker) -> tuple[date, float] | None:
    """取 earnings_dates 中最新一筆有 Reported EPS 的（公布日, EPS）；失敗回 None。

    format_consensus 要的是近 4 季，這裡只要最新一筆，故另抽一個小函式，
    不共用 format_consensus 的迴圈。
    """
    try:
        df = ticker.earnings_dates
        df = df[df["Reported EPS"].notna()]
        if df.empty:
            return None
        row = df.iloc[0]
        return row.name.date(), float(row["Reported EPS"])
    except Exception as e:  # noqa: BLE001
        log.warning("latest reported EPS 取得失敗", extra={"fields": {
            "symbol": getattr(ticker, "ticker", None), "field": "earnings_dates",
            "reason": "market_failed", "error": str(e)}})
        return None


def _quarter_of(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3


def _covered_quarter(d: date) -> tuple[int, int, date]:
    """公布日所涵蓋的財報季 (年, 第幾季 1-4, 季末日)，即公布日之前的那個曆法季。

    模型常把「reported 7 月」讀成 Q3，實為 Q2 結果，故明寫季別與季末日。
    # ponytail: 假設曆法會計年度且在次季內公布；ADR_RATIO 雙掛牌（TSM/UMC/CHT/ASX/IMOS）成立，
    # 非曆年制公司需自己的財報月曆。
    """
    y, q0 = _quarter_of(d)
    y, q = (y - 1, 4) if q0 == 0 else (y, q0)
    return y, q, date(y, q * 3, calendar.monthrange(y, q * 3)[1])


def _rep(d: date) -> str:
    y, q, end = _covered_quarter(d)
    return f"Q{q} {y} results (quarter ended {end}), reported {d}"


def format_adr_premium(tw: str, us: str, tw_info: dict, us_info: dict,
                        fx_info: dict, ratio: int,
                        tw_eps: tuple[date, float] | None = None,
                        us_eps: tuple[date, float] | None = None,
                        ) -> tuple[str | None, dict]:
    """純函式，算 ADR 溢價率；任一價格缺就回 (None, {})（缺資料不硬湊）。

    回傳 (text, metrics)：metrics 供呼叫端記 log／測試斷言，不必從文字裡拆數字。
    tw_eps/us_eps 兩邊都有值且公布日落在同一曆法季度（年、季相同；台美公布日常差好幾天
    但屬同一財報季）才附 EPS 等值換算並與台股比較；不同季則分開陳述已公布 EPS 與各自公布日
    並標明不可比較，另附 ADR 換算行（不含「vs」比較，也不進 metrics），標籤含糊會讓模型硬湊換算。
    """
    tw_price = tw_info.get("currentPrice") or tw_info.get("regularMarketPrice")
    us_price = us_info.get("currentPrice") or us_info.get("regularMarketPrice")
    fx = fx_info.get("currentPrice") or fx_info.get("regularMarketPrice")
    if tw_price is None or us_price is None or fx is None:
        return None, {}

    per_share_twd = us_price * fx / ratio
    premium_pct = round((per_share_twd / tw_price - 1) * 100, 2)

    lines = [
        f"ADR ratio: 1 {us} = {ratio} shares of {tw} "
        f"(ADR figure → per {tw} share: ÷ {ratio}, then × USD/TWD)",
        f"USD/TWD: {fx}{_fmt_time(fx_info)}",
        f"{us} price: {us_price} USD{_fmt_time(us_info)}",
        f"{tw} price: {tw_price} TWD{_fmt_time(tw_info)}",
        # 價格行不得出現「TWD (vs」，bench 的 _EPS_BLOCK_RE 靠它只命中 EPS 換算行
        f"{us} price per {tw} share: {us_price} / {ratio} × {fx} = {per_share_twd:.2f} TWD "
        "(share price, not EPS)",
        f"ADR premium vs {tw}: {premium_pct:+.2f}%",
    ]
    metrics = {"premium_pct": premium_pct}

    if tw_eps is not None and us_eps is not None:
        tw_date, tw_eps_val = tw_eps
        us_date, us_eps_val = us_eps
        if _quarter_of(tw_date) == _quarter_of(us_date):
            eps_equiv = us_eps_val / ratio * fx
            eps_equiv_diff_pct = round((eps_equiv / tw_eps_val - 1) * 100, 2)
            lines += [
                f"latest reported single-quarter EPS ({_rep(us_date)}): {tw} {tw_eps_val} TWD / "
                f"{us} {us_eps_val} USD",
                f"{us} EPS per {tw} share: {us_eps_val} / {ratio} × {fx} = {eps_equiv:.2f} TWD "
                f"(vs {tw} {tw_eps_val} TWD, {eps_equiv_diff_pct:+.2f}%)",
            ]
            metrics["eps_equiv_diff_pct"] = eps_equiv_diff_pct
        else:
            lines.append(
                f"latest reported single-quarter EPS (different quarters, do not compare): "
                f"{tw} {tw_eps_val} TWD ({_rep(tw_date)}) / {us} {us_eps_val} USD ({_rep(us_date)})"
            )
            # 換算行刻意不帶「TWD (vs」，bench 的 _EPS_BLOCK_RE 只能命中同季那行
            eps_equiv = us_eps_val / ratio * fx
            lines.append(
                f"{us} EPS per {tw} share: {us_eps_val} / {ratio} × {fx} = {eps_equiv:.2f} TWD "
                f"({us} {_rep(us_date)}; different quarter from {tw}, do not compare)"
            )
    elif tw_eps is not None or us_eps is not None:
        side, cur = (tw, "TWD") if tw_eps is not None else (us, "USD")
        other = us if tw_eps is not None else tw
        d, v = tw_eps or us_eps
        lines.append(
            f"latest reported single-quarter EPS (only {side} available, {other} has no data, do not compare): "
            f"{side} {v} {cur} ({_rep(d)})"
        )

    return "\n".join(lines), metrics


def get_adr_premium(tw: str, us: str) -> str | None:
    """抓台股/ADR/匯率三筆行情並算溢價率；查無換算比例或任一段失敗回 None。

    ADR_PREMIUM=="eps" 時順便抓兩邊最新一筆 Reported EPS，交給 format_adr_premium
    附上 EPS 等值換算；仍是同一輪 thread pool 並行，不多等一輪。
    """
    ratio = ADR_RATIO.get(us)
    if ratio is None:
        return None

    started = time.monotonic()
    try:
        import yfinance
        from concurrent.futures import ThreadPoolExecutor

        want_eps = config.ADR_PREMIUM == "eps"

        def _fetch(symbol: str, want_eps_for_symbol: bool) -> tuple[dict, tuple[date, float] | None]:
            t = yfinance.Ticker(symbol)
            eps = _latest_reported_eps(t) if want_eps_for_symbol else None
            return t.get_info(), eps

        symbols = (to_symbol(tw), us, "TWD=X")
        eps_wanted = (want_eps, want_eps, False)  # TWD=X 沒有 EPS 這種概念
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="adr") as executor:
            (tw_info, tw_eps), (us_info, us_eps), (fx_info, _) = executor.map(
                _fetch, symbols, eps_wanted)

        text, metrics = format_adr_premium(tw, us, tw_info, us_info, fx_info, ratio,
                                            tw_eps=tw_eps, us_eps=us_eps)
        if text is None:
            return None
        fx = fx_info.get("currentPrice") or fx_info.get("regularMarketPrice")
        log_duration(log, "adr_premium", started, node="market",
                     tw=tw, us=us, ratio=ratio, fx=fx, **metrics)
        return text
    except Exception as e:  # noqa: BLE001
        log.warning("ADR 溢價取得失敗", extra={"fields": {
            "tw": tw, "us": us, "reason": "market_failed", "error": str(e)}})
        return None


if __name__ == "__main__":
    print(get_market_snapshot(sys.argv[1]))
