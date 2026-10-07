"""雙掛牌標的的市場確認流程。"""
import src.graph as _g
from src.graph import (
    _last_dual_listed,
    _side_by_side,
    cross_market_split,
    resolve_market,
    route_after_resolve_market,
)
from src.market import get_adr_premium
from src.tickers import TW_US_DUAL_LISTED, TW_US_OTC_ONLY, dual_listed_peer, otc_adr_of


def test_dual_listed_peer_lookup():
    # --- 對照表雙向查詢 ---
    assert dual_listed_peer("2330") == "TSM"
    assert dual_listed_peer("TSM") == "2330"
    assert dual_listed_peer("tsm") == "2330"      # 大小寫不敏感
    assert dual_listed_peer("AAPL") is None       # 非雙掛牌
    assert dual_listed_peer("2454") is None       # 台股但無 ADR
    assert dual_listed_peer("8150") == "IMOS"     # 南茂（NASDAQ）
    assert dual_listed_peer("IMOS") == "8150"


def test_otc_adr_only_excluded_from_dual_listed():
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


def test_resolve_market_asks_and_does_not_pick_side():
    # --- 沒指明市場 → 反問，且不得先挑一邊 ---
    # 市場判斷改以問句為準，問句沒有市場字樣（純代號題）就該反問，即使呼叫端給了 market
    s = resolve_market({"companies": ["2330"], "market": None, "question": "台積電的營收多少？"})
    assert s["ask_market"] is True and s["peer_company"] == "TSM"
    assert s["companies"] == ["2330"]             # 尚未決定，不動 company
    assert route_after_resolve_market(s) == "ask_market"


def test_resolve_market_explicit_market_realigns_company():
    # --- 使用者已明講市場 → 直接照辦，不打斷對話 ---
    # 市場判斷改以問句為準，呼叫端的 market 不再被無條件採信，故這裡要帶含市場字樣的問句
    # 講美股但抽到的是台股代號：要換成 ADR 代號，否則查到的是台股資料
    s = resolve_market({"companies": ["2330"], "market": "us", "question": "台積電的美股表現如何？"})
    assert s["companies"] == ["TSM"] and s["ask_market"] is False
    assert route_after_resolve_market(s) == "agent"

    # 講台股但抽到 ADR 代號：反向對齊
    s = resolve_market({"companies": ["TSM"], "market": "tw", "question": "台積電台股表現如何？"})
    assert s["companies"] == ["2330"] and s["ask_market"] is False

    # 講的市場與抽到的代號本來就一致：原樣通過
    assert resolve_market({"companies": ["2330"], "market": "tw",
                            "question": "台積電台股的營收？"})["companies"] == ["2330"]
    assert resolve_market({"companies": ["TSM"], "market": "us",
                            "question": "TSM 的美股營收？"})["companies"] == ["TSM"]


def test_resolve_market_both_markets():
    # --- 兩邊都要：保留原代號並帶出對應代號，供 generate 併陳與提醒 ---
    # 問句要含「兩邊」語意，否則校正後 market 會變成 None（沒講）而非 both
    s = resolve_market({"companies": ["2330"], "market": "both",
                         "question": "台積電台股美股兩邊比較一下"})
    assert s["ask_market"] is False and s["peer_company"] == "TSM"
    assert route_after_resolve_market(s) == "agent"


def test_resolve_market_non_dual_listed_unaffected():
    # --- 非雙掛牌公司完全不受影響，不會多問一句 ---
    s = resolve_market({"companies": ["AAPL"], "market": None})
    assert s["ask_market"] is False and route_after_resolve_market(s) == "agent"
    assert s["companies"] == ["AAPL"]

    # company 為空（問法沒指名公司）也不得炸掉
    assert resolve_market({"companies": [], "market": None})["ask_market"] is False


