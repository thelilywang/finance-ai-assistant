"""手動觸發更新：抓取財報/新聞並匯入 pgvector。

用法：
    python -m src.update report --market us --company AAPL [--form 10-Q]
    python -m src.update report --market tw --company 2330
    python -m src.update news --company 2330 --limit 10
    python -m src.update market-news [--limit 10]
    python -m src.update inventory [--doc-type news] [--company 2330]   # 唯讀盤點，不改資料
    python -m src.update prune --days 180

美股財報與台股一樣走雙軌：SEC XBRL API 拿結構化數字、SEC EDGAR 拿申報全文的
文字敘述，兩軌各自獨立入庫，靠檢索時相似度搜尋重聚。
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html as html_lib
import logging
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache

import requests
import trafilatura

from . import config
from .ingest import ingest_file, ingest_text
from .logging_setup import log_duration, setup_logging
from .tickers import is_tw_ticker

log = logging.getLogger("update")

TIMEOUT = 30
# 財報全文動輒數萬字；低於此值代表拿到的是節流頁、維護頁或空殼，不是財報
_MIN_FILING_CHARS = 500
# 多個來源（Yahoo RSS、櫃買、MOPS、新聞列表頁）會擋預設的 python-requests UA
BROWSER_UA = {"User-Agent": "Mozilla/5.0"}


@dataclass
class FetchResult:
    """fetch_mops/fetch_edgar 的結構化回傳值，供程式化呼叫端（如未來的 MCP tool）判斷成敗。"""
    ok: bool
    detail: str

# 市場總覽新聞列表頁：{名稱: (列表 URL, 文章連結 regex, 連結 match -> 正規化文章 URL)}
MARKET_SOURCES = {
    "udn_tw": ("https://money.udn.com/money/cate/5590?from=edn_navibar",
               r"/money/story/(\d+)/(\d+)",
               lambda m: f"https://money.udn.com/money/story/{m.group(1)}/{m.group(2)}"),
    "udn_us": ("https://money.udn.com/search/tagging/1001/%E7%BE%8E%E8%82%A1",
               r"/money/story/(\d+)/(\d+)",
               lambda m: f"https://money.udn.com/money/story/{m.group(1)}/{m.group(2)}"),
    "cmoney_tw": ("https://www.cmoney.tw/notes/?navId=twstock",
                  r"note-detail\.aspx\?nid=(\d+)",
                  lambda m: f"https://www.cmoney.tw/notes/note-detail.aspx?nid={m.group(1)}"),
    "cmoney_us": ("https://www.cmoney.tw/notes/?tag=12367",
                   r"note-detail\.aspx\?nid=(\d+)",
                   lambda m: f"https://www.cmoney.tw/notes/note-detail.aspx?nid={m.group(1)}"),
    "cnyes_us": ("https://news.cnyes.com/news/cat/us_stock",
                 r"/news/id/(\d+)",
                 lambda m: f"https://news.cnyes.com/news/id/{m.group(1)}"),
    "cnyes_tw": ("https://news.cnyes.com/news/cat/tw_stock_news",
                 r"/news/id/(\d+)",
                 lambda m: f"https://news.cnyes.com/news/id/{m.group(1)}"),
}

def _market_of_source(name: str) -> str | None:
    """從 MARKET_SOURCES 的 key 取市場別；key 沒標明就回 None（市場不明）。

    市場新聞的 company 是從標題猜的、多半為 NULL，推不出市場；但「這篇是從哪個
    列表頁抓來的」本來就知道，key 的 _tw／_us 尾碼就是答案，不必靠網域或內容猜
    （三個網域都同時供應台股與美股版面，網域推市場必錯）。
    來源本身混合兩市場時不得硬給一個值，回 None 讓它只出現在不限市場的查詢裡。
    """
    suffix = name.rsplit("_", 1)[-1]
    return suffix if suffix in ("tw", "us") else None


# 官方財報 OpenAPI：證交所（上市）與櫃買（上櫃），皆免驗證。
# 每個 dataset 只含「最新一季」全體公司，所以是抓整包再挑出該公司那一列。
# ponytail: 只收一般業（_ci）。金融/金控/保險/證券期貨業（_basi/_fh/_ins/_bd）欄位
# 結構完全不同，各自解析要多寫四套 formatter；上限是查金融股時這軌沒資料、只剩
# PDF 那軌。真要支援再依 co_id 查所屬業別後擴充下面的清單。
TWSE_DATASETS = ("t187ap06_L_ci", "t187ap07_L_ci")                   # 上市：綜合損益表、資產負債表
TPEX_DATASETS = ("mopsfin_t187ap06_O_ci", "mopsfin_t187ap07_O_ci")   # 上櫃：同上
API_SOURCES = (
    ("證交所", "https://openapi.twse.com.tw/v1/opendata/{}", TWSE_DATASETS),
    ("櫃買中心", "https://www.tpex.org.tw/openapi/v1/{}", TPEX_DATASETS),
)

# 證交所用中文欄位名、櫃買用英文欄位名，同樣的資料兩種命名，兩邊都要吃
_CODE_KEYS = ("公司代號", "SecuritiesCompanyCode")
_NAME_KEYS = ("公司名稱", "CompanyName")
_YEAR_KEYS = ("年度", "Year")
_SEASON_KEYS = ("季別", "Season")
# 這些是識別欄位，不是財務數字，格式化時要排除
_META_KEYS = frozenset(_CODE_KEYS + _NAME_KEYS + _YEAR_KEYS + _SEASON_KEYS + ("出表日期", "Date"))

MOPS_MANUAL_GUIDE = """[update] MOPS 抓取失敗（介面脆弱，隨時可能變動）。手動下載步驟：
  1. 開 https://doc.twse.com.tw/server-java/t57sb01 或公開資訊觀測站搜尋公司代號
  2. 下載最新財報 PDF 到 data/
  3. 執行 python -m src.ingest --file data/<檔名>.pdf --company <代號> \\
       --doc-type financial_report --date <YYYY-MM-DD>"""

# SEC XBRL 概念優先序：同一指標各公司採用的標籤不同（AAPL 營收用
# RevenueFromContractWithCustomerExcludingAssessedTax、NVDA 用 Revenues），
# 外國發行人（TSM/ASML）整包走 ifrs-full 且 us-gaap 為空，故兩套並列，依序試到取得為止。
SEC_CONCEPTS = (
    ("營業收入", ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                  "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenue")),
    ("淨利", ("NetIncomeLoss", "ProfitLoss")),
    ("每股盈餘（稀釋）", ("EarningsPerShareDiluted", "DilutedEarningsLossPerShare")),
    ("每股盈餘（基本）", ("EarningsPerShareBasic", "BasicEarningsLossPerShare")),
    ("營業利益", ("OperatingIncomeLoss", "ProfitLossFromOperatingActivities")),
    ("毛利", ("GrossProfit",)),
    ("營業費用", ("OperatingExpenses", "OperatingExpense")),
    ("研發費用", ("ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseIfrs")),
    ("所得稅費用", ("IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations")),
    ("資產總額", ("Assets",)),
    ("負債總額", ("Liabilities",)),
    ("股東權益總額", ("StockholdersEquity", "Equity")),
    ("現金及約當現金", ("CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents")),
    ("營運現金流", ("NetCashProvidedByUsedInOperatingActivities",
                    "CashFlowsFromUsedInOperatingActivities")),
)


def _is_period_end(report_date: str, filing_date: str) -> bool:
    """判斷 reportDate 是否為「會計期末」，用來區分財報 6-K 與一般公告 6-K。

    財報 6-K 的 reportDate 是所報導期間的結束日（與申報日不同）；股利、董事會、
    AGM 這類公告則把當天當 reportDate。兩道條件：

    1. 距月底 7 天內 —— ASML 採 52/53 週制，期末落在 06-28、03-29 這種接近月底
       但非月底的日子。
    2. 落在季末月份（3/6/9/12）—— TSM 每月申報月營收，reportDate 是月底，過不了
       第 1 關；只有季末月份才是財報。
    """
    if not report_date or report_date == filing_date:
        return False
    try:
        d = dt.date.fromisoformat(report_date)
    except ValueError:
        return False
    next_month = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return (next_month - d).days <= 7 and d.month % 3 == 0


def _select_filing(recent: dict, forms: tuple[str, ...]) -> tuple[str, int] | None:
    """依 forms 的優先順序選出一筆申報，回傳 (表單類型, 索引)；查無則 None。

    recent 是 EDGAR 的欄位導向結構（各欄位為等長平行陣列，反時序排列），
    所以任一欄位的索引可直接套用到其他欄位。6-K 涵蓋外國發行人的任何重大公告，
    只收 reportDate 為期末者；其餘表單維持取最新一份。
    """
    for form in forms:
        for idx, f in enumerate(recent["form"]):
            if f != form:
                continue
            if form == "6-K" and not _is_period_end(
                recent["reportDate"][idx], recent["filingDate"][idx]
            ):
                continue
            return form, idx
    return None


def _select_exhibit(items: list[dict], primary_doc: str) -> str:
    """從申報目錄挑出真正含財報的文件。

    6-K 的 primaryDocument 只是封面頁（抽出來約 1~2 千字元的地址與表頭），
    財報本文放在同一份申報的 exhibit。挑最大的 .htm 在 ASML/TSM/NIO 都命中本文。
    ponytail: 「取最大的 htm」是啟發式，上限是可能誤挑到投影片；真的誤挑再改善。
    注意：優先選 EX-99.1 類型標籤不是可靠的升級路徑——實測 ASML 樣本 EX-99.1 是
    新聞稿、EX-99.2 才是投影片、真正財報本文是 EX-99.4，且 index.htm 表格無
    description 欄位可供關鍵字過濾。真要改善應解析 index.htm 表格本身的 size
    欄位（而非 index.json 的 size），此表格才同時帶有 Type 可交叉比對。
    """
    candidates = [
        it for it in items
        if it["name"].endswith(".htm")
        and it["name"] != primary_doc
        and "-index" not in it["name"]
    ]
    if not candidates:
        return primary_doc
    return max(candidates, key=lambda it: int(it.get("size") or 0))["name"]


@lru_cache(maxsize=1)
def _company_tickers() -> dict:
    """SEC 的 ticker→CIK 對照表約 800KB，且一天內不會變；同一次執行只抓一次。

    新增數字軌（fetch_sec_financials）後同一支美股會被抓兩次，這筆重複流量是
    本次改動造成的，故一併收掉；只做 lru_cache，不引入 Session/retry，那些牽涉
    重試策略與 SEC 速率限制，是獨立提案。
    """
    resp = requests.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers={"User-Agent": config.SEC_USER_AGENT}, timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_edgar(ticker: str, form: str = "10-Q") -> FetchResult:
    """從 SEC EDGAR 抓一份財報，抽純文字後匯入。

    依 10-Q/10-K/6-K/20-F/424B4/S-1 的順序 fallback。6-K 另做兩道處理：只收
    reportDate 為期末的財報 6-K，並改抓 exhibit 而非只是封面頁的主文。
    """
    headers = {"User-Agent": config.SEC_USER_AGENT}

    try:
        return _fetch_edgar(ticker, form, headers)
    except requests.RequestException as e:
        # 與其餘抓取器一致：抓取失敗回 FetchResult 而非拋錯，CLI 才印得出可讀訊息。
        # ingest_text 不在此範圍內（見 fetch_mops 的同一原則），DB 失敗仍往上拋
        msg = f"SEC EDGAR 取得失敗：{e}"
        log.warning(msg, extra={"fields": {
            "company": ticker, "source": "edgar", "reason": "http_error", "error": str(e)}})
        return FetchResult(False, msg)


def _fetch_edgar(ticker: str, form: str, headers: dict) -> FetchResult:
    """fetch_edgar 的實作本體；網路錯誤由呼叫端統一收斂。"""
    entry = next(
        (v for v in _company_tickers().values() if v["ticker"].upper() == ticker.upper()), None
    )
    if entry is None:
        msg = f"找不到 ticker {ticker} 對應的 CIK。"
        log.warning(msg, extra={"fields": {
            "company": ticker, "source": "edgar", "reason": "no_cik"}})
        return FetchResult(False, msg)
    cik = entry["cik_str"]

    resp = requests.get(
        f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=headers, timeout=TIMEOUT
    )
    resp.raise_for_status()
    recent = resp.json()["filings"]["recent"]
    # ponytail: 外國發行人（如 ASML/TSM）不申報 10-Q/10-K，季報走 6-K、年報走 20-F；
    # 新上市公司退回 424B4/S-1 招股書。
    forms = (form, "10-K", "6-K", "20-F", "424B4", "S-1")
    selected = _select_filing(recent, forms)
    if selected is None:
        msg = f"{ticker} 近期沒有 {'/'.join(dict.fromkeys(forms))} 申報。"
        log.warning(msg, extra={"fields": {
            "company": ticker, "source": "edgar", "reason": "no_filing"}})
        return FetchResult(False, msg)
    form, idx = selected

    accession = recent["accessionNumber"][idx]
    filing_date = recent["filingDate"][idx]
    primary_doc = recent["primaryDocument"][idx]
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}"

    doc = primary_doc
    cover_only_reason = None
    if form == "6-K":
        # 6-K 的主文只是封面頁（地址、表頭、簽名，無財務數字），財報在 exhibit。
        # 目錄讀不到時仍退回主文以取得部分內容，但要記下原因往上報：
        # 封面頁能通過 _MIN_FILING_CHARS 檢查，靜默當成功會讓「只有封面頁」的申報
        # 混進向量庫且看起來一切正常（ASML 2026 Q2 就是這樣只入庫 2,923 字元）
        try:
            listing = requests.get(f"{base}/index.json", headers=headers, timeout=TIMEOUT)
            listing.raise_for_status()
            doc = _select_exhibit(listing.json()["directory"]["item"], primary_doc)
        except (requests.RequestException, KeyError, ValueError) as e:
            cover_only_reason = f"{type(e).__name__}: {e}"
            log.warning(
                "讀取 6-K 申報目錄失敗，退回主文；主文通常只有封面頁，本次匯入可能缺漏財報本文",
                extra={"fields": {
                    "company": ticker.upper(), "source": "edgar", "reason": "cover_only",
                    "accession": accession, "primary_doc": primary_doc,
                    "error": cover_only_reason}})

    url = f"{base}/{doc}"
    log.info("下載 EDGAR 文件", extra={"fields": {
        "company": ticker.upper(), "source": "edgar", "form": form, "url": url}})
    resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()

    parse_started = time.monotonic()
    text = trafilatura.extract(resp.text)
    if not text:
        # ponytail: trafilatura 抽不到就整包去 tag 粗抽 + 解 HTML entities（€ 等符號），財報 HTML 幾乎都抽得到
        text = html_lib.unescape(re.sub(r"<[^>]+>", " ", resp.text))
    log_duration(log, "EDGAR 解析完成", parse_started, company=ticker.upper(),
                 source="edgar", chars=len(text))

    # SEC 節流頁與維護頁都是 HTTP 200，raise_for_status 攔不住；不檢查會把那一句
    # 警告文字當成財報寫進向量庫並回報成功，靜默污染檢索結果。財報全文遠長於此
    if len(text.strip()) < _MIN_FILING_CHARS or "Undeclared Automated Tool" in text:
        msg = f"{ticker.upper()} 的 {form} 內容異常（僅 {len(text.strip())} 字，可能是節流或維護頁）。"
        log.warning(msg, extra={"fields": {
            "company": ticker, "source": "edgar", "reason": "no_content"}})
        return FetchResult(False, msg)

    ingest_text(
        text,
        source=f"EDGAR:{ticker.upper()}:{accession}",
        company=ticker.upper(),
        doc_type="financial_report",
        published_at=filing_date,
    )
    if cover_only_reason:
        # 內容已入庫（有總比沒有好，且 source 相同、之後重抓會覆蓋），但不回報成功：
        # 呼叫端據此決定要不要重試或提示使用者，不會誤以為拿到了完整財報
        return FetchResult(
            False,
            f"{ticker.upper()} {form}（{filing_date}）僅取得封面頁，可能缺漏本文："
            f"申報 {accession} 目錄讀取失敗（{cover_only_reason}）。已匯入 {len(text.strip())} 字元，"
            f"請稍後重抓。",
        )
    return FetchResult(True, f"已匯入 {ticker.upper()} {form}（{filing_date}）")


def _period_label(row: dict) -> str:
    """把一筆事實的期間轉成人看得懂的標示：期間數字寫「起~迄」，時點數字只寫日期。"""
    start, end = row.get("start"), row.get("end", "")
    return f"{start}~{end}" if start else end


def _pick_fact(concept_units: dict, accession: str) -> tuple[float, str, bool, str] | None:
    """從單一概念的 units dict 選出對應這份申報的那一筆數字。

    回傳 (值, 幣別/單位, 是否命中該 accession, 該數字實際所屬期間)。第三個值讓呼叫端
    能區分「正好是這份申報的數字」與「退而求其次的舊數字」——AAPL 早已停用 Revenues
    （最新只到 2018 年），若不區分就會拿 2018 年的 62.9B 當本季營收，比正確值差了八年。
    第四個值供標示期間：外國發行人的 companyfacts 可能落後好幾期（TSM 2026 年的 6-K
    在 XBRL 只查得到 2024 年報數字），不標期間會讓 LLM 把舊年報當成最新一季引用。

    TSM 同時以 TWD、USD 申報同一指標，優先取 USD 給 LLM 讀比較不會誤判量級；
    companyfacts 常落後最新申報（TSM 最新 20-F 一筆事實都沒有），accession 對不到
    時退回該幣別中 filed 最新的一批，而非直接放棄。同一 accession 常回多列
    （年初至今 vs 當季，如 AAPL 一次回三列），取 start 最晚的那列＝當季數字；
    start 缺漏（資產負債表這類時點數字）則直接取。
    """
    # 幣別鍵在金額是 "USD"、每股盈餘卻是 "USD/shares"，用前綴比對才不會漏掉 EPS——
    # 只比對 "USD" 會讓 TSM 的 EPS 取到 TWD/shares 的 44.67 而非 USD/shares 的 1.36
    unit_name = next(
        (u for u in concept_units if u == "USD" or u.startswith("USD/")),
        next(iter(concept_units), None),
    )
    if unit_name is None:
        return None
    units = concept_units[unit_name]
    if not units:
        return None

    rows = [r for r in units if r.get("accn") == accession]
    exact = bool(rows)
    if not rows:
        latest_filed = max((r["filed"] for r in units), default=None)
        rows = [r for r in units if r["filed"] == latest_filed]
    if not rows:
        return None

    # 先比期末日再比起始日：同一份申報會同時含本期與比較期（資產負債表這類時點數字
    # 沒有 start，AAPL 一次列出 2024-09-28 到 2026-06-27 共六期權益數），只看 start
    # 會在時點數字間任意挑一期，選到兩年前的舊值。期末日相同時取 start 較晚者＝
    # 期間較短者，即當季而非年初至今。
    row = max(rows, key=lambda r: (r.get("end") or "", r.get("start") or ""))
    return row["val"], unit_name, exact, _period_label(row)


def _format_xbrl(facts: dict, taxonomy: str, accession: str, ticker: str, label: str) -> str | None:
    """把 SEC XBRL 概念數字轉成可 embedding 的中文文字，風格比照 _format_rows。

    金額單位必須明寫——同一坑台股那軌踩過（_format_rows 的註解）：原始值不標單位
    會被 LLM 讀成別的量級。SEC 的值是「元」而非仟元，EPS 是每股金額，兩者分開標；
    幣別非 USD 時（TSM 的 TWD）務必寫出幣別，否則 49.33 會被當成美元讀。

    非本次申報當期的數字「直接不寫入」，而不是寫出來再加警語。警語擋不住 LLM：
    TSM 2026Q2 實測中，這一塊是全庫唯一「長得像財報摘要」的乾淨數字清單（同申報的
    EDGAR 全文散成 371 塊會計附註碎片），相似度排序穩定把它排在最前面，模型照引了
    裡面的 2024 年報數字——即使開頭就寫明非當期、每條都標了期間。

    逐條濾而非整份丟：JPM 實測是混合期，13 條裡 11 條正好是當期，只有營業收入落後
    一年、現金及約當現金落後八年（2018-12-31，即 _pick_fact docstring 警告的停用概念
    型失分）。整份丟會讓 JPM 與 SPCX 完全沒有財報數字——這兩家的 EDGAR 全文塊數是 0，
    沒有另一軌接得住。全部落後時回 None，由呼叫端走既有的「無可用數字」不入庫路徑。

    每條留下的數字仍標所屬期間：同一份申報會同時含本期與比較期，不標期間會讓
    比較期數字被當成最新一季。
    """
    taxonomy_facts = facts.get(taxonomy, {})
    lines = []
    dropped = []
    for name, concepts in SEC_CONCEPTS:
        # 先掃過整串概念找「正好屬於這份申報」的，找不到才退回第一個有值的舊數字。
        # 不能取第一個有值的就停：AAPL 的 Revenues 停用於 2018 年但仍排在清單首位，
        # 直接採用會拿 2018 年的數字當本季營收，而正確值在後面的
        # RevenueFromContractWithCustomerExcludingAssessedTax。
        fallback = None
        for concept in concepts:
            concept_data = taxonomy_facts.get(concept)
            if not concept_data:
                continue
            picked = _pick_fact(concept_data.get("units", {}), accession)
            if picked is None:
                continue
            if picked[2]:
                fallback = picked
                break
            fallback = fallback or picked
        if fallback is None:
            continue
        val, unit, exact, period = fallback
        if not exact:
            # 非本次申報當期就整條不寫。留著只會多一個陷阱，該指標本季的值由
            # EDGAR 全文那軌（有的話）提供
            dropped.append(name)
            continue
        # 幣別一律照實寫出，不可簡化成「元」——TSM 以 TWD 與 USD 雙幣別申報，
        # 44.67 TWD/股寫成「元/股」會被 LLM 當成美元讀，量級差 30 倍以上
        unit_label = f"{unit.split('/')[0]}/股" if "每股盈餘" in name else unit
        # 每個數字仍標自己的期間：同一份申報含本期與比較期，_pick_fact 取的是期末
        # 最晚那期，標出來才能讓 LLM 確認是否為它要的期間
        lines.append(f"{name}：{_fmt_amount(val)}（{unit_label}，期間 {period}）")
    if not lines:
        return None
    header = f"{ticker.upper()} {label}（資料來源：SEC XBRL API，申報編號 {accession}）"
    if dropped:
        # 明講少了哪些指標，免得 LLM 把「沒列出」讀成「該指標為零」
        header += (
            f"\n注意：SEC 結構化資料尚未涵蓋本次申報的下列指標，已略去不列："
            f"{'、'.join(dropped)}。"
        )
    return header + "\n" + "\n".join(lines)


def fetch_sec_financials(ticker: str) -> FetchResult:
    """從 SEC XBRL API 抓結構化財報數字並匯入。

    與 fetch_edgar 是互補的兩軌：本函式拿 XBRL 精準數字，fetch_edgar 拿申報全文的
    文字敘述。任一軌失敗不影響另一軌，比照台股 fetch_tw_financials / fetch_mops。
    """
    headers = {"User-Agent": config.SEC_USER_AGENT}
    try:
        return _fetch_sec_financials(ticker, headers)
    except requests.RequestException as e:
        msg = f"SEC XBRL 取得失敗：{e}"
        log.warning(msg, extra={"fields": {
            "company": ticker, "source": "sec_xbrl", "reason": "http_error", "error": str(e)}})
        return FetchResult(False, msg)


def _fetch_sec_financials(ticker: str, headers: dict) -> FetchResult:
    """fetch_sec_financials 的實作本體；網路錯誤由呼叫端統一收斂。"""
    entry = next(
        (v for v in _company_tickers().values() if v["ticker"].upper() == ticker.upper()), None
    )
    if entry is None:
        msg = f"找不到 ticker {ticker} 對應的 CIK。"
        log.warning(msg, extra={"fields": {
            "company": ticker, "source": "sec_xbrl", "reason": "no_cik"}})
        return FetchResult(False, msg)
    cik = entry["cik_str"]

    resp = requests.get(
        f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=headers, timeout=TIMEOUT
    )
    resp.raise_for_status()
    recent = resp.json()["filings"]["recent"]
    # 與 fetch_edgar 用同一套表單優先序與期末判定，確保兩軌指向同一份申報
    forms = ("10-Q", "10-K", "6-K", "20-F", "424B4", "S-1")
    selected = _select_filing(recent, forms)
    if selected is None:
        msg = f"{ticker} 近期沒有 {'/'.join(dict.fromkeys(forms))} 申報。"
        log.warning(msg, extra={"fields": {
            "company": ticker, "source": "sec_xbrl", "reason": "no_filing"}})
        return FetchResult(False, msg)
    form, idx = selected
    accession = recent["accessionNumber"][idx]
    filing_date = recent["filingDate"][idx]

    resp = requests.get(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
        headers=headers, timeout=TIMEOUT,
    )
    resp.raise_for_status()
    facts = resp.json().get("facts", {})
    # 外國發行人（TSM/ASML）整包走 ifrs-full，us-gaap 概念數為 0
    taxonomy = "us-gaap" if facts.get("us-gaap") else "ifrs-full"

    # _format_xbrl 已逐條濾掉非本次申報當期的數字，全部落後時回 None 落在這裡
    text = _format_xbrl(facts, taxonomy, accession, ticker, f"{form}（{filing_date}）")
    if text is None:
        msg = (f"{ticker.upper()} 的 XBRL 無本次申報（{accession}）當期數字"
               f"（{taxonomy} 概念皆缺漏或落後），略過不入庫；"
               f"財報全文仍由 EDGAR 那軌提供。")
        log.warning(msg, extra={"fields": {
            "company": ticker, "source": "sec_xbrl", "reason": "xbrl_empty",
            "accession": accession}})
        return FetchResult(False, msg)

    ingest_text(
        text,
        source=f"SEC-XBRL:{ticker.upper()}:{accession}",
        company=ticker.upper(),
        doc_type="financial_report",
        published_at=filing_date,
    )
    return FetchResult(True, f"已匯入 {ticker.upper()} {form} XBRL 財報數字（{filing_date}）")


def _select_report_file(files: list[str]) -> str | None:
    """從 MOPS 回傳的財報檔名中選出最新月份的中文主文，退而求其次選同月份的英文版。

    檔名格式為 YYYYMM_公司代號_類型.pdf，同月份常見 _AI1（中文合併財報）與
    _AIA（英文版）兩份；字典序排序 'AIA' > 'AI1'，若用 sorted(files)[-1] 會固定選到
    英文版，因此改用明確規則優先抓最新月份的中文主文。
    """
    if not files:
        return None
    files = sorted(set(files))
    latest_month = files[-1][:6]
    month_files = [f for f in files if f.startswith(latest_month)]
    zh_main = [f for f in month_files if f.endswith("_AI1.pdf")]
    return zh_main[0] if zh_main else month_files[-1]


def _pick(row: dict, keys: tuple[str, ...]) -> str | None:
    """從 row 取出第一個存在的鍵值，用來吃證交所中文鍵／櫃買英文鍵兩種命名。"""
    for k in keys:
        if row.get(k):
            return str(row[k]).strip()
    return None


def _find_company_row(rows: list[dict], co_id: str) -> dict | None:
    """從整包資料中找出該公司那一列；查無回 None。"""
    for row in rows:
        if _pick(row, _CODE_KEYS) == co_id:
            return row
    return None


def _quarter_end_date(year: str, season: str) -> str | None:
    """民國年度 + 季別推出「季末次月一日」作為發布日期。115 年第 2 季 → 2026-08-01。

    財報實際公告日在季末後一至兩個月，取次月一日只是要一個穩定、單調遞增且不早於
    期末的日期，供檢索時的時間排序用，不是精確公告日。
    """
    try:
        ad_year = int(year) + 1911
        month = int(season) * 3 + 1  # Q1→4月, Q2→7月... 再加一個月的緩衝
    except (TypeError, ValueError):
        return None
    if not 1 <= int(season) <= 4:
        return None
    month += 1
    if month > 12:  # Q4 → 隔年 2 月
        ad_year, month = ad_year + 1, month - 12
    return f"{ad_year}-{month:02d}-01"


def _fmt_amount(value: object) -> str:
    """數字加千分位便於閱讀；非數字原樣輸出。"""
    text = str(value).strip()
    try:
        num = float(text)
    except ValueError:
        return text
    return f"{num:,.2f}".rstrip("0").rstrip(".") if "." in text else f"{int(num):,}"


def _format_rows(rows: list[dict], co_id: str) -> tuple[str, str, str] | None:
    """把各報表的數字列轉成可 embedding 的中文文字。

    回傳 (文字, published_at, 年度季別標籤)；沒有任何有效資料時回 None。
    金額單位為仟元，必須明寫——原始值如 2404483690 不標單位會被 LLM 讀成元。
    """
    blocks: list[str] = []
    published_at = label = None
    for title, row in rows:
        name = _pick(row, _NAME_KEYS) or co_id
        year = _pick(row, _YEAR_KEYS)
        season = _pick(row, _SEASON_KEYS)
        if not (year and season):
            continue
        published_at = published_at or _quarter_end_date(year, season)
        label = label or f"{year}Q{season}"

        # 空字串欄位（如生物資產類科目）大多數公司不適用，略過以免灌入無意義的雜訊
        lines = [
            f"{k}：{_fmt_amount(v)}"
            for k, v in row.items()
            if k not in _META_KEYS and str(v).strip()
        ]
        if not lines:
            continue
        # EPS 行離標題約 20 行，LLM 讀到那行時早已忘了累計期間，所以期間要寫進該行本身
        if title == "綜合損益表" and int(season) > 1:
            cum = f"1～{int(season) * 3} 月累計"
            lines = [
                ln.replace("（元）：", f"（元，{cum}）：", 1) if "每股盈餘" in ln.split("：")[0] else ln
                for ln in lines
            ]
        # 綜合損益表是年初至當季累計（Q2 = 1～6 月）：把累計期間放最前面（上半年／前三季／全年），
        # LLM 才不會丟掉括號而把累計 EPS 讀成單季；資產負債表是時點數，維持「第 N 季」
        period = f"第 {season} 季"
        if title == "綜合損益表":
            period = {
                "1": "第 1 季（1～3 月）",
                "2": "上半年（1～6 月累計，第 2 季財報）",
                "3": "前三季（1～9 月累計，第 3 季財報）",
                "4": "全年（1～12 月累計，第 4 季財報）",
            }[str(int(season))]
        blocks.append(
            f"{name}（{co_id}）{year} 年{period} {title}"
            f"（單位：仟元，每股盈餘為元；資料來源：公開資訊觀測站 OpenAPI）\n"
            + "\n".join(lines)
        )
    if not blocks or not published_at:
        return None
    return "\n\n".join(blocks), published_at, label


def fetch_tw_financials(co_id: str) -> FetchResult:
    """從官方 OpenAPI 抓結構化財報數字並匯入（上市走證交所、上櫃走櫃買）。

    與 fetch_mops 是互補的兩軌：本函式拿精準數字，fetch_mops 拿 PDF 的文字敘述
    （管理層討論、風險、展望）。任一軌失敗不影響另一軌。
    """
    # try 只包外部抓取，不包 ingest_text：DB/embedding 失敗不是抓取失敗，
    # 讓它往上拋（與 fetch_mops 同一原則）。resp.json() 的解析失敗會拋
    # requests.JSONDecodeError，它本身是 RequestException 的子類，已被涵蓋。
    reachable = False
    for source_name, url_tpl, datasets in API_SOURCES:
        try:
            found = []
            for dataset in datasets:
                resp = requests.get(url_tpl.format(dataset), headers=BROWSER_UA, timeout=TIMEOUT)
                resp.raise_for_status()
                row = _find_company_row(resp.json(), co_id)
                if row:
                    # 損益表在前、資產負債表在後，依 datasets 順序自然成立
                    title = "綜合損益表" if "ap06" in dataset else "資產負債表"
                    found.append((title, row))
        except requests.RequestException as e:
            # 單一市場的端點掛掉不影響另一個市場，繼續試下一個
            log.warning(f"{source_name} OpenAPI 取得失敗（{e}），略過。", extra={"fields": {
                "company": co_id, "source": source_name, "reason": "api_down", "error": str(e)}})
            continue
        reachable = True
        if not found:
            continue  # 這個市場查無此公司，換下一個市場

        formatted = _format_rows(found, co_id)
        if formatted is None:
            msg = f"{source_name} OpenAPI 查到 {co_id} 但欄位無法解析（格式可能已變動）。"
            log.warning(msg, extra={"fields": {
                "company": co_id, "source": source_name, "reason": "api_miss"}})
            return FetchResult(False, msg)
        text, published_at, label = formatted
        ingest_text(
            text,
            source=f"TWSE-API:{co_id}:{label}",  # 帶年度季別，換季不覆蓋舊季
            company=co_id,
            doc_type="financial_report",
            published_at=published_at,
        )
        return FetchResult(True, f"已匯入 {co_id} {label} 財報數字（{source_name} OpenAPI）")

    # 區分「連得上但沒這家公司」與「兩邊端點都掛了」，後者訊息若寫成查無公司會誤導排查方向
    msg = (
        f"官方 OpenAPI 查無 {co_id}（可能為興櫃、金融業或已下市）。" if reachable
        else "官方 OpenAPI 兩個來源皆無法取得（端點或網路異常）。"
    )
    log.warning(msg, extra={"fields": {
        "company": co_id, "source": "twse_api", "reason": "api_miss" if reachable else "api_down"}})
    return FetchResult(False, msg)


def fetch_mops(co_id: str) -> FetchResult:
    """從 MOPS（公開資訊觀測站）抓最新財報 PDF 並匯入。

    與 fetch_tw_financials 互補：本函式拿 PDF 的文字敘述（管理層討論、風險、業務
    展望），數字則由官方 OpenAPI 那軌負責。MOPS 無官方 API，此爬取流程依賴網站
    當前頁面結構、隨時可能失效；掛掉時印手動下載指引並回傳失敗，不 raise。
    """
    try:
        download_started = time.monotonic()
        endpoint = "https://doc.twse.com.tw/server-java/t57sb01"
        filename = None
        for year in (dt.date.today().year - 1911, dt.date.today().year - 1912):
            resp = requests.post(
                endpoint,
                data={
                    "id": "", "key": "", "step": "1", "co_id": co_id, "year": str(year),
                    "seamon": "", "mtype": "A", "encodeURIComponent": "1", "firstin": "true",
                },
                headers=BROWSER_UA,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            files = re.findall(r"(\d{6}_%s_\w+\.pdf)" % re.escape(co_id), resp.text)
            filename = _select_report_file(files)
            if filename:
                break
        if not filename:
            msg = f"MOPS 查無 {co_id} 的財報檔案。"
            log.warning(msg, extra={"fields": {
                "company": co_id, "source": "mops", "reason": "mops_blocked"}})
            print(MOPS_MANUAL_GUIDE)
            return FetchResult(False, msg)
        if not filename.endswith("_AI1.pdf"):
            # 中文主文缺席才會退而求其次選到這份，主動告警而非靜默接受降級結果
            log.warning("查無中文主文，改抓替代檔案", extra={"fields": {
                "company": co_id, "source": "mops", "reason": "no_chinese_doc",
                "filename": filename}})

        resp = requests.post(
            endpoint,
            data={"step": "9", "kind": "A", "co_id": co_id, "filename": filename},
            headers=BROWSER_UA,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        m = re.search(r"href=['\"](/pdf/[^'\"]+)['\"]", resp.text)
        if not m:
            msg = f"MOPS 第二步找不到 PDF 連結（{filename}）。"
            log.warning(msg, extra={"fields": {
                "company": co_id, "source": "mops", "reason": "mops_blocked"}})
            print(MOPS_MANUAL_GUIDE)
            return FetchResult(False, msg)

        resp = requests.get(
            f"https://doc.twse.com.tw{m.group(1)}", headers=BROWSER_UA, timeout=TIMEOUT
        )
        resp.raise_for_status()
        # 端點改版時第三步可能回錯誤頁 HTML；不檢查會寫成 .pdf 再由 pypdf 拋錯，
        # 錯誤訊息指向 pypdf 而非真正的失敗點 MOPS
        if not resp.content.startswith(b"%PDF"):
            msg = f"MOPS 回傳的不是 PDF（{filename}，可能是錯誤頁）。"
            log.warning(msg, extra={"fields": {
                "company": co_id, "source": "mops", "reason": "mops_blocked"}})
            print(MOPS_MANUAL_GUIDE)
            return FetchResult(False, msg)
        path = f"data/{filename}"
        with open(path, "wb") as f:
            f.write(resp.content)
        log.info("MOPS 下載完成", extra={"fields": {
            "company": co_id, "source": "mops", "bytes": len(resp.content),
            "elapsed_ms": round((time.monotonic() - download_started) * 1000)}})

        # 檔名開頭為西元 YYYYMM（如 202601_2330_AI1.pdf），推出發布日期
        published_at = f"{filename[:4]}-{filename[4:6]}-01"
        ingest_file(path, company=co_id, doc_type="financial_report", published_at=published_at)
        return FetchResult(True, f"已匯入 {co_id} 財報（{filename}）")
    except (requests.RequestException, OSError) as e:
        # 只收「抓取／寫檔」這段的失敗。ingest_file 內的 DB 或 embedding 失敗不是
        # MOPS 的錯，讓它往上拋給 graph.py 的 handler，不要誤報成 MOPS 抓取異常、
        # 也不要印一份無關的手動下載指引
        log.warning(f"MOPS 抓取異常：{e}", extra={"fields": {
            "company": co_id, "source": "mops", "reason": "mops_blocked", "error": str(e)}})
        print(MOPS_MANUAL_GUIDE)
        return FetchResult(False, f"MOPS 抓取異常：{e}")


def fetch_news(company: str, limit: int = 10) -> FetchResult:
    """從 Yahoo Finance RSS 抓最新新聞並匯入；RSS 空手時（台股中小型股常見）改走
    台股個股頁 fetch_tw_stock_news 補。台股代號自動加 .TW。"""
    from .vectorstore import source_exists

    symbol = f"{company}.TW" if is_tw_ticker(company) else company
    url = (
        "https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={symbol}&region=US&lang=en-US"
    )
    # Yahoo 會擋預設的 python-requests User-Agent，帶瀏覽器 UA
    resp = requests.get(url, headers=BROWSER_UA, timeout=TIMEOUT)
    if resp.status_code != 200:
        msg = f"Yahoo RSS 取得失敗（HTTP {resp.status_code}），稍後再試。"
        log.warning(msg, extra={"fields": {
            "company": company, "source": "yahoo_rss", "reason": "http_error"}})
        return FetchResult(False, msg)

    items = ET.fromstring(resp.content).findall(".//item")[:limit]
    if not items:
        # Yahoo RSS 台股覆蓋只到大型股（實測 3049/2380/3025 一律回 0 篇），
        # 個股頁則有 20 篇且跨代號不重疊。兩者同母站不同端點，互補而非替代，
        # 故只在空手時才付這個額外請求的成本，不無條件都打。
        if is_tw_ticker(company):
            return fetch_tw_stock_news(company, limit=limit)
        msg = f"{symbol} 的 RSS 沒有新聞。"
        log.warning(msg, extra={"fields": {
            "company": company, "source": "yahoo_rss", "reason": "no_content"}})
        return FetchResult(False, msg)

    total = 0
    skipped = 0
    for item in items:
        try:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            if source_exists(link):
                skipped += 1
                continue
            pub_date = item.findtext("pubDate", "").strip()
            published_at = None
            if pub_date:
                published_at = email.utils.parsedate_to_datetime(pub_date).date().isoformat()

            html = trafilatura.fetch_url(link)
            body = trafilatura.extract(html) if html else None
            # 抽不到內文就只 ingest 標題，聊勝於無
            text = f"{title}\n\n{body}" if body else title
            total += ingest_text(
                text, source=link, company=company, doc_type="news", published_at=published_at,
                title=title,
            )
        except (requests.RequestException, OSError, ValueError) as e:
            # 單篇文章的下載或解析失敗就跳過。DB/embedding 失敗不會落在這裡，
            # 會往上拋——那是系統性問題，逐篇印錯再回報「寫入 0 筆」等於靜默失敗
            log.warning(f"新聞處理失敗（{link}）：{e}", extra={"fields": {
                "company": company, "source": "yahoo_rss", "reason": "news_failed",
                "error": str(e)}})
    ok = total > 0 or skipped > 0
    # 全部來源都失敗時不能說「更新完成」：LLM 只讀得到 detail，看到「完成」就不會改走其他路
    msg = (f"新聞更新完成，共寫入 {total} 筆 chunk，跳過 {skipped} 篇已入庫。" if ok
           else "新聞抓取失敗：沒有取得任何文章（來源無回應、改版或內文抽取失敗）。")
    log.info(msg, extra={"fields": {
        "company": company, "source": "yahoo_rss", "chunks": total, "skipped": skipped}})
    return FetchResult(ok, msg)


def fetch_tw_stock_news(company: str, limit: int = 10) -> FetchResult:
    """從 Yahoo 台股個股頁抓新聞並匯入，補 Yahoo RSS 對台股中小型股的覆蓋缺口。

    與 fetch_news 同母站（tw.stock.yahoo.com）不同端點：RSS 走
    feeds.finance.yahoo.com（美股導向），個股頁是台股在地內容。
    實測 3049/2380/3025 三檔在 RSS 一律 0 篇，個股頁穩定 20 篇且互不重疊，
    故只作為 fetch_news 的 fallback，不取代它。
    """
    from .vectorstore import source_exists

    url = f"https://tw.stock.yahoo.com/quote/{company}.TW/news"
    resp = requests.get(url, headers=BROWSER_UA, timeout=TIMEOUT)
    if resp.status_code != 200:
        msg = f"Yahoo 台股個股頁取得失敗（HTTP {resp.status_code}），稍後再試。"
        log.warning(msg, extra={"fields": {
            "company": company, "source": "yahoo_tw_stock", "reason": "http_error"}})
        return FetchResult(False, msg)

    # 保序去重，同 fetch_market_news 的手法
    links = list(dict.fromkeys(
        re.findall(r'"(https://tw\.stock\.yahoo\.com/news/[^"?]+\.html)"', resp.text)
    ))[:limit]
    if not links:
        msg = f"{company} 的個股頁找不到任何新聞連結（版面可能改版）。"
        log.warning(msg, extra={"fields": {
            "company": company, "source": "yahoo_tw_stock", "reason": "no_content"}})
        return FetchResult(False, msg)

    total = 0
    skipped = 0
    for link in links:
        # 中文標題經 URL 編碼可能超過 doc_chunks.source 的 varchar(512)（實測虹光
        # 一篇公告連結編碼後 544 字元），插入會整批失敗；截斷會讓不同長 URL 共用
        # 前綴、騙過 source_exists 去重，故直接跳過整篇，不硬塞。
        if len(link) > 512:
            log.warning(f"個股頁連結超過欄位長度上限，跳過：{link}", extra={"fields": {
                "company": company, "source": "yahoo_tw_stock", "reason": "url_too_long",
                "length": len(link)}})
            continue
        if source_exists(link):
            skipped += 1
            continue
        try:
            html = trafilatura.fetch_url(link)
            if not html:
                log.warning(f"個股頁文章下載失敗：{link}", extra={"fields": {
                    "company": company, "source": "yahoo_tw_stock", "reason": "http_error"}})
                continue
            doc = trafilatura.bare_extraction(html, with_metadata=True)
            if not doc or len(doc.text or "") < 100:
                log.warning(f"個股頁內文過短或抽取失敗：{link}", extra={"fields": {
                    "company": company, "source": "yahoo_tw_stock", "reason": "no_content"}})
                continue
            total += ingest_text(
                doc.text, source=link, company=company, doc_type="news",
                published_at=doc.date, title=doc.title, market="tw",
            )
        except (requests.RequestException, OSError, ValueError) as e:
            # 單篇失敗跳過，DB/embedding 失敗往上拋，同 fetch_news 的例外邊界
            log.warning(f"個股頁文章處理失敗（{link}）：{e}", extra={"fields": {
                "company": company, "source": "yahoo_tw_stock", "reason": "news_failed",
                "error": str(e)}})
    ok = total > 0 or skipped > 0
    # 全部來源都失敗時不能說「更新完成」：LLM 只讀得到 detail，看到「完成」就不會改走其他路
    msg = (f"個股頁新聞更新完成，共寫入 {total} 筆 chunk，跳過 {skipped} 篇已入庫。" if ok
           else "個股頁新聞抓取失敗：沒有取得任何文章（來源無回應、改版或內文抽取失敗）。")
    log.info(msg, extra={"fields": {
        "company": company, "source": "yahoo_tw_stock", "chunks": total, "skipped": skipped}})
    return FetchResult(ok, msg)


def _company_from_title(title: str) -> str | None:
    """標題含「公司名(2330)」時抽出台股代號。# ponytail: 括號內 4 碼即視為代號，誤抓年份的機率低"""
    m = re.search(r"[（(](\d{4})[）)]", title)
    return m.group(1) if m else None


