"""最小 self-check：台股財報兩軌的純函式。

MOPS 那軌的 _select_report_file 選檔邏輯，以及官方 OpenAPI 那軌的欄位解析與格式化。
皆為純函式，不連網、不碰 DB。
執行：python tests/test_update.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.update import (
    _find_company_row, _fmt_amount, _format_rows, _quarter_end_date, _select_report_file,
)

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

# --- 官方 OpenAPI 那軌的純函式 ---

# 證交所用中文欄位名，櫃買用英文欄位名（實測差異），同一套邏輯兩邊都要吃得到。
# 這是雙來源命名差異的迴歸保護：任一邊改版或有人只改一處時，這裡會先失敗。
twse_rows = [
    {"公司代號": "1101", "公司名稱": "台泥", "年度": "115", "季別": "2", "營業收入": "10000.00"},
    {"公司代號": "2330", "公司名稱": "台積電", "年度": "115", "季別": "2",
     "營業收入": "2404483690.00", "基本每股盈餘（元）": "49.33",
     "原始認列生物資產及農產品之利益（損失）": ""},
]
tpex_rows = [
    {"SecuritiesCompanyCode": "6488", "CompanyName": "環球晶", "Year": "115", "Season": "2",
     "營業收入": "1234.00"},
]
assert _find_company_row(twse_rows, "2330")["公司名稱"] == "台積電"
assert _find_company_row(tpex_rows, "6488")["CompanyName"] == "環球晶"
assert _find_company_row(twse_rows, "9999") is None
assert _find_company_row([], "2330") is None

# 民國年 + 季別 → 季末次月一日；Q4 會跨到隔年
assert _quarter_end_date("115", "2") == "2026-08-01"
assert _quarter_end_date("115", "1") == "2026-05-01"
assert _quarter_end_date("115", "4") == "2027-02-01"
assert _quarter_end_date("", "2") is None          # 欄位缺失不炸
assert _quarter_end_date("115", "9") is None       # 季別超出範圍

# 金額加千分位便於閱讀；非數字原樣輸出（欄位可能是文字說明）
assert _fmt_amount("2404483690.00") == "2,404,483,690"
assert _fmt_amount("49.33") == "49.33"
assert _fmt_amount("") == ""
assert _fmt_amount("不適用") == "不適用"

text, published_at, label = _format_rows(
    [("綜合損益表", _find_company_row(twse_rows, "2330"))], "2330"
)
assert "台積電（2330）115 年第 2 季 綜合損益表" in text
assert "仟元" in text                                # 不標單位 LLM 會把數字讀成元
assert "營業收入：2,404,483,690" in text
assert "原始認列生物資產" not in text                 # 空欄位略過，不灌入雜訊
assert "公司代號" not in text                        # 識別欄位不當成財務數字輸出
assert (published_at, label) == ("2026-08-01", "115Q2")

# 櫃買的英文鍵一樣要能格式化出中文表頭
tpex_text, _, tpex_label = _format_rows(
    [("綜合損益表", _find_company_row(tpex_rows, "6488"))], "6488"
)
assert "環球晶（6488）115 年第 2 季" in tpex_text
assert tpex_label == "115Q2"

# 查無資料 / 缺年度季別 → None，呼叫端據此回報失敗而非寫入半套資料
assert _format_rows([], "2330") is None
assert _format_rows([("綜合損益表", {"公司代號": "2330"})], "2330") is None

print("tw financials self-check OK")

# --- 抓取層契約：網路錯誤回 FetchResult，資料層錯誤往上拋 ---

import contextlib
import io

import src.update as _u

_orig_get = _u.requests.get
try:
    # SEC 掛掉（429/逾時）時要回 FetchResult，不能拋錯——CLI 才印得出可讀訊息，
    # 而非 traceback。與 fetch_mops／fetch_tw_financials 同一契約。
    _u.requests.get = lambda *a, **k: (_ for _ in ()).throw(
        _u.requests.RequestException("SEC 429")
    )
    with contextlib.redirect_stdout(io.StringIO()):  # 預期中的錯誤訊息，不污染測試輸出
        _r = _u.fetch_edgar("AAPL")
    assert _r.ok is False and "SEC EDGAR" in _r.detail
finally:
    _u.requests.get = _orig_get

# SEC 節流頁是 HTTP 200，raise_for_status 攔不住；不檢查會把警告文字當財報入庫
# 並回報成功（靜默污染檢索結果）。此處釘住「內容過短即視為失敗、不入庫」。
_ingested = []


def _fake_get(url, **kw):
    class _R:
        def __init__(self, j=None, t=""):
            self._j, self.text = j, t
        def raise_for_status(self): pass
        def json(self): return self._j
    if "company_tickers" in url:
        return _R({"0": {"ticker": "AAPL", "cik_str": 320193}})
    if "submissions" in url:
        return _R({"filings": {"recent": {
            "form": ["10-Q"], "reportDate": ["2026-06-27"], "filingDate": ["2026-07-30"],
            "accessionNumber": ["0000320193-26-000070"], "primaryDocument": ["aapl.htm"]}}})
    return _R(t=_fake_get.body)


_orig_ingest = _u.ingest_text
try:
    _u.requests.get = _fake_get
    _u.ingest_text = lambda text, **kw: _ingested.append(text) or 1

    _fake_get.body = "<html>Your Request Originates from an Undeclared Automated Tool</html>"
    with contextlib.redirect_stdout(io.StringIO()):
        _r = _u.fetch_edgar("AAPL")
    assert _r.ok is False and not _ingested      # 節流頁不得入庫

    _fake_get.body = "<html>" + "Total net sales were 100 billion. " * 40 + "</html>"
    with contextlib.redirect_stdout(io.StringIO()):
        _r = _u.fetch_edgar("AAPL")
    assert _r.ok is True and len(_ingested) == 1  # 正常財報照常入庫
finally:
    _u.requests.get, _u.ingest_text = _orig_get, _orig_ingest

print("fetch contract self-check OK")
