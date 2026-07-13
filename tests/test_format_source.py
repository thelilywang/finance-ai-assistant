"""最小 self-check：_format_source 三種情況（EDGAR/本地檔/帶追蹤參數的 URL）、_clean_url。
執行：python tests/test_format_source.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app import _clean_url, _format_source

# EDGAR 來源：無連結，純文字含 ticker
assert _format_source("EDGAR:AAPL:0000320193-25-000057") == "SEC EDGAR filing (AAPL)"

# 本地路徑：只留檔名
assert _format_source("data/202601_2330_AI1.pdf") == "202601_2330_AI1.pdf"

# 帶追蹤 query 的 URL：去掉 query/fragment，標題從 path slug 生成
result = _format_source("https://www.example.com/news/apple-q3-earnings-beat?.tsrc=rss&utm=1#section")
assert "?.tsrc=rss" not in result
assert "https://www.example.com/news/apple-q3-earnings-beat" in result
assert "example.com" in result
assert "www." not in result.split("(")[0]  # domain 去掉 www.

# _clean_url：URL 去 query/fragment；非 URL（EDGAR/本地檔）回 None
assert _clean_url("https://www.example.com/a?x=1#y") == "https://www.example.com/a"
assert _clean_url("EDGAR:AAPL:0000320193-25-000057") is None
assert _clean_url("data/202601_2330_AI1.pdf") is None

print("_format_source self-check OK")