def fetch_market_news(limit_per_source: int = 10) -> FetchResult:
    """掃 MARKET_SOURCES 列表頁，抓新文章入庫。已入庫的 source 直接跳過。"""
    from .vectorstore import source_exists

    total = 0
    skipped = 0
    for name, (listing_url, pattern, normalize) in MARKET_SOURCES.items():
        resp = requests.get(
            listing_url, headers=BROWSER_UA, timeout=TIMEOUT
        )
        if resp.status_code != 200:
            log.warning(f"{name} 列表頁取得失敗（HTTP {resp.status_code}），跳過。", extra={"fields": {
                "source": name, "reason": "http_error"}})
            continue

        urls: list[str] = []
        seen = set()
        for m in re.finditer(pattern, resp.text):
            url = normalize(m)
            if url not in seen:
                seen.add(url)
                urls.append(url)
        if not urls:
            log.warning(f"{name} 找不到任何文章連結（版面可能改版），跳過。", extra={"fields": {
                "source": name, "reason": "http_error"}})
            continue

        for url in urls[:limit_per_source]:
            if source_exists(url):
                skipped += 1
                continue
            try:
                html = trafilatura.fetch_url(url)
                if not html:
                    log.warning(f"{name} 文章下載失敗：{url}", extra={"fields": {
                        "source": name, "reason": "http_error"}})
                    continue
                doc = trafilatura.bare_extraction(html, with_metadata=True)
                if not doc or len(doc.text or "") < 100:
                    log.warning(f"{name} 內文過短或抽取失敗：{url}", extra={"fields": {
                        "source": name, "reason": "no_content"}})
                    continue

                title = (doc.title or "").strip() or None
                published_at = doc.date
                company = _company_from_title(title) if title else None
                text = f"{title}\n\n{doc.text}" if title else doc.text
                total += ingest_text(
                    text, source=url, company=company, doc_type="news",
                    published_at=published_at, title=title,
                    market=_market_of_source(name),
                )
            except (requests.RequestException, OSError, ValueError) as e:
                # 同 fetch_news：單篇失敗跳過，DB/embedding 失敗往上拋
                log.warning(f"{name} 文章處理失敗（{url}）：{e}", extra={"fields": {
                    "source": name, "reason": "news_failed", "error": str(e)}})

    ok = total > 0 or skipped > 0
    # 全部來源都失敗時不能說「更新完成」：LLM 只讀得到 detail，看到「完成」就不會改走其他路
    msg = (f"市場新聞更新完成，共寫入 {total} 筆 chunk，跳過 {skipped} 篇已入庫。" if ok
           else "市場新聞抓取失敗：沒有取得任何文章（來源無回應、改版或內文抽取失敗）。")
    log.info(msg, extra={"fields": {"chunks": total, "skipped": skipped}})
    return FetchResult(ok, msg)


