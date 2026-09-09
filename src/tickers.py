"""台股/美股代號格式判斷與正規化。"""
from __future__ import annotations

import re

# 台股：一般股票/ETF 4-6 碼純數字，可選 1 碼英文字母尾碼（新制ETF策略/特別股/可轉債/換股權利證書）
_TW_RE = re.compile(r"^\d{4,6}[A-Z]?$")
# 美股：主體代號 1-5 碼大寫字母（不含 .PR.A 等後綴，後綴由 normalize_ticker 去除）
_US_RE = re.compile(r"^[A-Z]{1,5}$")


def normalize_ticker(raw: str) -> str | None:
    """去除交易所/股別後綴（.TW、.TWO、.PR.A、.W...），只留主體代號；不符合已知格式回 None。"""
    v = raw.strip().upper().split(".")[0]
    if _TW_RE.fullmatch(v) or _US_RE.fullmatch(v):
        return v
    return None


def is_tw_ticker(company: str) -> bool:
    """是否為台股代號格式（4-6碼數字，可選1碼英文字母尾碼）；False 則視為美股。"""
    return bool(_TW_RE.fullmatch(company))


# 同一家公司在台美兩市場都有掛牌（台股本股 ↔ 美股 ADR）。問「台積電 EPS」時
# 兩邊都答得出來卻是不同答案：幣別不同（台幣 vs 美元）、期間不同（台股按季、
# ADR 依 20-F/6-K）、每股基準不同（1 ADR = 5 股台積電普通股），直接比較會錯得離譜。
# 故遇到這些標的且使用者沒指明市場時，要先問清楚再查。
#
# 只收「美股那側查得到財報」的標的：本專案的美股資料全部來自 SEC（EDGAR 全文與
# XBRL 數字），而 OTC 的 Level 1 與非贊助 ADR 不須向 SEC 申報。實測 company_tickers.json
# 與公司名稱雙向查詢，富邦金(FUISY)、國泰金(CHYYY)、鴻海(HNHPF)、中信金(CTBKY)、
# 兆豐金(MEGAF)、友達(AUOTY) 六檔在 SEC 完全沒有申報實體（連 CIK 都沒有），
# 收進來只會讓使用者選了「美股」之後拿到查無資料，比不提供這個選項更糟。
# ponytail: 靜態表。台股 ADR 數量少且極少變動，查詢用的 API 沒有這個對應欄位，
# 靠公司名稱模糊比對反而不穩；改為 API 查詢 + 落地快取已列入維護日誌待辦。
TW_US_DUAL_LISTED = {
    "2330": "TSM",    # 台積電（NYSE）
    "2303": "UMC",    # 聯電（NYSE）
    "2412": "CHT",    # 中華電信（NYSE）
    "3711": "ASX",    # 日月光投控（NYSE）
    "8150": "IMOS",   # 南茂科技（NASDAQ）
}
_US_TO_TW = {us: tw for tw, us in TW_US_DUAL_LISTED.items()}

# 反問時要讓使用者認得是哪家公司，光給代號不夠親切
DUAL_LISTED_NAMES = {
    "2330": "台積電",
    "2303": "聯電",
    "2412": "中華電信",
    "3711": "日月光投控",
    "8150": "南茂科技",
}

# 有 ADR 但美股那側查不到財報：OTC 的 Level 1／非贊助 ADR 不向 SEC 申報，成交量也極低。
# 不放進 TW_US_DUAL_LISTED（避免反問後選美股拿到空手），但仍記錄下來，讓查台股時能
# 附帶告知「美股有掛牌、只是我們取不到財報」，而不是假裝沒這回事。
# 富智康（港股 2038 ↔ FXCNY）刻意不收：它不是台股，鍵位一律當台股代號用會被誤判成
# 台股去查證交所 API 而查無資料；台灣投資人也習慣直接看母公司鴻海。
TW_US_OTC_ONLY = {
    "2881": "FUISY",  # 富邦金控（另有 FUISF）
    "2882": "CHYYY",  # 國泰金控
    "2317": "HNHPF",  # 鴻海精密
    "2891": "CTBKY",  # 中信金控
    "2886": "MEGAF",  # 兆豐金控
    "2409": "AUOTY",  # 友達光電（原 NYSE 主板，已下市轉 OTC）
}
OTC_ONLY_NAMES = {
    "2881": "富邦金控",
    "2882": "國泰金控",
    "2317": "鴻海精密",
    "2891": "中信金控",
    "2886": "兆豐金控",
    "2409": "友達光電",
}


def dual_listed_peer(company: str) -> str | None:
    """回傳同一家公司在另一個市場的代號；非雙掛牌標的回 None。

    只涵蓋美股那側查得到財報的標的（見上方 TW_US_DUAL_LISTED 說明）。
    雙向查詢：dual_listed_peer("2330") == "TSM"、dual_listed_peer("TSM") == "2330"。
    """
    key = company.strip().upper()
    return TW_US_DUAL_LISTED.get(key) or _US_TO_TW.get(key)


def otc_adr_of(company: str) -> str | None:
    """回傳該台股標的在 OTC 的 ADR 代號；沒有或非此類回 None。

    這些 ADR 存在但本專案取不到其財報，僅供回答時附帶告知，不進入市場選擇流程。
    """
    return TW_US_OTC_ONLY.get(company.strip().upper())
