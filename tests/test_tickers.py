"""最小 self-check：normalize_ticker / is_tw_ticker 邊界案例。
執行：python tests/test_tickers.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tickers import normalize_ticker, is_tw_ticker

# 台股：一般股票 4 碼
assert normalize_ticker("2330") == "2330"
assert is_tw_ticker("2330")
# 台股：ETF 舊制 4 碼 / 中世代 5 碼 / 新制 6 碼
assert normalize_ticker("0050") == "0050"
assert normalize_ticker("00878") == "00878"
assert normalize_ticker("009801") == "009801"
assert is_tw_ticker("009801")
# 台股：特別股 / 可轉債（4 碼數字 + 1 碼英數尾碼）
assert normalize_ticker("2891B") == "2891B"
assert is_tw_ticker("2891B")
assert normalize_ticker("23791") == "23791"  # 5 碼數字（可轉債），仍在 4-6 碼數字規則內
# 台股：模型自行加上交易所後綴要被去除
assert normalize_ticker("2330.TW") == "2330"
assert normalize_ticker("2330.TWO") == "2330"

# 美股：主體代號 1-5 碼大寫字母
assert normalize_ticker("AAPL") == "AAPL"
assert not is_tw_ticker("AAPL")
assert normalize_ticker("ibm") == "IBM"  # 小寫要正規化成大寫
# 美股：特殊股別後綴一律砍掉只留主體代號
assert normalize_ticker("ABC.PR.A") == "ABC"
assert normalize_ticker("XYZ.W") == "XYZ"

# 不符合任何已知格式 → 視為抽取失敗
assert normalize_ticker("台積電") is None
assert normalize_ticker("WHAT") == "WHAT"  # 純字母仍會過美股格式（格式驗證管不到語意誤判，是 extract_filters 的職責）
assert normalize_ticker("123456789") is None  # 超過 6 碼數字
assert normalize_ticker("") is None
assert not is_tw_ticker("AAPL")

print("tickers self-check OK")