# 財報的軌別：每個市場正常該有「全文」與「數字」兩軌，決定「0 塊」算不算缺口。
# 台股（fetch_tw_financials + fetch_mops）：TWSE-API 數字 + MOPS PDF 全文。
# 美股（2026-09-09 建立的雙軌）：SEC-XBRL 數字 + EDGAR 全文。
# 本地 PDF 的 source 是檔案路徑、沒有共同前綴，故以「非其他三種」歸入 MOPS 全文軌。
_TRACKS = {
    "tw": {"full": "MOPS-PDF", "num": "TWSE-API"},
    "us": {"full": "EDGAR", "num": "SEC-XBRL"},
}
# 不報數字軌屬正常的例外：ASML/TSM 是 F 股，SEC 不收它們的 XBRL，只有 EDGAR 全文。
# 白名單而非「缺數字軌一律放行」——否則 META 那種只剩 1 塊 XBRL 的反例也會被放過。
_NO_NUM_TRACK = {"ASML", "TSM"}


def _track_of(prefix: str, market: str) -> str:
    """把來源前綴歸到 full／num 軌；不屬於該市場任一軌則回空字串。"""
    t = _TRACKS[market]
    if prefix == t["num"]:
        return "num"
    # 台股全文軌是本地 PDF，前綴就是檔案路徑本身
    if market == "tw" and prefix not in ("TWSE-API", "EDGAR", "SEC-XBRL", "https"):
        return "full"
    if prefix == t["full"]:
        return "full"
    return ""


