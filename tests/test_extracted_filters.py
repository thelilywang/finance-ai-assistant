"""最小 self-check：ExtractedFilters 的 news_since_days 夾取。

這個值會直接進 similarity_search 的 SQL 日期比較，本地模型回 0 或負數會讓條件
變成「未來的新聞」而查出空結果，所以邊界要固定住。
執行：python tests/test_extracted_filters.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph import ExtractedFilters

# 沒指定時效 → None（不過濾）
assert ExtractedFilters().news_since_days is None
assert ExtractedFilters(news_since_days=None).news_since_days is None

# 正常範圍原樣保留
assert ExtractedFilters(news_since_days=1).news_since_days == 1
assert ExtractedFilters(news_since_days=90).news_since_days == 90
assert ExtractedFilters(news_since_days=365).news_since_days == 365

# 越界夾回範圍內：0 與負數不能讓 SQL 變成查未來的新聞
assert ExtractedFilters(news_since_days=0).news_since_days == 1
assert ExtractedFilters(news_since_days=-7).news_since_days == 1
assert ExtractedFilters(news_since_days=9999).news_since_days == 365

# company 的正規化不受影響（同一個 model 上兩個 validator）
assert ExtractedFilters(company="台積電", news_since_days=7).news_since_days == 7

print("ExtractedFilters self-check OK")
