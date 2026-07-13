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

print("market_links self-check OK")