def inventory(doc_type: str | None = None, company: str | None = None) -> bool:
    """盤點庫內來源：列出來源與塊數，並標出軌別缺口（某標的某一軌整個掛零）。

    純讀，不改資料。缺口偵測的由來見維護日誌「待建能力：按來源重跑 ingest」：
    ingest 的低字數警示只在入庫當下觸發，且只看得到進來的那塊，看不到
    「整軌沒進來」——META 那筆就是這樣拖到人工查才發現。
    """
    from .vectorstore import list_sources

    rows = list_sources(doc_type, company)
    if not rows:
        print("[inventory] 查無資料")
        return True

    by_prefix: dict[tuple[str, str], list[int]] = {}
    for r in rows:
        key = (r["prefix"], r["doc_type"])
        acc = by_prefix.setdefault(key, [0, 0])
        acc[0] += 1
        acc[1] += r["chunks"]
    print("依來源前綴：")
    print(f"  {'前綴':<28} {'doc_type':<18} {'來源數':>6} {'塊數':>8}")
    for (prefix, dtype), (n_src, n_chunk) in sorted(
            by_prefix.items(), key=lambda kv: -kv[1][1]):
        print(f"  {prefix:<28} {dtype:<18} {n_src:>6} {n_chunk:>8}")
    print(f"  {'合計':<28} {'':<18} {len(rows):>6} "
          f"{sum(r['chunks'] for r in rows):>8}")

    # 軌別交叉表：只看財報，新聞沒有軌的概念
    tracks: dict[str, dict[str, int]] = {}
    for r in rows:
        if r["doc_type"] != "financial_report" or not r["company"]:
            continue
        co = r["company"]
        market = "tw" if is_tw_ticker(co) else "us"
        # 市場看代號本身，不看「碰巧有哪幾軌」——否則整個市場的軌都掛零時
        # 會被判成「不屬於任何市場」而靜默跳過，正是要偵測的那種情況
        slot = tracks.setdefault(co, {"market": market, "full": 0, "num": 0})
        track = _track_of(r["prefix"], market)
        if track:
            slot[track] += r["chunks"]
    if tracks:
        print("\n財報軌別（每個市場應有全文與數字兩軌）：")
        print(f"  {'company':<10} {'市場':<4} {'全文軌':>8} {'數字軌':>8}  判定")
        gaps = []
        for co in sorted(tracks, key=lambda c: (tracks[c]["market"], c)):
            slot = tracks[co]
            full, num = slot["full"], slot["num"]
            t = _TRACKS[slot["market"]]
            if full == 0:
                verdict = f"缺口：全文軌（{t['full']}）掛零"
                gaps.append(co)
            elif num == 0 and co in _NO_NUM_TRACK:
                verdict = f"僅全文軌（F 股不報 {t['num']}，正常）"
            elif num == 0:
                verdict = f"缺口：數字軌（{t['num']}）掛零"
                gaps.append(co)
            else:
                verdict = "正常"
            print(f"  {co:<10} {slot['market']:<4} {full:>8} {num:>8}  {verdict}")
        if gaps:
            print(f"\n  ⚠ {len(gaps)} 個標的有軌別缺口：{'、'.join(gaps)}")

    stale = [r for r in rows if r["chunk_unit"] is None]
    print(f"\n切法出處：舊塊（chunk_unit 為 NULL）{len(stale)} 源／"
          f"{sum(r['chunks'] for r in stale)} 塊，"
          f"帶值 {len(rows) - len(stale)} 源／"
          f"{sum(r['chunks'] for r in rows if r['chunk_unit'] is not None)} 塊")
    return True


