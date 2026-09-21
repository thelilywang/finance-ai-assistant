"""最小 self-check：三個 MCP tool 的回傳格式與參數傳遞。

tool 是 async def（MCP 規範），所以用 asyncio.run 呼叫，與其他同步測試略有差異。
不測 LLM 會不會依 docstring 正確選用 tool——那需要真實 Ollama 且結果不確定，屬手動驗證。
執行：python tests/test_mcp_tools.py
"""
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.mcp_server as mcp_server
from src.update import FetchResult

TODAY = dt.date.today()
chunks = [
    {"id": 1, "source": "EDGAR:AAPL:x", "title": None, "doc_type": "financial_report",
     "company": "AAPL", "published_at": TODAY - dt.timedelta(days=60), "content": "財報內容"},
    {"id": 2, "source": "https://news/1", "title": "新聞標題", "doc_type": "news",
     "company": "AAPL", "published_at": TODAY - dt.timedelta(days=1), "content": "新聞內容"},
]

# --- search_knowledge_base：回傳 JSON 須同時給 LLM 讀的文字與程式用的結構化 chunks ---
mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None: chunks
out = json.loads(asyncio.run(mcp_server.search_knowledge_base("AAPL 財報", "AAPL")))
assert set(out) == {"summary_for_llm", "chunks"}
assert len(out["chunks"]) == len(chunks)  # 原封不動帶回，generate 要靠它組來源編號
assert "EDGAR:AAPL:x" in out["summary_for_llm"]

# 時效性判斷的關鍵：LLM 讀得到日期卻不會自己跟今天相減，所以要直接給「距今 N 天」與今天日期
summary = out["summary_for_llm"]
assert f"今天是 {TODAY}" in summary
assert "距今 60 天" in summary
assert "距今 1 天" in summary
# 時效結論只看新聞：財報 60 天不該被拿來當過期依據（實測模型會混用兩者的天數）
# 有指名公司時 header 會標明是哪家的新聞，免得模型把別家的新鮮度當成這家的
assert "最新的 AAPL 的「新聞」距今 1 天" in summary
assert "[財報｜EDGAR:AAPL:x]" in summary and "[新聞｜https://news/1]" in summary

# 時效只算查詢公司自己的新聞：retrieve_context 會補進其他公司與全域市場新聞，
# 那些通常更新，混進來會讓 header 報出別家的新鮮度，使用者問 AAPL 卻被告知
# 「距今 0 天」（其實是別家的新聞）而不去補抓
mixed = chunks + [
    {"id": 3, "source": "https://news/global", "title": "大盤", "doc_type": "news",
     "company": None, "published_at": TODAY, "content": "全域新聞"},
    {"id": 4, "source": "https://news/other", "title": "他家", "doc_type": "news",
     "company": "MSFT", "published_at": TODAY, "content": "別家新聞"},
]
mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None: mixed
mixed_summary = json.loads(
    asyncio.run(mcp_server.search_knowledge_base("AAPL 新聞", "AAPL"))
)["summary_for_llm"]
assert "最新的 AAPL 的「新聞」距今 1 天" in mixed_summary, mixed_summary
assert "距今 0 天" not in mixed_summary.split("以下是檢索結果")[0]

# 不指名公司時維持原行為：全部新聞一起算，取最新的 0 天
mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None: mixed
any_summary = json.loads(
    asyncio.run(mcp_server.search_knowledge_base("大盤新聞"))
)["summary_for_llm"]
assert "最新的「新聞」距今 0 天" in any_summary, any_summary

mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None: chunks

# 只給 N 讓模型自己比門檻不夠：實測報 N=17 仍直接收工，故把結論一起寫進 header。
# 門檻與 docstring 的判準必須一致，否則等於給模型兩套互相矛盾的說明。
def _fresh_line(days_ago, news_since_days=None):
    mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None: [
        {"id": 1, "source": "s", "title": None, "doc_type": "news", "company": "AAPL",
         "published_at": TODAY - dt.timedelta(days=days_ago), "content": "新聞"}]
    s = json.loads(asyncio.run(
        mcp_server.search_knowledge_base("x", "AAPL", None, news_since_days)
    ))["summary_for_llm"]
    return s.split("以下是檢索結果")[0]

assert "不需補抓" in _fresh_line(3), _fresh_line(3)           # N=3，門檻 3 → 不補
assert "請呼叫 fetch_company_data" in _fresh_line(4), _fresh_line(4)   # N=4 → 補
assert "請呼叫 fetch_company_data" in _fresh_line(17), _fresh_line(17)  # 實測的 2454
# 問題要求近期（時效窗 <= 7）時門檻收緊到當天
assert "不需補抓" in _fresh_line(0, 7)
assert "請呼叫 fetch_company_data" in _fresh_line(2, 7), _fresh_line(2, 7)
# 時效窗 90 天不算要求當天，仍走 3 天門檻
assert "不需補抓" in _fresh_line(2, 90)

# 只有財報沒有新聞時要明講，否則模型會誤以為新聞夠新
mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None: [chunks[0]]
only_report = json.loads(asyncio.run(mcp_server.search_knowledge_base("x")))
assert "沒有任何新聞" in only_report["summary_for_llm"]

