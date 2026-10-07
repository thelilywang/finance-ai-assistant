"""台股財報兩軌的純函式。

MOPS 那軌的 _select_report_file 選檔邏輯，以及官方 OpenAPI 那軌的欄位解析與格式化。
皆為純函式，不連網、不碰 DB。
"""
import contextlib
import io

import src.update as _u
from src.update import (
    _find_company_row,
    _fmt_amount,
    _format_rows,
    _format_xbrl,
    _pick_fact,
    _quarter_end_date,
    _select_report_file,
)


def test_select_report_file():
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


# --- 官方 OpenAPI 那軌的純函式 ---

# 證交所用中文欄位名，櫃買用英文欄位名（實測差異），同一套邏輯兩邊都要吃得到。
# 這是雙來源命名差異的迴歸保護：任一邊改版或有人只改一處時，這裡會先失敗。
TWSE_ROWS = [
    {"公司代號": "1101", "公司名稱": "台泥", "年度": "115", "季別": "2", "營業收入": "10000.00"},
    {"公司代號": "2330", "公司名稱": "台積電", "年度": "115", "季別": "2",
     "營業收入": "2404483690.00", "基本每股盈餘（元）": "49.33",
     "原始認列生物資產及農產品之利益（損失）": ""},
]
TPEX_ROWS = [
    {"SecuritiesCompanyCode": "6488", "CompanyName": "環球晶", "Year": "115", "Season": "2",
     "營業收入": "1234.00"},
]


def test_find_company_row():
    assert _find_company_row(TWSE_ROWS, "2330")["公司名稱"] == "台積電"
    assert _find_company_row(TPEX_ROWS, "6488")["CompanyName"] == "環球晶"
    assert _find_company_row(TWSE_ROWS, "9999") is None
    assert _find_company_row([], "2330") is None


def test_quarter_end_date():
    # 民國年 + 季別 → 季末次月一日；Q4 會跨到隔年
    assert _quarter_end_date("115", "2") == "2026-08-01"
    assert _quarter_end_date("115", "1") == "2026-05-01"
    assert _quarter_end_date("115", "4") == "2027-02-01"
    assert _quarter_end_date("", "2") is None          # 欄位缺失不炸
    assert _quarter_end_date("115", "9") is None       # 季別超出範圍


def test_fmt_amount():
    # 金額加千分位便於閱讀；非數字原樣輸出（欄位可能是文字說明）
    assert _fmt_amount("2404483690.00") == "2,404,483,690"
    assert _fmt_amount("49.33") == "49.33"
    assert _fmt_amount("") == ""
    assert _fmt_amount("不適用") == "不適用"


def test_format_rows_twse():
    text, published_at, label = _format_rows(
        [("綜合損益表", _find_company_row(TWSE_ROWS, "2330"))], "2330"
    )
    assert "台積電（2330）115 年上半年（1～6 月累計，第 2 季財報） 綜合損益表" in text
    assert "仟元" in text                                # 不標單位 LLM 會把數字讀成元
    assert "營業收入：2,404,483,690" in text
    assert "原始認列生物資產" not in text                 # 空欄位略過，不灌入雜訊
    assert "公司代號" not in text                        # 識別欄位不當成財務數字輸出
    assert (published_at, label) == ("2026-08-01", "115Q2")


def test_format_rows_tpex_english_keys():
    # 櫃買的英文鍵一樣要能格式化出中文表頭
    tpex_text, _, tpex_label = _format_rows(
        [("綜合損益表", _find_company_row(TPEX_ROWS, "6488"))], "6488"
    )
    assert "環球晶（6488）115 年上半年（1～6 月累計，第 2 季財報）" in tpex_text
    assert tpex_label == "115Q2"


def test_format_rows_missing_data_returns_none():
    # 查無資料 / 缺年度季別 → None，呼叫端據此回報失敗而非寫入半套資料
    assert _format_rows([], "2330") is None
    assert _format_rows([("綜合損益表", {"公司代號": "2330"})], "2330") is None


# --- 抓取層契約：網路錯誤回 FetchResult，資料層錯誤往上拋 ---


