"""最小 self-check：_select_report_file 從 MOPS 檔名清單選出正確財報。
執行：python tests/test_update.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.update import _select_report_file

# 真實案例（2330，115年第一、二季）：同月份有中文主文(AI1)與英文版(AIA)，
# 應選最新月份(202602)的中文主文，不是字典序最後一筆(202602_2330_AIA.pdf)
files = [
    "202601_2330_AI1.pdf", "202601_2330_AIA.pdf",
    "202602_2330_AI1.pdf", "202602_2330_AIA.pdf",
]
assert _select_report_file(files) == "202602_2330_AI1.pdf"

# 最新月份只有英文版（中文主文尚未上傳）→ 退而求其次選英文版
only_en = ["202601_2330_AI1.pdf", "202602_2330_AIA.pdf"]
assert _select_report_file(only_en) == "202602_2330_AIA.pdf"

# 只有一份檔案
assert _select_report_file(["202602_2330_AI1.pdf"]) == "202602_2330_AI1.pdf"

# 查無資料
assert _select_report_file([]) is None

# 重複檔名（同一份檔案在頁面中出現兩次）不影響選擇結果
dup = ["202602_2330_AI1.pdf", "202602_2330_AI1.pdf", "202602_2330_AIA.pdf"]
assert _select_report_file(dup) == "202602_2330_AI1.pdf"

print("update self-check OK")
