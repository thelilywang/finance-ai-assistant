"""get_market_snapshots 的成功/失敗家數語意，不碰網路。"""
from src import market


def test_market_snapshots_semantics(monkeypatch):
    calls = []

    def fake(company):
        calls.append(company)
        return None if company.startswith("BAD") else f"snapshot of {company}"

    monkeypatch.setattr(market, "get_market_snapshot", fake)

    # 全成功 -> 三筆、key 正確
    assert market.get_market_snapshots(["2330", "2454", "AAPL"]) == {
        "2330": "snapshot of 2330",
        "2454": "snapshot of 2454",
        "AAPL": "snapshot of AAPL",
    }

    # 部分失敗 -> 失敗的 key 不存在，成功的仍在
    partial = market.get_market_snapshots(["2330", "BAD1"])
    assert partial == {"2330": "snapshot of 2330"}, partial

    # 全失敗 -> 空 dict
    assert market.get_market_snapshots(["BAD1", "BAD2"]) == {}

    # 空 list -> 空 dict，且完全不呼叫底層（不起 executor）
    calls.clear()
    assert market.get_market_snapshots([]) == {}
    assert calls == []