# 日期不明的資料不應該炸，也不該硬掰天數
mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None: [
    {"id": 3, "source": "s", "title": None, "doc_type": "news",
     "company": None, "published_at": None, "content": "無日期"}
]
no_date = json.loads(asyncio.run(mcp_server.search_knowledge_base("x")))
assert "發布日期：不明" in no_date["summary_for_llm"]

# doc_type 只接受單一合法值：LLM 實測會塞 "financial_report,news"，那樣過濾會查空
seen = {}
mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None: seen.update(doc_type=d) or chunks
asyncio.run(mcp_server.search_knowledge_base("x", None, "financial_report,news"))
assert seen["doc_type"] is None  # 多值 → 不過濾，而非照字面查
asyncio.run(mcp_server.search_knowledge_base("x", None, "news"))
assert seen["doc_type"] == "news"  # 單一合法值照常傳遞
asyncio.run(mcp_server.search_knowledge_base("x", None, "亂填"))
assert seen["doc_type"] is None

# market 同樣只接受 "tw"/"us"：模型填錯字時寧可不過濾，也不要因為猜錯市場查出空結果
seen = {}
mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None: seen.update(market=m) or chunks
asyncio.run(mcp_server.search_knowledge_base("x", None, None, None, "us"))
assert seen["market"] == "us"  # 合法值照常傳遞到檢索層
asyncio.run(mcp_server.search_knowledge_base("x", None, None, None, "both"))
assert seen["market"] is None  # "both"＝兩邊都要，不可當成市場值過濾
asyncio.run(mcp_server.search_knowledge_base("x", None, None, None, "TW"))
assert seen["market"] is None  # 大小寫不符一律視為不過濾
asyncio.run(mcp_server.search_knowledge_base("x", None, None, None))
assert seen["market"] is None  # 沒填就是不限市場

# 查無資料時仍是合法 JSON，chunks 為空
mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None: []
empty = json.loads(asyncio.run(mcp_server.search_knowledge_base("無此標的")))
assert empty["chunks"] == []
assert "查無" in empty["summary_for_llm"]

# --- fetch_company_data：正規化 ticker、依既有財報決定 has_report ---
calls = {}
mcp_server.fetch_missing_data = lambda company, has_report: (
    calls.update(company=company, has_report=has_report) or ["已匯入財報", "新聞更新完成"]
)

mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None: []  # 沒有既有財報
assert asyncio.run(mcp_server.fetch_company_data("2330")) == "已匯入財報；新聞更新完成"
assert calls == {"company": "2330", "has_report": False}

mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None: chunks  # 已有財報 → 只補新聞
asyncio.run(mcp_server.fetch_company_data("aapl.us"))  # 順便驗證後綴會被正規化掉
assert calls == {"company": "AAPL", "has_report": True}

# 「有財報」不等於「財報夠新」：過期的財報必須重抓，否則一份舊財報會永遠擋住更新
def _report(days_ago):
    return [{"id": 1, "source": "s", "title": None, "doc_type": "financial_report",
             "company": "AAPL",
             "published_at": None if days_ago is None else TODAY - dt.timedelta(days=days_ago),
             "content": "財報"}]

for days, expected in [(89, True), (120, True), (121, False), (229, False), (None, False)]:
    mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None, _d=days: _report(_d)
    asyncio.run(mcp_server.fetch_company_data("AAPL"))
    assert calls["has_report"] is expected, (days, calls)

# 代號格式不符時不應打外部來源
calls.clear()
assert "無法辨識" in asyncio.run(mcp_server.fetch_company_data("這不是代號"))
assert calls == {}

# --- 觀測：記下的 N 必須與 header 報的 N 一致 ---
# 這兩行 log 是用來判斷「該補沒補」的成因，記錯了比沒記更糟：會把稀釋問題誤判成
# 模型不照 tool 說明做。故直接比對記下的 news_age_min 與 summary 裡的數字。
import logging

seen = []
logging.getLogger("mcp_tools").addHandler(
    type("H", (logging.Handler,), {"emit": lambda self, r: seen.append(r)})()
)

mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None: mixed
seen.clear()
s = json.loads(asyncio.run(mcp_server.search_knowledge_base("AAPL 新聞", "AAPL")))["summary_for_llm"]
kb = [r for r in seen if r.msg == "search_knowledge_base"]
assert len(kb) == 1, kb
f = kb[0].fields
assert f["company"] == "AAPL", f          # LLM 實填的 company，稀釋與否全看它
assert f["news_age_min"] == 1, f          # 與 header 的「距今 1 天」一致
assert f"距今 {f['news_age_min']} 天" in s.split("以下是檢索結果")[0]
assert 0 not in f["news_ages"], f         # 別家的 0 天不得混進這家的清單

# 查無資料時不得炸掉，N 記為 None
mcp_server.retrieve_context = lambda q, c=None, d=None, n=None, m=None: []
seen.clear()
asyncio.run(mcp_server.search_knowledge_base("查無", "ZZZZ"))
assert [r for r in seen if r.msg == "search_knowledge_base"][0].fields["news_age_min"] is None

# --- fetch_market_overview：取 FetchResult.detail ---
mcp_server.fetch_market_news = lambda limit: FetchResult(True, "市場新聞更新完成，共寫入 5 筆")
assert asyncio.run(mcp_server.fetch_market_overview()) == "市場新聞更新完成，共寫入 5 筆"

print("mcp tools self-check OK")