def test_fetch_edgar_network_error_returns_fetch_result(monkeypatch):
    # SEC 掛掉（429/逾時）時要回 FetchResult，不能拋錯——CLI 才印得出可讀訊息，
    # 而非 traceback。與 fetch_mops／fetch_tw_financials 同一契約。
    monkeypatch.setattr(
        _u.requests, "get",
        lambda *a, **k: (_ for _ in ()).throw(_u.requests.RequestException("SEC 429")),
    )
    with contextlib.redirect_stdout(io.StringIO()):  # 預期中的錯誤訊息，不污染測試輸出
        r = _u.fetch_edgar("AAPL")
    assert r.ok is False and "SEC EDGAR" in r.detail
    # _company_tickers 用 lru_cache，上面的假回應（拋錯）若殘留在快取會污染後續測試
    _u._company_tickers.cache_clear()


def test_fetch_edgar_throttle_page_not_ingested(monkeypatch):
    # SEC 節流頁是 HTTP 200，raise_for_status 攔不住；不檢查會把警告文字當財報入庫
    # 並回報成功（靜默污染檢索結果）。此處釘住「內容過短即視為失敗、不入庫」。
    ingested = []

    class _R:
        def __init__(self, j=None, t=""):
            self._j, self.text = j, t

        def raise_for_status(self):
            pass

        def json(self):
            return self._j

    def _fake_get(url, **kw):
        if "company_tickers" in url:
            return _R({"0": {"ticker": "AAPL", "cik_str": 320193}})
        if "submissions" in url:
            return _R({"filings": {"recent": {
                "form": ["10-Q"], "reportDate": ["2026-06-27"], "filingDate": ["2026-07-30"],
                "accessionNumber": ["0000320193-26-000070"], "primaryDocument": ["aapl.htm"]}}})
        return _R(t=_fake_get.body)

    monkeypatch.setattr(_u.requests, "get", _fake_get)
    monkeypatch.setattr(_u, "ingest_text", lambda text, **kw: ingested.append(text) or 1)

    _fake_get.body = "<html>Your Request Originates from an Undeclared Automated Tool</html>"
    with contextlib.redirect_stdout(io.StringIO()):
        r = _u.fetch_edgar("AAPL")
    assert r.ok is False and not ingested      # 節流頁不得入庫
    _u._company_tickers.cache_clear()


def test_fetch_edgar_normal_report_ingested(monkeypatch):
    ingested = []

    class _R:
        def __init__(self, j=None, t=""):
            self._j, self.text = j, t

        def raise_for_status(self):
            pass

        def json(self):
            return self._j

    def _fake_get(url, **kw):
        if "company_tickers" in url:
            return _R({"0": {"ticker": "AAPL", "cik_str": 320193}})
        if "submissions" in url:
            return _R({"filings": {"recent": {
                "form": ["10-Q"], "reportDate": ["2026-06-27"], "filingDate": ["2026-07-30"],
                "accessionNumber": ["0000320193-26-000070"], "primaryDocument": ["aapl.htm"]}}})
        return _R(t=_fake_get.body)

    monkeypatch.setattr(_u.requests, "get", _fake_get)
    monkeypatch.setattr(_u, "ingest_text", lambda text, **kw: ingested.append(text) or 1)

    _fake_get.body = "<html>" + "Total net sales were 100 billion. " * 40 + "</html>"
    with contextlib.redirect_stdout(io.StringIO()):
        r = _u.fetch_edgar("AAPL")
    assert r.ok is True and len(ingested) == 1  # 正常財報照常入庫
    _u._company_tickers.cache_clear()


# --- CIK 快取：同一次執行只打一次 company_tickers.json ---


def test_company_tickers_cached(monkeypatch):
    call_count = {"n": 0}

    def _counting_get(url, **kw):
        if "company_tickers" in url:
            call_count["n"] += 1

            class _R:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"0": {"ticker": "AAPL", "cik_str": 320193}}
            return _R()
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(_u.requests, "get", _counting_get)
    _u._company_tickers.cache_clear()
    _u._company_tickers()
    _u._company_tickers()
    assert call_count["n"] == 1  # 第二次呼叫吃快取，不再打網路
    _u._company_tickers.cache_clear()


