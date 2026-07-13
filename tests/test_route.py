"""最小 self-check：route_after_retrieve 各種 retrieved/company/fetched 組合。
執行：python tests/test_route.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph import route_after_retrieve

report = {"doc_type": "financial_report"}
news = {"doc_type": "news"}

# 有新聞在結果裡 → 直接 generate
assert route_after_retrieve({"retrieved": [report, news], "company": "AAPL", "fetched": False}) == "generate"
# 有財報沒新聞、還沒抓過 → auto_fetch 補新聞
assert route_after_retrieve({"retrieved": [report], "company": "AAPL", "fetched": False}) == "auto_fetch"
# 抓過了就不再抓
assert route_after_retrieve({"retrieved": [report], "company": "AAPL", "fetched": True}) == "generate"
# 沒指名公司不抓
assert route_after_retrieve({"retrieved": [report], "company": None, "fetched": False}) == "generate"
# 完全沒結果、有公司 → auto_fetch
assert route_after_retrieve({"retrieved": [], "company": "AAPL", "fetched": False}) == "auto_fetch"
# 完全沒結果、沒公司、還沒抓過 → auto_fetch（沒公司也掃市場新聞）
assert route_after_retrieve({"retrieved": [], "company": None, "fetched": False}) == "auto_fetch"
# 完全沒結果、沒公司、抓過了 → no_result
assert route_after_retrieve({"retrieved": [], "company": None, "fetched": True}) == "no_result"

print("route_after_retrieve self-check OK")