def test_last_dual_listed_from_history():
    # --- 追問情境：使用者回答上一輪的反問，答句本身不含公司名 ---
    # 改寫未必補得回公司，若不從歷史撿回代號會退化成「不限公司」的全庫檢索
    hist = [("台積電最新一季EPS多少?", "「台積電」在台股與美股都有掛牌…要看哪一邊？")]
    assert _last_dual_listed(hist) == "2330"
    assert _last_dual_listed([("TSM 的 EPS?", "...")]) == "2330"
    assert _last_dual_listed([("蘋果的營收?", "...")]) is None   # 非雙掛牌不亂猜
    assert _last_dual_listed([]) is None


def test_resolve_market_recovers_company_from_history():
    hist = [("台積電最新一季EPS多少?", "「台積電」在台股與美股都有掛牌…要看哪一邊？")]

    # 回答「美股」：company 由歷史撿回並對齊到 ADR 代號
    s = resolve_market({"companies": [], "market": "us", "history": hist})
    assert s["companies"] == ["TSM"] and s["ask_market"] is False

    # 回答「台股」
    s = resolve_market({"companies": [], "market": "tw", "history": hist})
    assert s["companies"] == ["2330"] and s["ask_market"] is False

    # 回答「都要」：兩個代號都要留著，且不可再問一次
    s = resolve_market({"companies": [], "market": "both", "history": hist})
    assert s["companies"] == ["2330"] and s["peer_company"] == "TSM"
    assert s["ask_market"] is False

    # 沒有歷史可撿又沒公司：走一般流程，不得誤認成雙掛牌
    s = resolve_market({"companies": [], "market": "us", "history": []})
    assert s["companies"] == [] and s["ask_market"] is False


def test_ui_button_market_not_overridden_by_reextraction(monkeypatch):
    # --- UI 按鈕：呼叫端指定的 market 不得被 extract_filters 重抽的結果蓋掉 ---
    # 點按鈕後帶著 market 重跑，但問句本身沒有市場字樣，重抽必然回 None；
    # 若讓它覆寫就等於把剛按下的選擇丟掉，畫面上會再問一次
    class _FakeParsed:
        companies = []
        doc_type = news_since_days = market = None
        in_scope = True  # 與 ExtractedFilters 同步；漏了會在 extract_filters 取值時炸開
        answer_shape = "full"  # 同上，ExtractedFilters 的必要欄位，缺了會 AttributeError

    monkeypatch.setattr(
        _g, "_llms",
        lambda m: {"filters": type("F", (), {"invoke": lambda self, p: _FakeParsed()})()},
    )
    out = _g.extract_filters({"question": "台積電EPS?", "companies": ["2330"], "market": "us",
                              "lang": "zh", "model": ""})
    assert out["market"] == "us"      # 按鈕選的市場保留
    assert out["companies"] == ["2330"]   # 公司也不能被抽成空陣列，否則變全庫檢索

    # 沒有呼叫端指定時，照常採用重抽結果（不影響一般問句）
    out = _g.extract_filters({"question": "隨便問問", "lang": "zh", "model": ""})
    assert out["market"] is None and out["companies"] == []


def test_resolve_market_multi_company_no_ask_even_with_dual_listed():
    # 多標的比較時不卡市場反問——即使其中一家是雙掛牌
    s = resolve_market({"companies": ["2330", "AAPL"], "market": None})
    assert s["ask_market"] is False and route_after_resolve_market(s) == "agent"


def test_cross_market_split():
    # --- 幣別提醒的觸發：看最後要並排的代號橫不橫跨兩市場 ---
    # 多標的跨市場比較：最需要這句提醒的場合，沒有 peer_company 也要觸發
    assert cross_market_split({"companies": ["2330", "NVDA"]}) == (["2330"], ["NVDA"])
    # 雙掛牌併陳：peer_company 併進來判斷
    assert cross_market_split({"companies": ["2330"], "peer_company": "TSM",
                                "market": "both"}) == (["2330"], ["TSM"])
    # 同市場多標的不觸發，兩邊都是同一幣別
    assert cross_market_split({"companies": ["2330", "2454"]}) is None
    assert cross_market_split({"companies": ["NVDA", "AAPL"]}) is None
    # 雙掛牌但只看一邊：市場已經確定，沒有並排也就沒有換算風險
    assert cross_market_split({"companies": ["TSM"], "peer_company": "2330", "market": "us"}) is None
    # 沒指名公司不得炸掉
    assert cross_market_split({}) is None