# --- SEC XBRL 純函式：_pick_fact / _format_xbrl ---


def test_pick_fact_prefers_latest_period():
    # 同一 accession 回三列（年初至今 vs 當季，AAPL 實測樣本）：取 start 最晚那列＝當季數字
    aapl_units = {"USD": [
        {"accn": "0000320193-26-000070", "start": "2025-10-01", "end": "2025-12-31", "val": 100, "filed": "2026-01-30"},
        {"accn": "0000320193-26-000070", "start": "2025-01-01", "end": "2025-12-31", "val": 400, "filed": "2026-01-30"},
        {"accn": "0000320193-25-000050", "start": "2024-10-01", "end": "2024-12-31", "val": 90, "filed": "2025-01-30"},
    ]}
    assert _pick_fact(aapl_units, "0000320193-26-000070") == (100, "USD", True, "2025-10-01~2025-12-31")


def test_pick_fact_point_in_time_no_start():
    # 資產負債表這類時點數字沒有 start，直接取該 accession 那列
    bs_units = {"USD": [{"accn": "acc1", "end": "2025-12-31", "val": 500, "filed": "2026-01-30"}]}
    assert _pick_fact(bs_units, "acc1") == (500, "USD", True, "2025-12-31")


def test_pick_fact_prefers_usd_over_other_currency():
    # 雙幣別（TSM 情境）：優先取 USD 而非字典裡先出現的 TWD
    dual_currency = {
        "TWD": [{"accn": "tw-acc", "start": "2025-01-01", "end": "2025-12-31", "val": 999, "filed": "2026-03-01"}],
        "USD": [{"accn": "tw-acc", "start": "2025-01-01", "end": "2025-12-31", "val": 31, "filed": "2026-03-01"}],
    }
    assert _pick_fact(dual_currency, "tw-acc") == (31, "USD", True, "2025-01-01~2025-12-31")


def test_pick_fact_falls_back_to_latest_filed_when_stale():
    # companyfacts 落後：對不到該 accession，退回同幣別中 filed 最新的一批（TSM 20-F 落後情境）
    stale_units = {"USD": [
        {"accn": "old-acc-1", "start": "2023-01-01", "end": "2023-12-31", "val": 10, "filed": "2024-01-01"},
        {"accn": "old-acc-2", "start": "2024-01-01", "end": "2024-12-31", "val": 20, "filed": "2025-01-01"},
    ]}
    # 第三個值為 False：這是退而求其次的舊數字，呼叫端據此優先改用其他概念
    assert _pick_fact(stale_units, "brand-new-accession-not-in-facts") == (20, "USD", False, "2024-01-01~2024-12-31")


def test_pick_fact_empty():
    assert _pick_fact({}, "acc1") is None


def test_pick_fact_point_in_time_multiple_periods():
    # 時點數字（資產負債表）沒有 start，同一份申報會同時列出本期與多期比較數。
    # 只依 start 排序會在這些列之間任意挑一期——AAPL 實測會選到兩年前的權益數
    point_in_time = {"USD": [
        {"accn": "acc1", "end": "2024-09-28", "val": 56950000000, "filed": "2026-07-31"},
        {"accn": "acc1", "end": "2026-06-27", "val": 107520000000, "filed": "2026-07-31"},
        {"accn": "acc1", "end": "2025-09-27", "val": 73733000000, "filed": "2026-07-31"},
    ]}
    assert _pick_fact(point_in_time, "acc1") == (107520000000, "USD", True, "2026-06-27")


def test_pick_fact_same_end_prefers_shorter_period():
    # 期末日相同時取期間較短者＝當季，而非年初至今
    same_end = {"USD": [
        {"accn": "acc1", "start": "2025-09-28", "end": "2026-06-27", "val": 364357000000, "filed": "2026-07-31"},
        {"accn": "acc1", "start": "2026-03-29", "end": "2026-06-27", "val": 109417000000, "filed": "2026-07-31"},
    ]}
    assert _pick_fact(same_end, "acc1") == (109417000000, "USD", True, "2026-03-29~2026-06-27")


