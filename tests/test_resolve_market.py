"""反問前提改由問句判斷（_market_in_question）與 market_confirmed 早退。
不需要 LLM、不連 DB——照 test_dual_market.py 的模式，只 import src.graph 直接餵 state。
"""
from src.graph import _collapse_dual_listing, extract_filters, resolve_market, rewrite_question


def test_collapse_dual_listing_merges_same_company():
    # --- 同一家公司的兩個掛牌要收斂成一個，否則會被當成多標的比較 ---
    # 留兩個元素會踩到三處 len(companies)>1：繞過反問與 both 併陳、決策卡把同一家公司
    # 當兩家開比較表、逐家重複抓同一家新聞
    assert _collapse_dual_listing(["2303", "UMC"]) == ["2303"]
    assert _collapse_dual_listing(["UMC", "2303"]) == ["2303"]   # 抽取順序不保證


def test_collapse_dual_listing_leaves_real_multi_company():
    # 真多標的不得誤傷：兩家不同公司照原樣留著
    assert _collapse_dual_listing(["2330", "2303"]) == ["2330", "2303"]
    assert _collapse_dual_listing(["2330", "UMC"]) == ["2330", "UMC"]
    assert _collapse_dual_listing(["MSFT", "GOOGL"]) == ["MSFT", "GOOGL"]
    assert _collapse_dual_listing(["2881", "2303", "3711"]) == ["2881", "2303", "3711"]
    assert _collapse_dual_listing([]) == [] and _collapse_dual_listing(["2330"]) == ["2330"]


def test_resolve_market_collapsed_dual_listing_enters_both_branch():
    # 收斂後走得進雙掛牌併陳分支（修正前這題會短路成多標的比較）
    s = resolve_market({"question": "聯電台股美股兩邊比較一下",
                        "companies": _collapse_dual_listing(["2303", "UMC"]), "market": "both"})
    assert s["ask_market"] is False and s["market"] == "both" and s["peer_company"] == "UMC"


def test_resolve_market_asks_when_market_not_stated():
    # 1. 模型猜了 tw，但問句只有中文名，沒有市場字樣 → 該反問
    s = resolve_market({"question": "台積電的營收多少？", "companies": ["2330"], "market": "tw"})
    assert s["ask_market"] is True


def test_resolve_market_bare_ticker_still_asks():
    # 2. 代號直給（2330）→ 仍要反問。打代號不代表表態：使用者可能只是記得公司代號，
    #    雙掛牌兩邊幣別／期間／每股基準都不同，猜錯的代價大於多問一句。
    s = resolve_market({"question": "2330 最新財報重點？", "companies": ["2330"], "market": "tw"})
    assert s["ask_market"] is True and s["peer_company"] == "TSM"

    # 2b. 美股代號同理，規則對稱：TSM 也不算表態
    s = resolve_market({"question": "TSM 近期有什麼消息？", "companies": ["TSM"], "market": "us"})
    assert s["ask_market"] is True and s["peer_company"] == "2330"


def test_resolve_market_both_markets_stated():
    # 3. 明講「台股美股兩邊」→ 校正成 both，不反問；peer_company 帶出聯電的 ADR 代號
    s = resolve_market({"question": "聯電台股美股兩邊比較一下", "companies": ["2303"], "market": "tw"})
    assert s["ask_market"] is False
    assert s["market"] == "both"
    assert s["peer_company"] == "UMC"


def test_resolve_market_adr_phrase_aligns_company():
    # 4. 問句講「美股 ADR」→ company 對齊到 TSM，不反問
    s = resolve_market({"question": "台積電的美股 ADR 表現如何？", "companies": ["2330"], "market": "us"})
    assert s["companies"] == ["TSM"]
    assert s["ask_market"] is False


def test_resolve_market_none_still_asks():
    # 5. 既有行為不變：market 本來就是 None 時一樣要反問
    s = resolve_market({"question": "台積電的營收多少？", "companies": ["2330"], "market": None})
    assert s["ask_market"] is True


def test_resolve_market_confirmed_not_overridden():
    # 6. 按鈕重跑（market_confirmed=True）：問句沒有市場字樣，但不得被校正打回 None，
    #    否則會無限反問——這是本次修正最需要守住的防線
    s = resolve_market({"question": "台積電的營收多少？", "companies": ["2330"], "market": "us",
                         "market_confirmed": True})
    assert s["ask_market"] is False
    assert s["companies"] == ["TSM"]


def test_resolve_market_multi_company_bypasses_ask():
    # 7. 多標的：短路路徑不受影響，不因其中一家雙掛牌就卡反問
    s = resolve_market({"question": "比較一下 2330 和 2303 的表現", "companies": ["2330", "2303"],
                         "market": "tw"})
    assert s["ask_market"] is False


def test_resolve_market_non_dual_listed_unaffected():
    # 8. 非雙掛牌（MSFT）：完全不受影響
    s = resolve_market({"question": "現在該不該買微軟？", "companies": ["MSFT"], "market": "us"})
    assert s["ask_market"] is False


def test_rewrite_question_early_return_when_confirmed():
    # 9. rewrite_question 早退：market_confirmed=True 時原樣回傳，不呼叫 LLM
    state = {"question": "台積電的營收多少？", "history": [("上一輪", "上一輪回覆")],
             "market_confirmed": True}
    out = rewrite_question(state)
    assert out == state


def test_extract_filters_early_return_when_confirmed():
    # 10. extract_filters 早退：market_confirmed=True 且 companies 非空時原樣回傳，不呼叫 LLM
    state = {"question": "台積電的營收多少？", "companies": ["2330"], "market": "us",
             "market_confirmed": True}
    out = extract_filters(state)
    assert out == state
