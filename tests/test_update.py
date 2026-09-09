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
    # _company_tickers 用 lru_cache，上面的假回應（拋錯）若殘留在快取會污染後續測試
    _u._company_tickers.cache_clear()

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
    _u._company_tickers.cache_clear()

print("fetch contract self-check OK")

# --- CIK 快取：同一次執行只打一次 company_tickers.json ---

_call_count = {"n": 0}


def _counting_get(url, **kw):
    if "company_tickers" in url:
        _call_count["n"] += 1
        class _R:
            def raise_for_status(self): pass
            def json(self): return {"0": {"ticker": "AAPL", "cik_str": 320193}}
        return _R()
    raise AssertionError(f"unexpected url {url}")


try:
    _u.requests.get = _counting_get
    _u._company_tickers()
    _u._company_tickers()
    assert _call_count["n"] == 1  # 第二次呼叫吃快取，不再打網路
finally:
    _u.requests.get = _orig_get
    _u._company_tickers.cache_clear()

print("company tickers cache self-check OK")

# --- SEC XBRL 純函式：_pick_fact / _format_xbrl ---

from src.update import _format_xbrl, _pick_fact

# 同一 accession 回三列（年初至今 vs 當季，AAPL 實測樣本）：取 start 最晚那列＝當季數字
aapl_units = {"USD": [
    {"accn": "0000320193-26-000070", "start": "2025-10-01", "end": "2025-12-31", "val": 100, "filed": "2026-01-30"},
    {"accn": "0000320193-26-000070", "start": "2025-01-01", "end": "2025-12-31", "val": 400, "filed": "2026-01-30"},
    {"accn": "0000320193-25-000050", "start": "2024-10-01", "end": "2024-12-31", "val": 90, "filed": "2025-01-30"},
]}
assert _pick_fact(aapl_units, "0000320193-26-000070") == (100, "USD", True, "2025-10-01~2025-12-31")

# 資產負債表這類時點數字沒有 start，直接取該 accession 那列
bs_units = {"USD": [{"accn": "acc1", "end": "2025-12-31", "val": 500, "filed": "2026-01-30"}]}
assert _pick_fact(bs_units, "acc1") == (500, "USD", True, "2025-12-31")

# 雙幣別（TSM 情境）：優先取 USD 而非字典裡先出現的 TWD
dual_currency = {
    "TWD": [{"accn": "tw-acc", "start": "2025-01-01", "end": "2025-12-31", "val": 999, "filed": "2026-03-01"}],
    "USD": [{"accn": "tw-acc", "start": "2025-01-01", "end": "2025-12-31", "val": 31, "filed": "2026-03-01"}],
}
assert _pick_fact(dual_currency, "tw-acc") == (31, "USD", True, "2025-01-01~2025-12-31")

# companyfacts 落後：對不到該 accession，退回同幣別中 filed 最新的一批（TSM 20-F 落後情境）
stale_units = {"USD": [
    {"accn": "old-acc-1", "start": "2023-01-01", "end": "2023-12-31", "val": 10, "filed": "2024-01-01"},
    {"accn": "old-acc-2", "start": "2024-01-01", "end": "2024-12-31", "val": 20, "filed": "2025-01-01"},
]}
# 第三個值為 False：這是退而求其次的舊數字，呼叫端據此優先改用其他概念
assert _pick_fact(stale_units, "brand-new-accession-not-in-facts") == (20, "USD", False, "2024-01-01~2024-12-31")

# 查無資料
assert _pick_fact({}, "acc1") is None

facts = {"us-gaap": {
    "Revenues": {"units": {"USD": [
        {"accn": "acc1", "start": "2025-10-01", "end": "2025-12-31", "val": 1000000, "filed": "2026-01-30"},
    ]}},
    "EarningsPerShareDiluted": {"units": {"USD/shares": [
        {"accn": "acc1", "start": "2025-10-01", "end": "2025-12-31", "val": 1.5, "filed": "2026-01-30"},
    ]}},
}}
text = _format_xbrl(facts, "us-gaap", "acc1", "aapl", "10-Q（2026-01-30）")
assert "營業收入：1,000,000" in text
assert "1.5（USD/股，期間" in text  # EPS 要帶幣別，不可只寫「元/股」
assert "USD" in text
assert "acc1" in text

# 概念清單首位已停用（AAPL 實測：Revenues 最新只到 2018 年，本季營收在後面那個概念）。
# 不可取第一個有值的就停，否則會拿八年前的數字當本季營收
stale_first = {"us-gaap": {
    "Revenues": {"units": {"USD": [
        {"accn": "old-2018", "start": "2018-07-01", "end": "2018-09-29", "val": 62900000000, "filed": "2018-11-05"},
    ]}},
    "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
        {"accn": "acc1", "start": "2025-10-01", "end": "2025-12-31", "val": 109417000000, "filed": "2026-01-30"},
    ]}},
}}
text_stale = _format_xbrl(stale_first, "us-gaap", "acc1", "aapl", "10-Q")
assert "109,417,000,000" in text_stale and "62,900,000,000" not in text_stale

