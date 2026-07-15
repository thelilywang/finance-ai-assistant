"""手動觸發更新：抓取財報/新聞並匯入 pgvector。

用法：
    python -m src.update report --market us --company AAPL [--form 10-Q]
    python -m src.update report --market tw --company 2330
    python -m src.update news --company 2330 --limit 10
    python -m src.update market-news [--limit 10]
    python -m src.update prune --days 180
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html as html_lib
import re
import xml.etree.ElementTree as ET

import requests
import trafilatura

from . import config
from .ingest import ingest_file, ingest_text

TIMEOUT = 30

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
    "cmoney_tag": ("https://www.cmoney.tw/notes/?tag=12367",
                   r"note-detail\.aspx\?nid=(\d+)",
                   lambda m: f"https://www.cmoney.tw/notes/note-detail.aspx?nid={m.group(1)}"),
    "cnyes_us": ("https://news.cnyes.com/news/cat/us_stock",
                 r"/news/id/(\d+)",
                 lambda m: f"https://news.cnyes.com/news/id/{m.group(1)}"),
    "cnyes_tw": ("https://news.cnyes.com/news/cat/tw_stock_news",
                 r"/news/id/(\d+)",
                 lambda m: f"https://news.cnyes.com/news/id/{m.group(1)}"),
}

MOPS_MANUAL_GUIDE = """[update] MOPS 抓取失敗（介面脆弱，隨時可能變動）。手動下載步驟：
  1. 開 https://doc.twse.com.tw/server-java/t57sb01 或公開資訊觀測站搜尋公司代號
  2. 下載最新財報 PDF 到 data/
  3. 執行 python -m src.ingest --file data/<檔名>.pdf --company <代號> \\
       --doc-type financial_report --date <YYYY-MM-DD>"""


def fetch_edgar(ticker: str, form: str = "10-Q") -> None:
    """從 SEC EDGAR 抓最新一份指定表單（10-K/10-Q），抽純文字後匯入。"""
    headers = {"User-Agent": config.SEC_USER_AGENT}

    resp = requests.get(
        "https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=TIMEOUT
    )
    resp.raise_for_status()
    entry = next(
        (v for v in resp.json().values() if v["ticker"].upper() == ticker.upper()), None
    )
    if entry is None:
        print(f"[update] 找不到 ticker {ticker} 對應的 CIK。")
        return
    cik = entry["cik_str"]

    resp = requests.get(
        f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=headers, timeout=TIMEOUT
    )
    resp.raise_for_status()
    recent = resp.json()["filings"]["recent"]
    # ponytail: 外國發行人（如 ASML/TSM）不申報 10-Q/10-K，季報走 6-K、年報走 20-F；
    # 新上市公司退回 424B4/S-1 招股書。6-K 也可能是非財報公告，先取最新一份，誤抓再精修。
    for f in (form, "10-K", "6-K", "20-F", "424B4", "S-1"):
        if f in recent["form"]:
            form, idx = f, recent["form"].index(f)
            break
    else:
        print(f"[update] {ticker} 近期沒有 {form}/10-K/424B4/S-1 申報。")
        return

    accession = recent["accessionNumber"][idx]
    filing_date = recent["filingDate"][idx]
    primary_doc = recent["primaryDocument"][idx]

    url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik}/"
        f"{accession.replace('-', '')}/{primary_doc}"
    )
    print(f"[update] 下載 {form}：{url}")
    resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()

    text = trafilatura.extract(resp.text)
    if not text:
        # ponytail: trafilatura 抽不到就整包去 tag 粗抽 + 解 HTML entities（€ 等符號），財報 HTML 幾乎都抽得到
        text = html_lib.unescape(re.sub(r"<[^>]+>", " ", resp.text))
    ingest_text(
        text,
        source=f"EDGAR:{ticker.upper()}:{accession}",
        company=ticker.upper(),
        doc_type="financial_report",
        published_at=filing_date,
    )


def fetch_mops(co_id: str) -> None:
    """從 MOPS（公開資訊觀測站）抓最新財報 PDF 並匯入。

    # ponytail: MOPS 無官方 API，此爬取流程隨時可能失效；掛掉時印手動下載指引，不 raise。
    """
    try:
        endpoint = "https://doc.twse.com.tw/server-java/t57sb01"
        filename = None
        for year in (dt.date.today().year - 1911, dt.date.today().year - 1912):
            resp = requests.post(
                endpoint,
                data={
                    "id": "", "key": "", "step": "1", "co_id": co_id, "year": str(year),
                    "seamon": "", "mtype": "A", "encodeURIComponent": "1", "firstin": "true",
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            files = re.findall(r"(\d{6}_%s_\w+\.pdf)" % re.escape(co_id), resp.text)
            if files:
                filename = sorted(files)[-1]  # 檔名以 YYYYMM 開頭，排序取最新
                break
        if not filename:
            print(f"[update] MOPS 查無 {co_id} 的財報檔案。")
            print(MOPS_MANUAL_GUIDE)
            return

        resp = requests.post(
            endpoint,
            data={"step": "9", "kind": "A", "co_id": co_id, "filename": filename},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        m = re.search(r"href=['\"](/pdf/[^'\"]+)['\"]", resp.text)
        if not m:
            print(f"[update] MOPS 第二步找不到 PDF 連結（{filename}）。")
            print(MOPS_MANUAL_GUIDE)
            return

        resp = requests.get(f"https://doc.twse.com.tw{m.group(1)}", timeout=TIMEOUT)
        resp.raise_for_status()
        path = f"data/{filename}"
        with open(path, "wb") as f:
            f.write(resp.content)
        print(f"[update] 已下載 {path}")

        # 檔名開頭為西元 YYYYMM（如 202601_2330_AI1.pdf），推出發布日期
        published_at = f"{filename[:4]}-{filename[4:6]}-01"
        ingest_file(path, company=co_id, doc_type="financial_report", published_at=published_at)
    except Exception as e:  # noqa: BLE001
        print(f"[update] MOPS 抓取異常：{e}")
        print(MOPS_MANUAL_GUIDE)


def fetch_news(company: str, limit: int = 10) -> None:
    """從 Yahoo Finance RSS 抓最新新聞並匯入。台股 4 碼代號自動加 .TW。"""
    symbol = f"{company}.TW" if company.isdigit() and len(company) == 4 else company
    url = (
        "https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={symbol}&region=US&lang=en-US"
    )
    # Yahoo 會擋預設的 python-requests User-Agent，帶瀏覽器 UA
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT)
    if resp.status_code != 200:
        print(f"[update] Yahoo RSS 取得失敗（HTTP {resp.status_code}），稍後再試。")
        return

    items = ET.fromstring(resp.content).findall(".//item")[:limit]
    if not items:
        print(f"[update] {symbol} 的 RSS 沒有新聞。")
        return

    total = 0
    for item in items:
        try:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
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
        except Exception as e:  # noqa: BLE001
            print(f"[update] 新聞處理失敗（{link}）：{e}")
    print(f"[update] 新聞更新完成，共寫入 {total} 筆 chunk。")


def _company_from_title(title: str) -> str | None:
    """標題含「公司名(2330)」時抽出台股代號。# ponytail: 括號內 4 碼即視為代號，誤抓年份的機率低"""
    m = re.search(r"[（(](\d{4})[）)]", title)
    return m.group(1) if m else None


