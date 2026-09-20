"""最小 self-check：check_answer_format 的規則覆蓋與 i18n 欄名格式保護。
執行：python tests/test_answer_format.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph import check_answer_format, _ALL_FIELDS, _FIELD_LINE_RE
from src.i18n import t

FIELDS = ["conclusion", "facts", "inference", "upside", "risk"]

GOOD_ZH = """結論在這裡。

## 📈 投資決策參考
- **一句話結論**：偏多
- **已知事實**：
  - 營收成長 [來源1]
- **推論**：
  - 動能延續 [來源2]
- **利多**：需求強
- **風險**：庫存高

以上非投資建議，僅為資料解讀，投資請自行判斷。
"""


def _rule_names(violations):
    return {v["rule"] for v in violations}


# 1: 全合格 -> []
assert check_answer_format(GOOD_ZH, FIELDS, 3, "zh") == []

# 2: 缺免責聲明 -> 只報 missing_disclaimer（09-17 迴歸）
no_disclaimer = GOOD_ZH.replace("以上非投資建議，僅為資料解讀，投資請自行判斷。\n", "")
violations = check_answer_format(no_disclaimer, FIELDS, 3, "zh")
assert _rule_names(violations) == {"missing_disclaimer"}, violations

# 3: 少一欄 -> missing_fields
missing_risk = GOOD_ZH.replace("- **風險**：庫存高\n", "")
violations = check_answer_format(missing_risk, FIELDS, 3, "zh")
assert "missing_fields" in _rule_names(violations)
detail = next(v["detail"] for v in violations if v["rule"] == "missing_fields")
assert "風險" in detail

# 4: 多一欄 -> unexpected_fields
extra_field = GOOD_ZH.replace(
    "- **風險**：庫存高\n", "- **風險**：庫存高\n- **多餘欄**：不該出現\n")
violations = check_answer_format(extra_field, FIELDS, 3, "zh")
assert "unexpected_fields" in _rule_names(violations)
detail = next(v["detail"] for v in violations if v["rule"] == "unexpected_fields")
assert "多餘欄" in detail

# 5: [來源9] 但只有 3 個來源 -> citation_out_of_range
out_of_range = GOOD_ZH.replace("[來源2]", "[來源9]")
violations = check_answer_format(out_of_range, FIELDS, 3, "zh")
assert "citation_out_of_range" in _rule_names(violations)
detail = next(v["detail"] for v in violations if v["rule"] == "citation_out_of_range")
assert detail == [9]

# 6: [即時市場數據] -> unknown_citation_marker（待辦「[即時市場數據] 被當成引用標記」迴歸）
unknown_marker = GOOD_ZH.replace("需求強", "需求強 [即時市場數據]")
violations = check_answer_format(unknown_marker, FIELDS, 3, "zh")
assert "unknown_citation_marker" in _rule_names(violations)
detail = next(v["detail"] for v in violations if v["rule"] == "unknown_citation_marker")
assert "即時市場數據" in detail

# 7: markdown 連結 [看這裡](http://x) -> 不誤報 unknown_citation_marker
md_link = GOOD_ZH.replace("需求強", "需求強 [看這裡](http://x)")
violations = check_answer_format(md_link, FIELDS, 3, "zh")
assert "unknown_citation_marker" not in _rule_names(violations), violations

# 8: 英文 lang -> 欄名與 [Source 1]（label 尾端空格）都要過
GOOD_EN = """Conclusion here.

## 📈 Investment Decision Reference
- **One-line conclusion**: bullish
- **Known facts**:
  - Revenue grew [Source 1]
- **Inference**:
  - Momentum continues [Source 2]
- **Positives**: strong demand
- **Risks**: high inventory

This is not investment advice — data interpretation only. Invest at your own discretion.
"""
assert check_answer_format(GOOD_EN, FIELDS, 3, "en") == []

# 9: 縮排子條列 "  - **xxx**：" 不被當成欄位
indented = GOOD_ZH.replace(
    "  - 營收成長 [來源1]\n", "  - 營收成長 [來源1]\n  - **子項**：不是欄位\n")
violations = check_answer_format(indented, FIELDS, 3, "zh")
assert violations == [], violations

# 10: 格式保護測試——_ALL_FIELDS × ["zh", "en"]，每個 trend_field_* 都抽得出非空欄名
for field_id in _ALL_FIELDS:
    for lang in ("zh", "en"):
        raw = t(lang, f"trend_field_{field_id}")
        m = _FIELD_LINE_RE.match(raw)
        assert m is not None, (field_id, lang, raw)
        assert m.group(1).strip(), (field_id, lang, raw)

# 11-13: 全形【】。實測模型在中文語境輸出的是【來源1】【即時市場數據】而非半形，
# 只認半形的話這三種違規全都靜悄悄地漏掉。
full_ok = GOOD_ZH.replace("[來源1]", "【來源1】").replace("[來源2]", "【來源2】")
assert check_answer_format(full_ok, FIELDS, 3, "zh") == [], full_ok

full_unknown = full_ok.replace("需求強", "需求強【即時市場數據】")
violations = check_answer_format(full_unknown, FIELDS, 3, "zh")
detail = next(v["detail"] for v in violations if v["rule"] == "unknown_citation_marker")
assert "即時市場數據" in detail

full_oor = full_ok.replace("【來源2】", "【來源9】")
violations = check_answer_format(full_oor, FIELDS, 3, "zh")
detail = next(v["detail"] for v in violations if v["rule"] == "citation_out_of_range")
assert detail == [9]

print("check_answer_format self-check OK")
