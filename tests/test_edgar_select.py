"""最小 self-check：EDGAR 6-K 選取與 exhibit 挑選。
執行：python tests/test_edgar_select.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.update import _is_period_end, _select_exhibit, _select_filing

FORMS = ("10-Q", "10-K", "6-K", "20-F", "424B4", "S-1")


def recent(rows):
    """rows: [(form, filingDate, reportDate)] → EDGAR 的欄位導向結構。"""
    return {
        "form": [r[0] for r in rows],
        "filingDate": [r[1] for r in rows],
        "reportDate": [r[2] for r in rows],
    }


# 期末判定：申報日 == 報導日是公告，不是財報
assert _is_period_end("2026-06-28", "2026-07-15")   # ASML 52/53 週期末
assert _is_period_end("2026-06-30", "2026-08-14")   # TSM 季末
assert not _is_period_end("2026-04-23", "2026-04-23")  # AGM 公告
assert not _is_period_end("", "2026-04-23")            # 無 reportDate
assert not _is_period_end("2026-06-15", "2026-07-15")  # 月中，非期末
assert not _is_period_end("not-a-date", "2026-07-15")  # 壞資料不炸
# TSM 每月申報月營收，reportDate 是月底但非季末月份 → 不是財報
assert not _is_period_end("2026-07-31", "2026-08-25")
assert not _is_period_end("2026-01-31", "2026-02-10")

# ASML 真實樣本（反時序）：跳過 04-23 的 AGM，選中 07-15 的季報
asml = recent([
    ("6-K", "2026-07-15", "2026-06-28"),
    ("6-K", "2026-04-23", "2026-04-23"),
    ("6-K", "2026-04-15", "2026-03-29"),
    ("20-F", "2026-02-25", "2025-12-31"),
])
assert _select_filing(asml, FORMS) == ("6-K", 0)

# TSM 真實樣本：最新一份 6-K 是股利調整公告，應跳過，選 08-14 的財報
tsm = recent([
    ("6-K", "2026-09-01", "2026-09-01"),   # 股利調整（reportDate == filingDate）
    ("6-K", "2026-08-25", "2026-07-31"),   # 月營收（月底但非季末月份）
    ("6-K", "2026-08-14", "2026-06-30"),   # 財報
])
assert _select_filing(tsm, FORMS) == ("6-K", 2)

# 全部 6-K 都是同日 reportDate（NIO 樣態）→ 回退到 20-F
nio = recent([
    ("6-K", "2026-09-01", "2026-09-01"),
    ("6-K", "2026-08-20", "2026-08-20"),
    ("20-F", "2026-04-30", "2025-12-31"),
])
assert _select_filing(nio, FORMS) == ("20-F", 2)

# 表單優先序：10-Q 在清單中優先於後面的 6-K
us = recent([
    ("6-K", "2026-08-01", "2026-06-30"),
    ("10-Q", "2026-07-31", "2026-06-30"),
])
assert _select_filing(us, FORMS) == ("10-Q", 1)

# 查無任何目標表單
assert _select_filing(recent([("8-K", "2026-08-01", "2026-08-01")]), FORMS) is None

# exhibit 挑選：選最大的非主文 .htm（NIO 真實樣本）
items = [
    {"name": "tm2624535d2_6k.htm", "size": "12518"},
    {"name": "tm2624535d2_ex99-1.htm", "size": "668825"},
    {"name": "0001104659-26-104116-index.html", "size": "9000"},
    {"name": "logo.jpg", "size": "999999"},
]
assert _select_exhibit(items, "tm2624535d2_6k.htm") == "tm2624535d2_ex99-1.htm"

# 只有主文（TSM 股利公告樣態）→ 退回主文
assert _select_exhibit(
    [{"name": "tsm-only.htm", "size": "16297"}], "tsm-only.htm"
) == "tsm-only.htm"

# 空清單 → 退回主文
assert _select_exhibit([], "primary.htm") == "primary.htm"

# size 缺漏或為 None 不炸
assert _select_exhibit(
    [{"name": "a.htm", "size": None}, {"name": "b.htm", "size": "10"}], "p.htm"
) == "b.htm"

print("edgar select self-check OK")
