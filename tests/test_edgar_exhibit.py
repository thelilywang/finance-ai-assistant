"""6-K exhibit 選取，以及目錄讀取失敗時不得靜默偽裝成抓取成功。

背景：6-K 主文只是封面頁（地址、表頭、簽名），財報在 exhibit。封面頁約 2~3 千字元，
能通過 _MIN_FILING_CHARS(500) 檢查，所以「退回主文」若回報 ok=True，就會讓只有封面頁的
申報混進向量庫且看起來一切正常——ASML 2026 Q2 實際只入庫 2,923 字元就是這個形狀。
"""
import src.update as update
from src.update import _select_exhibit

COVER = "<html>" + "SECURITIES AND EXCHANGE COMMISSION Washington D.C. " * 40 + "</html>"
BODY = "<html>" + "Total net sales were 9.3 billion euro this quarter. " * 200 + "</html>"

ITEMS = [
    {"name": "0001628280-26-048235-index.html", "size": ""},
    {"name": "form6-kquarterlyfilings.htm", "size": "11412"},
    {"name": "financialstatementsusgaa.htm", "size": "27506"},
    {"name": "pressreleasefinancialresul.htm", "size": "43745"},
    {"name": "statutoryinterimreport20.htm", "size": "76137"},
    {"name": "statutoryinterimreport20001.jpg", "size": "125015"},  # 更大但非 htm
]

SUBMISSIONS = {"filings": {"recent": {
    "form": ["6-K"], "accessionNumber": ["0001628280-26-048235"],
    "filingDate": ["2026-07-15"], "reportDate": ["2026-06-30"],
    "primaryDocument": ["form6-kquarterlyfilings.htm"],
}}}
LISTING = {"directory": {"item": ITEMS}}


class _Resp:
    def __init__(self, payload=None, text="", boom=None):
        self._payload, self.text, self._boom = payload, text, boom

    def raise_for_status(self):
        pass

    def json(self):
        if self._boom:
            raise self._boom
        return self._payload


def test_select_exhibit_picks_largest_non_index_htm():
    # --- _select_exhibit：挑最大的 .htm，排除主文與 -index 檔 ---
    assert _select_exhibit(ITEMS, "form6-kquarterlyfilings.htm") == "statutoryinterimreport20.htm"
    # 只有主文時沒得挑，退回主文
    assert _select_exhibit([{"name": "cover.htm", "size": "11412"}], "cover.htm") == "cover.htm"
    # size 缺漏不得炸掉（EDGAR 目錄項的 size 是字串，索引頁為空字串）
    assert _select_exhibit(
        [{"name": "a.htm"}, {"name": "b.htm", "size": "900"}], "cover.htm"
    ) == "b.htm"


def _run(monkeypatch, submissions, index_json_behaviour):
    """跑一次 fetch_edgar，index.json 的回應行為由參數決定。"""
    ingested = {}

    def fake_get(url, **kw):
        if "company_tickers" in url:
            return _Resp({"0": {"cik_str": 937966, "ticker": "ASML"}})
        if "submissions" in url:
            return _Resp(submissions)
        if url.endswith("index.json"):
            return index_json_behaviour()
        ingested["url"] = url
        return _Resp(text=BODY if "statutoryinterimreport" in url else COVER)

    monkeypatch.setattr(update.requests, "get", fake_get)
    monkeypatch.setattr(update, "ingest_text", lambda text, **kw: ingested.update(chars=len(text)) or 0)
    update._company_tickers.cache_clear()
    result = update.fetch_edgar("ASML")
    update._company_tickers.cache_clear()
    return result, ingested


def test_fetch_edgar_normal_path_downloads_exhibit(monkeypatch):
    # --- 正常路徑：抓到目錄就下載 exhibit 本文，回報成功 ---
    result, got = _run(monkeypatch, SUBMISSIONS, lambda: _Resp(LISTING))
    assert result.ok, result
    assert got["url"].endswith("statutoryinterimreport20.htm"), got["url"]


def test_fetch_edgar_directory_failure_falls_back_but_not_ok(monkeypatch):
    # --- except 分支：目錄讀取失敗 → 退回主文，但絕不可回報成功 ---
    def _broken_json():
        return _Resp(boom=ValueError("Expecting value: line 1 column 1 (char 0)"))

    result, got = _run(monkeypatch, SUBMISSIONS, _broken_json)
    assert got["url"].endswith("form6-kquarterlyfilings.htm"), "應退回主文"
    # 封面頁字數足以通過 _MIN_FILING_CHARS，正是靜默成功最危險的地方
    assert got["chars"] > update._MIN_FILING_CHARS
    assert not result.ok, "退回封面頁不得回報成功，否則呼叫端無從分辨內容缺漏"
    for want in ("封面頁", "0001628280-26-048235", "ASML", "ValueError"):
        assert want in result.detail, f"detail 應含 {want}：{result.detail}"


def test_fetch_edgar_network_error_not_ok(monkeypatch):
    # 網路錯誤同樣不得靜默成功
    def _timeout():
        raise update.requests.RequestException("Read timed out")

    result, _ = _run(monkeypatch, SUBMISSIONS, _timeout)
    assert not result.ok and "封面頁" in result.detail, result


def test_fetch_edgar_non_6k_skips_exhibit_selection(monkeypatch):
    # --- 非 6-K（如 10-Q）不走 exhibit 選取，維持原行為 ---
    ten_q = {"filings": {"recent": {
        "form": ["10-Q"], "accessionNumber": ["0000320193-26-000020"],
        "filingDate": ["2026-07-31"], "reportDate": ["2026-06-28"],
        "primaryDocument": ["aapl-20260628.htm"],
    }}}
    result, got = _run(monkeypatch, ten_q, lambda: _Resp(LISTING))
    assert result.ok and got["url"].endswith("aapl-20260628.htm"), got
