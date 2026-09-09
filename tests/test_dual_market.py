"""最小 self-check：雙掛牌標的的市場確認流程。
執行：python tests/test_dual_market.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph import resolve_market, route_after_resolve_market
from src.tickers import TW_US_DUAL_LISTED, TW_US_OTC_ONLY, dual_listed_peer, otc_adr_of

# --- 對照表雙向查詢 ---
assert dual_listed_peer("2330") == "TSM"
assert dual_listed_peer("TSM") == "2330"
assert dual_listed_peer("tsm") == "2330"      # 大小寫不敏感
assert dual_listed_peer("AAPL") is None       # 非雙掛牌
assert dual_listed_peer("2454") is None       # 台股但無 ADR
assert dual_listed_peer("8150") == "IMOS"     # 南茂（NASDAQ）
assert dual_listed_peer("IMOS") == "8150"

# --- 只收美股那側查得到財報的標的 ---
# OTC 的 Level 1／非贊助 ADR 不向 SEC 申報，實測這六檔在 company_tickers.json 查無 CIK。
# 放進市場選擇流程會讓使用者選了「美股」卻拿到查無資料，比不給這個選項更糟
for tw in TW_US_OTC_ONLY:
    assert dual_listed_peer(tw) is None, tw
assert otc_adr_of("2317") == "HNHPF"          # 但仍記錄，供回答時附帶告知
assert otc_adr_of("2409") == "AUOTY"
assert otc_adr_of("2330") is None             # 主板標的不走這條
assert otc_adr_of("AAPL") is None

# 兩張表不得重疊，否則同一代號會同時走兩條路徑
assert not (set(TW_US_DUAL_LISTED) & set(TW_US_OTC_ONLY))

# 富智康是港股 2038，不是台股：鍵位一律當台股代號用會被誤判成台股去查證交所 API
assert dual_listed_peer("2038") is None and otc_adr_of("2038") is None

# --- 沒指明市場 → 反問，且不得先挑一邊 ---
s = resolve_market({"company": "2330", "market": None})
assert s["ask_market"] is True and s["peer_company"] == "TSM"
assert s["company"] == "2330"                 # 尚未決定，不動 company
assert route_after_resolve_market(s) == "ask_market"

# --- 使用者已明講市場 → 直接照辦，不打斷對話 ---
# 講美股但抽到的是台股代號：要換成 ADR 代號，否則查到的是台股資料
s = resolve_market({"company": "2330", "market": "us"})
assert s["company"] == "TSM" and s["ask_market"] is False
assert route_after_resolve_market(s) == "agent"

# 講台股但抽到 ADR 代號：反向對齊
s = resolve_market({"company": "TSM", "market": "tw"})
assert s["company"] == "2330" and s["ask_market"] is False

# 講的市場與抽到的代號本來就一致：原樣通過
assert resolve_market({"company": "2330", "market": "tw"})["company"] == "2330"
assert resolve_market({"company": "TSM", "market": "us"})["company"] == "TSM"

# --- 兩邊都要：保留原代號並帶出對應代號，供 generate 併陳與提醒 ---
s = resolve_market({"company": "2330", "market": "both"})
assert s["ask_market"] is False and s["peer_company"] == "TSM"
assert route_after_resolve_market(s) == "agent"

# --- 非雙掛牌公司完全不受影響，不會多問一句 ---
s = resolve_market({"company": "AAPL", "market": None})
assert s["ask_market"] is False and route_after_resolve_market(s) == "agent"
assert s["company"] == "AAPL"

# company 為 None（問法沒指名公司）也不得炸掉
assert resolve_market({"company": None, "market": None})["ask_market"] is False

# --- 追問情境：使用者回答上一輪的反問，答句本身不含公司名 ---
# 改寫未必補得回公司，若不從歷史撿回代號會退化成「不限公司」的全庫檢索
from src.graph import _last_dual_listed

hist = [("台積電最新一季EPS多少?", "「台積電」在台股與美股都有掛牌…要看哪一邊？")]
assert _last_dual_listed(hist) == "2330"
assert _last_dual_listed([("TSM 的 EPS?", "...")]) == "2330"
assert _last_dual_listed([("蘋果的營收?", "...")]) is None   # 非雙掛牌不亂猜
assert _last_dual_listed([]) is None

# 回答「美股」：company 由歷史撿回並對齊到 ADR 代號
s = resolve_market({"company": None, "market": "us", "history": hist})
assert s["company"] == "TSM" and s["ask_market"] is False

# 回答「台股」
s = resolve_market({"company": None, "market": "tw", "history": hist})
assert s["company"] == "2330" and s["ask_market"] is False

# 回答「都要」：兩個代號都要留著，且不可再問一次
s = resolve_market({"company": None, "market": "both", "history": hist})
assert s["company"] == "2330" and s["peer_company"] == "TSM"
assert s["ask_market"] is False

# 沒有歷史可撿又沒公司：走一般流程，不得誤認成雙掛牌
s = resolve_market({"company": None, "market": "us", "history": []})
assert s["company"] is None and s["ask_market"] is False

# --- UI 按鈕：呼叫端指定的 market 不得被 extract_filters 重抽的結果蓋掉 ---
# 點按鈕後帶著 market 重跑，但問句本身沒有市場字樣，重抽必然回 None；
# 若讓它覆寫就等於把剛按下的選擇丟掉，畫面上會再問一次
import src.graph as _g


class _FakeParsed:
    status, error_message = "ok", None
    company = doc_type = news_since_days = market = None


_orig_llms = _g._llms
try:
    _g._llms = lambda m: {"filters": type("F", (), {"invoke": lambda self, p: _FakeParsed()})()}
    out = _g.extract_filters({"question": "台積電EPS?", "company": "2330", "market": "us",
                              "lang": "zh", "model": ""})
    assert out["market"] == "us"      # 按鈕選的市場保留
    assert out["company"] == "2330"   # 公司也不能被抽成 None，否則變全庫檢索

    # 沒有呼叫端指定時，照常採用重抽結果（不影響一般問句）
    out = _g.extract_filters({"question": "隨便問問", "lang": "zh", "model": ""})
    assert out["market"] is None and out["company"] is None
finally:
    _g._llms = _orig_llms

print("dual market self-check OK")
