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

# companies 的正規化不受影響（同一個 model 上兩個 validator）
assert ExtractedFilters(companies=["台積電"], news_since_days=7).news_since_days == 7

# 「台積電」不是合法代號格式，normalize_ticker 認不得就丟掉
assert ExtractedFilters(companies=["台積電"]).companies == []

# 多標的：逐項正規化並去重、保序；認不得的代號丟掉
assert ExtractedFilters(companies=["aapl", "2330.TW", "AAPL", "台積電"]).companies == ["AAPL", "2330"]

print("ExtractedFilters self-check OK")

# --- extract_filters 的模型選擇（A/B 開關）---
# 換小模型的臂靠 config.FILTERS_MODEL 切換。抽錯代號會讓整條流程查錯公司，
# 所以這裡固定住「空值沿用主模型、有值才覆蓋」，避免開關寫錯時兩臂其實跑同一個模型
# 而量出假的「沒有差異」。
import src.config as config
import src.graph as graph

_calls = []


class _FakeFilters:
    def invoke(self, prompt):
        return ExtractedFilters(companies=["AAPL"])


def _fake_llms(model):
    _calls.append(model)
    return {"filters": _FakeFilters()}


_real_llms, _real_filters_model = graph._llms, config.FILTERS_MODEL
graph._llms = _fake_llms
try:
    state = {"question": "蘋果最近的財報表現如何？", "companies": [], "market": None,
             "model": "main-model"}

    # 空值：沿用該輪的主模型（UI 選單選的那個）
    config.FILTERS_MODEL = ""
    graph.extract_filters(dict(state))
    assert _calls[-1] == "main-model", _calls

    # 有值：覆蓋主模型，兩臂才真的不同
    config.FILTERS_MODEL = "small-model"
    graph.extract_filters(dict(state))
    assert _calls[-1] == "small-model", _calls

    # 主模型留空（舊呼叫端沒帶 model）時仍退回預設，不會傳空字串給 Ollama
    config.FILTERS_MODEL = ""
    graph.extract_filters({**state, "model": ""})
    assert _calls[-1] == config.LLM_MODEL, _calls
finally:
    graph._llms, config.FILTERS_MODEL = _real_llms, _real_filters_model

print("extract_filters model switch self-check OK")
