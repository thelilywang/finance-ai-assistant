"""最小 self-check：market news 連結解析純函式，不碰網路。
執行：python tests/test_market_links.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.update import MARKET_SOURCES, _company_from_title

assert _company_from_title("台積電(2330)大漲") == "2330"
assert _company_from_title("（2603）長榮") == "2603"
assert _company_from_title("美股大漲") is None

# udn: 相對連結 + tracking query，應正規化為無 query 的絕對網址
_, pattern, normalize = MARKET_SOURCES["udn_tw"]
html = '<a href="/money/story/11074/9625182?from=edn_navibar">標題</a>'
m = re.search(pattern, html)
assert m is not None
assert normalize(m) == "https://money.udn.com/money/story/11074/9625182"

# cmoney: query 本身是 nid，需保留
_, pattern, normalize = MARKET_SOURCES["cmoney_tw"]
html = '<a href="https://www.cmoney.tw/notes/note-detail.aspx?nid=123">標題</a>'
m = re.search(pattern, html)
assert m is not None
assert normalize(m) == "https://www.cmoney.tw/notes/note-detail.aspx?nid=123"

# fetch_tw_stock_news 的連結 regex：假 HTML 字串、不碰網路
_TW_STOCK_NEWS_LINK_RE = r'"(https://tw\.stock\.yahoo\.com/news/[^"?]+\.html)"'
html = (
    '"https://tw.stock.yahoo.com/news/公告-虹光115年8月合併營業收入-123456.html"'
    '"https://tw.stock.yahoo.com/news/公告-虹光115年8月合併營業收入-123456.html"'
    '"https://tw.stock.yahoo.com/news/other-article-789.html"'
    # 帶 query string 的連結（如 tracking 參數）不應被誤吃進 .html 之後
    '"https://tw.stock.yahoo.com/news/tracked-article.html?src=rss"'
)
links = list(dict.fromkeys(re.findall(_TW_STOCK_NEWS_LINK_RE, html)))
# 重複連結應保序去重只留一份；帶 query 的連結因規則要求 .html 緊接右引號，不會被收進來
assert links == [
    "https://tw.stock.yahoo.com/news/公告-虹光115年8月合併營業收入-123456.html",
    "https://tw.stock.yahoo.com/news/other-article-789.html",
], links

print("market_links self-check OK")