def test_get_adr_premium_no_ratio_skips_network(monkeypatch):
    # --- ADR_RATIO 沒有對應比例的代號直接回 None，且根本不打網路 ---
    import src.market as _m

    class _BoomTicker:
        def __init__(self, *a, **k):
            raise AssertionError("ADR_RATIO 沒有比例時不應呼叫 yfinance.Ticker")

    monkeypatch.setattr(_m, "ADR_RATIO", {}, raising=False)
    assert get_adr_premium("2330", "TSM") is None

    # 就算 yfinance.Ticker 被 monkeypatch 成一呼叫就炸，也不會被走到
    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", _BoomTicker)
    assert get_adr_premium("2330", "TSM") is None


class _StubLLM:
    """generate() 真正跑到底但不打真模型，捕捉最終 prompt 供斷言。"""

    def __init__(self):
        self.last_prompt = None

    def invoke(self, prompt):
        self.last_prompt = prompt
        from langchain_core.messages import AIMessage
        return AIMessage(content="stub answer")


def _drive_generate(monkeypatch, arm: str) -> str:
    """跑一次 generate()（market=both、雙掛牌併陳），回傳送進 LLM 的完整 prompt。"""
    import src.config as _cfg

    stub = _StubLLM()
    monkeypatch.setattr(_cfg, "ADR_PREMIUM", arm)
    monkeypatch.setattr(_g, "_llms", lambda model: {"llm": stub})
    monkeypatch.setattr(_g, "get_market_snapshots",
                         lambda codes: {c: f"currentPrice: 1\ncurrency: USD" for c in codes})
    monkeypatch.setattr(_g, "get_adr_premium", lambda tw, us: "ADR premium stub text")

    state = {
        "question": "台積電台股和 ADR 的 EPS 差多少？", "lang": "zh",
        "companies": ["2330"], "peer_company": "TSM", "market": "both",
        "doc_type": None, "news_since_days": None, "answer_shape": None,
        "retrieved": [], "history": [],
    }
    _g.generate(state)
    assert stub.last_prompt is not None
    return stub.last_prompt


def test_adr_premium_off_no_block(monkeypatch):
    prompt = _drive_generate(monkeypatch, "off")
    assert "ADR 溢價" not in prompt


def test_adr_premium_block_has_block(monkeypatch):
    prompt = _drive_generate(monkeypatch, "block")
    assert "ADR 溢價" in prompt
    assert "ADR premium stub text" in prompt


def test_adr_premium_block_gating():
    # --- _adr_premium_block：off 不附；兩邊都有行情且溢價算得出來才附 ---
    import src.config as _cfg
    from src.graph import _adr_premium_block

    orig = _cfg.ADR_PREMIUM
    try:
        _cfg.ADR_PREMIUM = "off"
        assert _adr_premium_block("zh", {"2330": "s1", "TSM": "s2"}, "premium text") == ""

        _cfg.ADR_PREMIUM = "block"
        assert _adr_premium_block("zh", {"2330": "s1"}, "premium text") == ""  # 只有一邊行情
        assert _adr_premium_block("zh", {"2330": "s1", "TSM": "s2"}, None) == ""  # 溢價算不出來
        block = _adr_premium_block("zh", {"2330": "s1", "TSM": "s2"}, "premium text")
        assert "premium text" in block
        assert "ADR 溢價" in block
    finally:
        _cfg.ADR_PREMIUM = orig


def test_side_by_side_merges_peer_only_when_both():
    # --- generate() 的行情抓取清單也靠這份判斷，peer 沒併進來就會漏抓 ADR 行情 ---
    assert _side_by_side({"companies": ["2330"], "peer_company": "TSM",
                           "market": "both"}) == ["2330", "TSM"]
    # 市場已確定（非 both）：不併，行情只抓已確定的那一邊
    assert _side_by_side({"companies": ["TSM"], "peer_company": "2330",
                           "market": "us"}) == ["TSM"]
    assert _side_by_side({"companies": ["2330", "2454"]}) == ["2330", "2454"]
    assert _side_by_side({}) == []