def fetch_market_news(limit_per_source: int = 10) -> None:
    """掃 MARKET_SOURCES 列表頁，抓新文章入庫。已入庫的 source 直接跳過。"""
    from .vectorstore import source_exists

    total = 0
    skipped = 0
    for name, (listing_url, pattern, normalize) in MARKET_SOURCES.items():
        resp = requests.get(
            listing_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT
        )
        if resp.status_code != 200:
            print(f"[update] {name} 列表頁取得失敗（HTTP {resp.status_code}），跳過。")
            continue

        urls: list[str] = []
        seen = set()
        for m in re.finditer(pattern, resp.text):
            url = normalize(m)
            if url not in seen:
                seen.add(url)
                urls.append(url)
        if not urls:
            print(f"[update] {name} 找不到任何文章連結（版面可能改版），跳過。")
            continue

        for url in urls[:limit_per_source]:
            if source_exists(url):
                skipped += 1
                continue
            try:
                html = trafilatura.fetch_url(url)
                if not html:
                    print(f"[update] {name} 文章下載失敗：{url}")
                    continue
                doc = trafilatura.bare_extraction(html, with_metadata=True)
                if not doc or len(doc.text or "") < 100:
                    print(f"[update] {name} 內文過短或抽取失敗：{url}")
                    continue

                title = (doc.title or "").strip() or None
                published_at = doc.date
                company = _company_from_title(title) if title else None
                text = f"{title}\n\n{doc.text}" if title else doc.text
                total += ingest_text(
                    text, source=url, company=company, doc_type="news",
                    published_at=published_at, title=title,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[update] {name} 文章處理失敗（{url}）：{e}")

    print(f"[update] 市場新聞更新完成，共寫入 {total} 筆 chunk，跳過 {skipped} 篇已入庫。")


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取財報/新聞並匯入 pgvector")
    sub = parser.add_subparsers(dest="command", required=True)

    p_report = sub.add_parser("report", help="抓財報（us: SEC EDGAR / tw: MOPS）")
    p_report.add_argument("--market", required=True, choices=["tw", "us"])
    p_report.add_argument("--company", required=True, help="美股 ticker 或台股代號")
    p_report.add_argument("--form", default="10-Q", help="美股表單類型，預設 10-Q")

    p_news = sub.add_parser("news", help="抓 Yahoo Finance RSS 新聞")
    p_news.add_argument("--company", required=True, help="美股 ticker 或台股代號")
    p_news.add_argument("--limit", type=int, default=10)

    p_market_news = sub.add_parser("market-news", help="掃市場總覽新聞列表頁（udn/cmoney）")
    p_market_news.add_argument("--limit", type=int, default=10, help="每個來源抓取篇數，預設 10")

    p_prune = sub.add_parser("prune", help="刪除過期新聞 chunk（財報不刪）")
    p_prune.add_argument("--days", type=int, default=180, help="保留天數，預設 180")

    args = parser.parse_args()
    if args.command == "report":
        if args.market == "us":
            fetch_edgar(args.company, args.form)
        else:
            fetch_mops(args.company)
    elif args.command == "news":
        fetch_news(args.company, args.limit)
    elif args.command == "market-news":
        fetch_market_news(args.limit)
    else:
        from .vectorstore import delete_news_older_than

        print(f"[update] 已刪除 {delete_news_older_than(args.days)} 筆過期新聞 chunk。")


if __name__ == "__main__":
    main()
