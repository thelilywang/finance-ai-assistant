"""最小 self-check：route_after_retrieve 各種 retrieved/company/fetched 組合。
執行：python tests/test_route.py
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph import needs_refetch, route_after_retrieve

report = {"doc_type": "financial_report"}
news = {"doc_type": "news", "published_at": dt.date.today()}  # 今天的新聞，不算過期
stale_news = {"doc_type": "news", "published_at": dt.date(2000, 1, 1)}
base = {"question": "近況如何？"}  # route_after_retrieve 會用 question 判斷是否要求「最新」

# needs_refetch 獨立斷言
assert needs_refetch([report, news], "AAPL", "近況如何？") is False
assert needs_refetch([report], "AAPL", "近況如何？") is True  # 有財報沒新聞
assert needs_refetch([report, stale_news], "AAPL", "近況如何？") is True  # 新聞過舊
assert needs_refetch([report, stale_news], "AAPL", "最新消息？") is True  # 要求最新，門檻收緊
assert needs_refetch([report], None, "近況如何？") is False  # 沒指名公司不判斷

# 有新聞在結果裡（且夠新）→ 直接 generate
assert route_after_retrieve({**base, "retrieved": [report, news], "company": "AAPL", "fetched": False}) == "generate"
# 有財報沒新聞、還沒抓過 → auto_fetch 補新聞
assert route_after_retrieve({**base, "retrieved": [report], "company": "AAPL", "fetched": False}) == "auto_fetch"
# 新聞在結果裡但日期過舊、還沒抓過 → auto_fetch 重抓
assert route_after_retrieve({**base, "retrieved": [report, stale_news], "company": "AAPL", "fetched": False}) == "auto_fetch"
# 抓過了就不再抓（即使新聞過舊，fetched=True 保證只重試一次）
assert route_after_retrieve({**base, "retrieved": [report, stale_news], "company": "AAPL", "fetched": True}) == "generate"
# 沒指名公司不抓
assert route_after_retrieve({**base, "retrieved": [report], "company": None, "fetched": False}) == "generate"
# 完全沒結果、有公司 → auto_fetch
assert route_after_retrieve({**base, "retrieved": [], "company": "AAPL", "fetched": False}) == "auto_fetch"
# 完全沒結果、沒公司、還沒抓過 → auto_fetch（沒公司也掃市場新聞）
assert route_after_retrieve({**base, "retrieved": [], "company": None, "fetched": False}) == "auto_fetch"
# 完全沒結果、沒公司、抓過了 → no_result
assert route_after_retrieve({**base, "retrieved": [], "company": None, "fetched": True}) == "no_result"

print("route_after_retrieve self-check OK")
