"""離題判斷：不打 DB，測 in_scope 的分岔與路由。

「in_scope 判得準不準」是模型行為問題，由 probe 腳本打真實模型驗證（22 題全對）；
這支只測邏輯：有指名公司不判離題、欄位缺漏時的預設、路由走對節點。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import graph


# --- _is_off_topic ---
# in_scope=False 且沒指名公司 → 離題
assert graph._is_off_topic({"question": "今天天氣如何", "company": None, "in_scope": False})

# in_scope=True → 一律不判離題
assert graph._is_off_topic(
    {"question": "法說會通常看什麼", "company": None, "in_scope": True}) is False

# 有指名公司 → 不判離題。company 過濾本身最強，庫內沒這家會回空走補抓，
# 不該在這裡攔下（模型把「台達電財報」誤判成 out of scope 時尤其要保住這條）
assert graph._is_off_topic(
    {"question": "台達電財報", "company": "2308", "in_scope": False}) is False

# 欄位缺漏（舊 state / 結構化輸出降級）→ 當成 in_scope，不拒答
assert graph._is_off_topic({"question": "隨便問問"}) is False
assert graph._is_off_topic({}) is False


# --- 路由三個出口 ---
assert graph.route_after_resolve_market({"ask_market": True}) == "ask_market"
assert graph.route_after_resolve_market({"off_topic": True}) == "off_topic"
assert graph.route_after_resolve_market({}) == "agent"
# 反問市場優先於離題：雙掛牌問句本來就抽得出公司，不該被判離題
assert graph.route_after_resolve_market(
    {"ask_market": True, "off_topic": True}) == "ask_market"


# --- off_topic 節點 ---
out = graph.off_topic({"question": "今天天氣", "lang": "zh", "retrieved": [{"id": 1}]})
assert out["retrieved"] == [], "離題不得留下檢索結果，否則會走 generate"
assert "財經" in out["answer"]
assert "scope of financial data" in graph.off_topic({"lang": "en"})["answer"]


# --- ExtractedFilters 預設值 ---
# 模型漏填 in_scope 時必須預設 True——誤判成離題會讓正常問題直接被拒答
assert graph.ExtractedFilters().in_scope is True

print("test_off_topic: all passed")