# 雙幣別 EPS：單位鍵是 USD/shares 而非 USD，前綴比對才選得到美元那組。
# 只比對 "USD" 會取到 TWD/shares 的 44.67，被 LLM 當成美元讀，量級差 30 倍以上
dual_eps = {"ifrs-full": {"DilutedEarningsLossPerShare": {"units": {
    "TWD/shares": [{"accn": "acc1", "start": "2024-01-01", "end": "2024-12-31", "val": 44.67, "filed": "2025-04-17"}],
    "USD/shares": [{"accn": "acc1", "start": "2024-01-01", "end": "2024-12-31", "val": 1.36, "filed": "2025-04-17"}],
}}}}
assert "1.36（USD/股，期間" in _format_xbrl(dual_eps, "ifrs-full", "acc1", "tsm", "20-F")

# 只有非美元幣別時，幣別照實寫出，不可簡化成「元」
twd_only = {"ifrs-full": {"DilutedEarningsLossPerShare": {"units": {
    "TWD/shares": [{"accn": "acc1", "start": "2024-01-01", "end": "2024-12-31", "val": 44.67, "filed": "2025-04-17"}],
}}}}
assert "44.67（TWD/股，期間" in _format_xbrl(twd_only, "ifrs-full", "acc1", "tsm", "20-F")

# 時點數字（資產負債表）沒有 start，同一份申報會同時列出本期與多期比較數。
# 只依 start 排序會在這些列之間任意挑一期——AAPL 實測會選到兩年前的權益數
point_in_time = {"USD": [
    {"accn": "acc1", "end": "2024-09-28", "val": 56950000000, "filed": "2026-07-31"},
    {"accn": "acc1", "end": "2026-06-27", "val": 107520000000, "filed": "2026-07-31"},
    {"accn": "acc1", "end": "2025-09-27", "val": 73733000000, "filed": "2026-07-31"},
]}
assert _pick_fact(point_in_time, "acc1") == (107520000000, "USD", True, "2026-06-27")

# 期末日相同時取期間較短者＝當季，而非年初至今
same_end = {"USD": [
    {"accn": "acc1", "start": "2025-09-28", "end": "2026-06-27", "val": 364357000000, "filed": "2026-07-31"},
    {"accn": "acc1", "start": "2026-03-29", "end": "2026-06-27", "val": 109417000000, "filed": "2026-07-31"},
]}
assert _pick_fact(same_end, "acc1") == (109417000000, "USD", True, "2026-03-29~2026-06-27")

# 落後 fallback 時整份加註警語，且每條標出實際期間，避免舊年報被當成最新一季
stale_facts = {"ifrs-full": {"Revenue": {"units": {"USD": [
    {"accn": "old-acc", "start": "2024-01-01", "end": "2024-12-31", "val": 88268000000, "filed": "2025-04-17"},
]}}}}
stale_text = _format_xbrl(stale_facts, "ifrs-full", "new-acc-not-in-facts", "tsm", "6-K（2026-08-14）")
assert "並非本次申報當期" in stale_text
assert "期間 2024-01-01~2024-12-31" in stale_text

# 命中當期則不得出現警語，否則每份都加註等於沒有警示作用
assert "並非本次申報當期" not in _format_xbrl(
    {"us-gaap": {"Revenues": {"units": {"USD": [
        {"accn": "acc1", "start": "2025-10-01", "end": "2025-12-31", "val": 1000000, "filed": "2026-01-30"},
    ]}}}}, "us-gaap", "acc1", "aapl", "10-Q")

# 一條都取不到 → None，呼叫端據此回報失敗而非入庫半份資料
assert _format_xbrl({"us-gaap": {}}, "us-gaap", "acc1", "aapl", "10-Q") is None

print("sec xbrl self-check OK")

# --- fetch_sec_financials 契約：網路錯誤回 FetchResult，不入庫 ---

try:
    _u.requests.get = lambda *a, **k: (_ for _ in ()).throw(
        _u.requests.RequestException("SEC 429")
    )
    with contextlib.redirect_stdout(io.StringIO()):
        _r = _u.fetch_sec_financials("AAPL")
    assert _r.ok is False and "SEC XBRL" in _r.detail
finally:
    _u.requests.get = _orig_get
    _u._company_tickers.cache_clear()

print("fetch_sec_financials contract self-check OK")