def main() -> None:
    # CLI 進入點也要設定 logging，否則本模組的 log.* 只會落到 stderr，不會寫進
    # data/logs 的 JSON Lines——抓取耗時與失敗原因就無法事後回測。
    setup_logging("update")
    parser = argparse.ArgumentParser(description="抓取財報/新聞並匯入 pgvector")
    sub = parser.add_subparsers(dest="command", required=True)

    p_report = sub.add_parser(
        "report", help="抓財報（us: SEC XBRL + EDGAR 兩軌 / tw: 官方 OpenAPI + MOPS 兩軌）"
    )
    p_report.add_argument("--market", required=True, choices=["tw", "us"])
    p_report.add_argument("--company", required=True, help="美股 ticker 或台股代號")
    p_report.add_argument("--form", default="10-Q", help="美股表單類型，預設 10-Q")

    p_news = sub.add_parser("news", help="抓 Yahoo Finance RSS 新聞")
    p_news.add_argument("--company", required=True, help="美股 ticker 或台股代號")
    p_news.add_argument("--limit", type=int, default=10)

    p_market_news = sub.add_parser("market-news", help="掃市場總覽新聞列表頁（udn/cmoney）")
    p_market_news.add_argument("--limit", type=int, default=10, help="每個來源抓取篇數，預設 10")

    p_inv = sub.add_parser("inventory", help="盤點庫內來源與軌別缺口（唯讀）")
    p_inv.add_argument("--doc-type", default=None,
                       choices=["financial_report", "news"])
    p_inv.add_argument("--company", default=None, help="只看單一標的")

    p_prune = sub.add_parser("prune", help="刪除過期新聞 chunk（財報不刪）")
    p_prune.add_argument("--days", type=int, default=180, help="保留天數，預設 180")

    args = parser.parse_args()
    if args.command == "report":
        if args.market == "us":
            # 兩軌互補：XBRL 拿精準數字、EDGAR 拿申報全文的文字敘述。兩軌都跑，任一軌成功就算成功
            api = fetch_sec_financials(args.company)
            doc = fetch_edgar(args.company, args.form)
            ok = api.ok or doc.ok
        else:
            # 兩軌互補：API 拿數字、MOPS 拿文字敘述。兩軌都跑，任一軌成功就算成功
            api = fetch_tw_financials(args.company)
            pdf = fetch_mops(args.company)
            ok = api.ok or pdf.ok
    elif args.command == "news":
        ok = fetch_news(args.company, args.limit).ok
    elif args.command == "market-news":
        ok = fetch_market_news(args.limit).ok
    elif args.command == "inventory":
        ok = inventory(args.doc_type, args.company)
    else:
        from .vectorstore import delete_news_older_than

        print(f"[update] 已刪除 {delete_news_older_than(args.days)} 筆過期新聞 chunk。")
        ok = True

    # 失敗回非零結束碼，讓排程/CI 偵測得到；抓取函式本身的行為不變（graph 那邊靠字串）
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