def test_format_xbrl_basic():
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


def test_format_xbrl_skips_stale_concept():
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


def test_format_xbrl_dual_currency_eps_prefers_usd():
    # 雙幣別 EPS：單位鍵是 USD/shares 而非 USD，前綴比對才選得到美元那組。
    # 只比對 "USD" 會取到 TWD/shares 的 44.67，被 LLM 當成美元讀，量級差 30 倍以上
    dual_eps = {"ifrs-full": {"DilutedEarningsLossPerShare": {"units": {
        "TWD/shares": [{"accn": "acc1", "start": "2024-01-01", "end": "2024-12-31", "val": 44.67, "filed": "2025-04-17"}],
        "USD/shares": [{"accn": "acc1", "start": "2024-01-01", "end": "2024-12-31", "val": 1.36, "filed": "2025-04-17"}],
    }}}}
    assert "1.36（USD/股，期間" in _format_xbrl(dual_eps, "ifrs-full", "acc1", "tsm", "20-F")


def test_format_xbrl_non_usd_currency_shown_as_is():
    # 只有非美元幣別時，幣別照實寫出，不可簡化成「元」
    twd_only = {"ifrs-full": {"DilutedEarningsLossPerShare": {"units": {
        "TWD/shares": [{"accn": "acc1", "start": "2024-01-01", "end": "2024-12-31", "val": 44.67, "filed": "2025-04-17"}],
    }}}}
    assert "44.67（TWD/股，期間" in _format_xbrl(twd_only, "ifrs-full", "acc1", "tsm", "20-F")


def test_format_xbrl_stale_only_returns_none():
    # 落後期的數字整條不寫出，只剩它時回 None——警語擋不住 LLM，TSM 實測照引了 2024 年報數字
    stale_facts = {"ifrs-full": {"Revenue": {"units": {"USD": [
        {"accn": "old-acc", "start": "2024-01-01", "end": "2024-12-31", "val": 88268000000, "filed": "2025-04-17"},
    ]}}}}
    assert _format_xbrl(stale_facts, "ifrs-full", "new-acc-not-in-facts", "tsm", "6-K（2026-08-14）") is None


def test_format_xbrl_mixed_keeps_current_drops_stale():
    # 混合期（JPM 實測形狀）：當期的留、落後的丟，不因為一條落後就丟掉整份——
    # JPM 與 SPCX 的 EDGAR 全文塊數是 0，整份丟等於這兩家完全沒有財報數字
    mixed = {"us-gaap": {
        "Revenues": {"units": {"USD": [
            {"accn": "old-acc", "start": "2025-01-01", "end": "2025-12-31", "val": 182447000000, "filed": "2026-02-01"},
        ]}},
        "NetIncomeLoss": {"units": {"USD": [
            {"accn": "acc1", "start": "2026-04-01", "end": "2026-06-30", "val": 21155000000, "filed": "2026-08-01"},
        ]}},
    }}
    mixed_text = _format_xbrl(mixed, "us-gaap", "acc1", "jpm", "10-Q")
    assert "21,155,000,000（USD，期間 2026-04-01~2026-06-30）" in mixed_text, mixed_text
    assert "182,447,000,000" not in mixed_text, mixed_text
    # 少列的指標要明講，免得 LLM 把「沒列出」讀成「該指標為零」
    assert "已略去不列" in mixed_text and "營業收入" in mixed_text, mixed_text


def test_format_xbrl_no_stale_note_when_all_current():
    # 全部命中當期則不得出現略去註記，否則每份都加註等於沒有警示作用
    assert "已略去不列" not in _format_xbrl(
        {"us-gaap": {"Revenues": {"units": {"USD": [
            {"accn": "acc1", "start": "2025-10-01", "end": "2025-12-31", "val": 1000000, "filed": "2026-01-30"},
        ]}}}}, "us-gaap", "acc1", "aapl", "10-Q")


