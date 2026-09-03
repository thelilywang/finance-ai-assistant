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