def test_format_xbrl_nothing_current_returns_none():
    # 一條都取不到 → None，呼叫端據此回報失敗而非入庫半份資料
    assert _format_xbrl({"us-gaap": {}}, "us-gaap", "acc1", "aapl", "10-Q") is None


# --- fetch_sec_financials 契約：網路錯誤回 FetchResult，不入庫 ---


def test_fetch_sec_financials_network_error(monkeypatch):
    monkeypatch.setattr(
        _u.requests, "get",
        lambda *a, **k: (_ for _ in ()).throw(_u.requests.RequestException("SEC 429")),
    )
    with contextlib.redirect_stdout(io.StringIO()):
        r = _u.fetch_sec_financials("AAPL")
    assert r.ok is False and "SEC XBRL" in r.detail
    _u._company_tickers.cache_clear()


# --- 一條當期數字都沒有的 XBRL 不入庫 ---
# TSM 2026Q2 實測：這塊是全庫唯一「長得像財報摘要」的乾淨數字清單（同申報的 EDGAR
# 全文散成 371 塊會計附註碎片），相似度排序穩定排第一，LLM 照引了裡面的 2024 年報
# 數字——即使開頭已寫明非當期、每條都標了期間。文案擋不住，故落後期逐條不寫出，
# 全落後時 _format_xbrl 回 None 而不入庫（混合期的行為見上方 sec xbrl 那組）。


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_sec_financials_all_stale_not_ingested(monkeypatch):
    ingested = []

    def _fake_get(url, **_kw):
        if "submissions" in url:
            return _Resp({"filings": {"recent": {
                "form": ["6-K"], "accessionNumber": ["new-acc"],
                "filingDate": ["2026-08-14"], "reportDate": ["2026-06-30"],
                "primaryDocument": ["d.htm"], "items": [""],
            }}})
        # companyfacts 只有更早期的數字，對不到 new-acc → 整份 stale
        return _Resp({"facts": {"ifrs-full": {"Revenue": {"units": {"USD": [
            {"accn": "old-acc", "start": "2024-01-01", "end": "2024-12-31",
             "val": 88268000000, "filed": "2025-04-17"},
        ]}}}}})

    monkeypatch.setattr(_u, "ingest_text", lambda *a, **k: ingested.append(k.get("source")))
    monkeypatch.setattr(_u, "_company_tickers", lambda: {"0": {"ticker": "TSM", "cik_str": 1046179}})
    monkeypatch.setattr(_u.requests, "get", _fake_get)

    with contextlib.redirect_stdout(io.StringIO()):
        r = _u.fetch_sec_financials("TSM")
    assert r.ok is False, f"整份落後期應回失敗，實得 {r}"
    assert "無本次申報" in r.detail, r.detail
    assert ingested == [], f"整份落後期不該入庫，實得 {ingested}"


def test_fetch_sec_financials_current_period_ingested(monkeypatch):
    # 對照組：命中當期就要照常入庫，否則等於把正常的一起擋掉
    ingested = []

    def _fresh_get(url, **_kw):
        if "submissions" in url:
            return _Resp({"filings": {"recent": {
                "form": ["6-K"], "accessionNumber": ["new-acc"],
                "filingDate": ["2026-08-14"], "reportDate": ["2026-06-30"],
                "primaryDocument": ["d.htm"], "items": [""],
            }}})
        return _Resp({"facts": {"ifrs-full": {"Revenue": {"units": {"USD": [
            {"accn": "new-acc", "start": "2026-04-01", "end": "2026-06-30",
             "val": 1000000, "filed": "2026-08-14"},
        ]}}}}})

    monkeypatch.setattr(_u, "ingest_text", lambda *a, **k: ingested.append(k.get("source")))
    monkeypatch.setattr(_u, "_company_tickers", lambda: {"0": {"ticker": "TSM", "cik_str": 1046179}})
    monkeypatch.setattr(_u.requests, "get", _fresh_get)

    with contextlib.redirect_stdout(io.StringIO()):
        r = _u.fetch_sec_financials("TSM")
    assert r.ok is True, f"命中當期應入庫，實得 {r}"
    assert ingested == ["SEC-XBRL:TSM:new-acc"], ingested
