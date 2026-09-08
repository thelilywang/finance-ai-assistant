"""LangGraph 主流程。

Graph 結構：
    rewrite_question -> extract_filters -> agent <-> tools -> assemble -> (generate | no_result)

- rewrite_question: 多輪對話時把追問改寫成獨立問題，讓 embedding 檢索有效
- extract_filters: 用 LLM 從問題中抽出公司代號/文件類型，供 agent 呼叫 tool 時當已知條件
- agent: 把 MCP tool 綁給 LLM，由 LLM 自行決定檢索/補抓、要不要再呼叫下一個 tool
- tools: 執行 LLM 選定的 MCP tool（ToolNode）
- assemble: 把 tool 回傳結果整理回 retrieved/fetch_results，供下游節點沿用既有格式
- generate: 根據檢索到的 chunk 生成回答，並附上出處來源
- no_result: 找不到相關資料時，誠實告知使用者，避免幻覺

「資料夠不夠新、要不要補抓」不再由程式規則判斷（原 needs_refetch/route_after_retrieve），
改由 LLM 讀 MCP tool 的說明自行決定，判斷準則寫在 src/mcp_server.py 的 tool docstring。
"""
from __future__ import annotations

import datetime as dt
import json
import re
from functools import lru_cache
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, field_validator

from . import config
from .i18n import t
from .market import get_market_snapshot
from .tickers import is_tw_ticker, normalize_ticker
from .vectorstore import similarity_search


class GraphState(TypedDict):
    question: str
    history: list[tuple[str, str]]  # [(user, assistant), ...] 由呼叫端傳入
    company: str | None
    doc_type: str | None
    retrieved: list[dict]
    answer: str
    fetched: bool  # 本輪是否呼叫過補抓 tool，no_result 用來決定提示語
    fetch_results: list[str]  # 各補抓 tool 的結果訊息，no_result 用來提示抓取是否失敗
    lang: str
    model: str  # 本輪使用的 Ollama 模型，由 UI 選單決定；空值則用 config.LLM_MODEL
    messages: Annotated[list[BaseMessage], add_messages]  # agent <-> tools 的往返記錄


# reasoning=False 關閉推理段。曾評估對 generate 開啟以顯示推理過程（可解釋性），
# 實測在 qwen3.5:9b 上代價無法接受：單題 186s→1245s，光 generate 就從 87s 變 1053s
# （模型為一句營收問題寫了 30891 字推理，是答案的 21 倍），且首個 token 從 108s 延後
# 到 238s，連體感延遲都更差。壓制推理長度的兩條路也都試過：reasoning='low' 對
# qwen3.5 無效（推理字數與 True 完全相同，層級控制僅 gpt-oss 支援），num_predict
# 則是推理先吃光額度、答案被截成空字串（done_reason=length）。換模型再重新評估。
def _model_of(state: GraphState) -> str:
    """本輪要用的模型。UI 沒選（或舊呼叫端沒帶）就退回預設。"""
    return state.get("model") or config.LLM_MODEL


@lru_cache(maxsize=8)
def _llms(model: str) -> dict:
    """建立某個模型的三個實例。lru_cache 讓同一模型的多個 session 共用，換模型才新建。"""
    base = ChatOllama(
        model=model, base_url=config.OLLAMA_BASE_URL, temperature=0, reasoning=False
    )
    return {
        # with_retry：Ollama 模型冷啟動/短暫逾時時重試，避免整個 graph 節點直接中斷對話
        "llm": base.with_retry(stop_after_attempt=3),
        "filters": base.with_structured_output(ExtractedFilters).with_retry(
            stop_after_attempt=3
        ),
        # tool-calling 專用：reasoning=False 會讓模型把「我要呼叫某工具」寫成文字而非
        # 產生結構化 tool_calls（實測 A/B：關推理時同一情境完全不發 tool call，開啟則
        # 正常），因此 agent 節點不能沿用關掉推理的實例。
        "tool": ChatOllama(model=model, base_url=config.OLLAMA_BASE_URL, temperature=0),
    }


embeddings = OllamaEmbeddings(model=config.EMBEDDING_MODEL, base_url=config.OLLAMA_BASE_URL)


def _format_history(history: list[tuple[str, str]]) -> str:
    """把最近 3 輪對話排成「使用者/助理」逐行文字。"""
    lines = []
    for user, assistant in history[-3:]:
        lines.append(f"使用者: {user}")
        lines.append(f"助理: {assistant}")
    return "\n".join(lines)


def rewrite_question(state: GraphState) -> GraphState:
    """有對話歷史時，把追問改寫成不依賴上下文的獨立問題；沒有就直接通過。"""
    if not state.get("history"):
        return state

    prompt = f"""以下是使用者與財經助理的對話紀錄，以及使用者的新問題。
若新問題依賴上下文（例如「那毛利率呢？」），請改寫成一個不依賴上下文、可獨立理解的完整問題；
若新問題本身已經獨立完整，原樣輸出即可。只輸出改寫後的問題，不要有其他文字。

對話紀錄：
{_format_history(state["history"])}

新問題：{state['question']}
"""
    rewritten = _llms(_model_of(state))["llm"].invoke(prompt).content.strip()
    return {**state, "question": rewritten or state["question"]}


class ExtractedFilters(BaseModel):
    status: Literal["ok", "error"] = "ok"
    error_message: str | None = None
    company: str | None = None
    doc_type: Literal["financial_report", "news"] | None = None

    @field_validator("company")
    @classmethod
    def _normalize_company(cls, v: str | None) -> str | None:
        return normalize_ticker(v) if v else None


def extract_filters(state: GraphState) -> GraphState:
    """從問題中抽取公司代號 / 文件類型，抽不出來就設為 None（不過濾）。"""
    prompt = f"""你是財經助理的前處理模組。請從使用者問題中判斷：
1. company: 台股代號（4-6 碼數字，如 "2330"）或美股 ticker（1-5 個大寫英文字母，如 "AAPL"），
   沒有明確提到就設為 null；公司名稱要轉成代號/ticker（如 台積電→"2330"、蘋果→"AAPL"）
2. doc_type: "financial_report"（財報相關）或 "news"（新聞相關），不確定就設為 null
3. 若問題同時指名多個不同公司，company 設為 null，status 設為 "error"，
   error_message 說明偵測到哪些標的、目前僅支援單一標的查詢
4. 正常情況（含完全抽不到 company 的情況）status 設為 "ok"，error_message 設為 null

使用者問題：{state['question']}
"""
    try:
        parsed = _llms(_model_of(state))["filters"].invoke(prompt)
    except Exception as e:  # noqa: BLE001  結構化輸出解析失敗（模型偏離格式）時降級成不過濾
        print(f"[extract_filters] 結構化輸出失敗：{e}")
        return {**state, "company": None, "doc_type": None}

    if parsed.status == "error":
        print(f"[extract_filters] {parsed.error_message}")

    return {**state, "company": parsed.company, "doc_type": parsed.doc_type}


# ponytail: 關鍵字啟發式判斷時效性，要更準再交給 extract_filters 的 LLM 判斷
_RECENT_RE = re.compile(r"最近|近期|這幾天|本週|近日|最新|即時|今天|重抓|更新|recent|lately|latest|today", re.I)


def retrieve_context(question: str, company: str | None = None, doc_type: str | None = None) -> list[dict]:
    """向量檢索 + 既有的補資料規則（doc_type 濾空放寬重查、財報補新聞、補全域市場新聞）。

    不依賴 GraphState，供 LangGraph 節點與未來的 MCP tool 共用。
    """
    recent = _RECENT_RE.search(question)
    query_vec = embeddings.embed_query(question)
    docs = similarity_search(
        query_vec, company=company, doc_type=doc_type,
        news_since_days=90 if recent else None,
    )
    if not docs and doc_type:
        # ponytail: doc_type 濾到空就放寬重查，避免問「財報」時把僅有的新聞全濾光
        docs = similarity_search(
            query_vec, company=company,
            news_since_days=90 if recent else None,
        )
    if company and docs and not any(d["doc_type"] == "news" for d in docs):
        # ponytail: 財報問題也補 3 條新聞給趨勢段當素材，沒有就交給 LLM 決定要不要補抓
        news = similarity_search(
            query_vec, top_k=3, company=company, doc_type="news",
            news_since_days=90 if recent else None,
        )
        docs = docs + news
    if company and docs:
        # ponytail: 補 2 條全域市場新聞給決策卡當市場脈絡（market-news 入庫多為 company=NULL）
        seen_ids = {d["id"] for d in docs}
        market = similarity_search(query_vec, top_k=2, doc_type="news",
                                   news_since_days=90 if recent else None)
        docs = docs + [d for d in market if d["id"] not in seen_ids]
    return docs


def fetch_missing_data(company: str | None, has_report: bool) -> list[str]:
    """company 為 None 時只補市場總覽新聞；has_report=True 時只補新聞不重抓財報。

    不依賴 GraphState，供 LangGraph 節點與未來的 MCP tool 共用。單一來源失敗不中斷，
    回傳每個來源的結果訊息（成功或失敗皆含），供呼叫端判斷是否要提示使用者。
    """
    try:
        from .update import fetch_edgar, fetch_mops, fetch_news, fetch_market_news  # 延遲 import，避免循環依賴
    except ImportError as e:  # 環境缺套件時降級成不抓，不炸整個對話
        msg = f"匯入失敗（環境缺套件？）：{e}"
        print(f"[auto_fetch] {msg}")
        return [msg]

    calls = []
    if company:
        if is_tw_ticker(company):
            calls = [lambda: fetch_mops(company), lambda: fetch_news(company)]
        else:
            calls = [lambda: fetch_edgar(company.upper()), lambda: fetch_news(company.upper())]
        # 已有該公司財報才只補新聞；只有新聞時財報照抓（原本檢查整個 retrieved，害外國發行人的財報永遠沒抓）
        if has_report:
            calls = calls[-1:]
    # ponytail: 市場總覽新聞一律補掃，source_exists 會跳過已入庫的，重複觸發便宜
    calls.append(lambda: fetch_market_news(3))

    results = []
    for call in calls:
        try:
            results.append(call().detail)
        except Exception as e:  # noqa: BLE001  單一來源失敗不中斷
            msg = f"抓取失敗：{e}"
            print(f"[auto_fetch] {msg}")
            results.append(msg)
    return results


# ponytail: tool 呼叫輪數上限，取代原本 fetched 布林的「只重試一次」保護。
# LLM 補抓失敗時可能反覆重試，每次都是真實的外部網路請求，必須有硬上限。
_MAX_TOOL_ROUNDS = 4

_mcp_client = MultiServerMCPClient({
    "finance": {
        "transport": "streamable_http",
        "url": config.MCP_SERVER_URL,
        "headers": (
            {"Authorization": f"Bearer {config.MCP_AUTH_TOKEN}"}
            if config.MCP_AUTH_TOKEN else None
        ),
    }
})


def _seed_prompt(state: GraphState) -> str:
    """組 agent 首次進入迴圈的引導訊息，把已知條件交代清楚免得 LLM 重猜。

    # ponytail: 一定要帶今天日期——實測模型會正確讀出資料的發布日期，卻因為不知道
    # 今天是哪天而判定兩個月前的資料「已足夠」，導致該補抓時沒補抓。
    """
    known = [f"今天日期：{dt.date.today()}"]
    if state.get("company"):
        known.append(f"已知公司代號：{state['company']}")
    if state.get("doc_type"):
        known.append(f"已知文件類型：{state['doc_type']}")
    known_block = "\n".join(known)
    return f"""使用者問題：{state['question']}
{known_block}

請用工具查詢財經資料庫回答上述問題所需的資料。檢索結果會標明每筆資料距今幾天，
請依工具說明判斷是否夠新；不夠新就補抓後再查一次。
取得足夠資料後就停止呼叫工具即可，不需要自己寫出回答——後續會有另一個步驟根據你查到的
資料生成最終回覆。"""


async def agent(state: GraphState) -> GraphState:
    """把 MCP tool 綁給 LLM，由它自行決定要呼叫哪個 tool、要不要再呼叫下一個。"""
    tools = await _mcp_client.get_tools()
    messages = state.get("messages") or [HumanMessage(content=_seed_prompt(state))]
    resp = await _llms(_model_of(state))["tool"].bind_tools(tools).ainvoke(messages)
    return {**state, "messages": [resp]}


def agent_route(state: GraphState) -> str:
    """LLM 還要呼叫 tool 就去 tools，否則收工；超過輪數上限一律強制收工。"""
    rounds = sum(1 for m in state["messages"] if isinstance(m, AIMessage) and m.tool_calls)
    if rounds >= _MAX_TOOL_ROUNDS:
        print(f"[agent] 已達 tool 呼叫輪數上限（{_MAX_TOOL_ROUNDS}），停止呼叫工具。")
        return "assemble"
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else "assemble"


def _tool_text(content) -> str:
    """取出 ToolMessage 的文字內容。

    MCP tool 經 langchain-mcp-adapters 回來的是 content block 陣列
    （[{"type": "text", "text": ...}]），本地 tool 則是純字串，兩種都要能讀。
    """
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return str(content)


def assemble(state: GraphState) -> GraphState:
    """把 tool 回傳結果整理回下游節點沿用的既有欄位。

    retrieved 取最後一次 search_knowledge_base 的 chunks（工具已回傳結構化資料，
    不再重查一次）；補抓類 tool 的訊息填進 fetched/fetch_results 供 no_result 使用。
    """
    retrieved: list[dict] = []
    fetch_results: list[str] = []
    fetched = False
    for msg in state["messages"]:
        if not isinstance(msg, ToolMessage):
            continue
        if msg.name == "search_knowledge_base":
            try:
                retrieved = json.loads(_tool_text(msg.content)).get("chunks", [])
            except (json.JSONDecodeError, TypeError, AttributeError) as e:
                print(f"[assemble] 解析檢索結果失敗，視為查無資料：{e}")
        elif msg.name in ("fetch_company_data", "fetch_market_overview"):
            fetched = True
            fetch_results.append(_tool_text(msg.content))
    return {**state, "retrieved": retrieved, "fetched": fetched, "fetch_results": fetch_results}


def route_after_assemble(state: GraphState) -> str:
    return "generate" if state["retrieved"] else "no_result"


def unique_sources(retrieved: list[dict]) -> list[str]:
    """依出現順序去重的來源列表，引用編號與來源列表共用這個順序。"""
    ordered = []
    for doc in retrieved:
        if doc["source"] not in ordered:
            ordered.append(doc["source"])
    return ordered


def generate(state: GraphState) -> GraphState:
    lang = state.get("lang", "zh")
    src_label = t(lang, "citation_label")  # 引用標記跟隨回答語言（[來源1] / [Source 1]）
    ordered = unique_sources(state["retrieved"])
    context_blocks = []
    for idx, src in enumerate(ordered, start=1):
        docs = [d for d in state["retrieved"] if d["source"] == src]
        date = docs[0].get("published_at") or "日期未知"
        contents = "\n".join(d["content"] for d in docs)
        context_blocks.append(f"[{src_label}{idx}] {src}（{date}）\n{contents}")
    context = "\n\n".join(context_blocks)

    history_block = ""
    if state.get("history"):
        history_block = f"\n先前對話（僅供理解語境）：\n{_format_history(state['history'])}\n"

    market_block = ""
    if state.get("company"):
        snapshot = get_market_snapshot(state["company"])
        if snapshot:
            market_block = f"\n即時市場數據（Yahoo Finance，僅供估值/時機參考，非檢索來源，不參與來源編號）：\n{snapshot}\n"

    prompt = f"""你是專業的財經分析助理。請根據下方參考資料回答使用者問題。
規則：
- 只根據參考資料回答，不要編造資料中沒有的數字或事實
- 回答中明確標示引用的來源編號，例如「根據[{src_label}1]...」
- 引用編號僅限 [{src_label}1] 到 [{src_label}{len(ordered)}]，不得使用其他編號
- 如果參考資料不足以完整回答，誠實說明還缺什麼資訊
- 回答務必簡潔：先給結論，最多 2-3 段、每段不超過 3 句，段落間空一行，不要展示推敲過程
- 回答時區分【已知事實】（附來源編號）與【推論】，不確定的事明說不確定
- 不得輸出信心百分比；所有數字必須出自參考資料或即時市場數據，不得自行估算
- 即使資料有限，也要給出可執行的觀察建議（觸發條件、關鍵事件、追蹤指標），不得整段棄權
{t(lang, "answer_lang_rule")}

輸出格式（嚴格遵守）：
1. 先簡潔回答問題
2. 然後固定追加以下一節：

{t(lang, "trend_section")}

{t(lang, "disclaimer")}

參考資料：
{context}
{market_block}{history_block}
使用者問題：{state['question']}
"""
    resp = _llms(_model_of(state))["llm"].invoke(prompt)
    return {**state, "answer": resp.content}


def no_result(state: GraphState) -> GraphState:
    lang = state.get("lang", "zh")
    if state.get("fetched"):
        answer = t(lang, "no_result_fetched", company=state.get("company"))
        results = state.get("fetch_results") or []
        if results:
            answer += "\n\n" + "\n".join(f"- {r}" for r in results)
    else:
        answer = t(lang, "no_result_plain")
    if state.get("company"):
        snapshot = get_market_snapshot(state["company"])
        if snapshot:
            answer += "\n\n" + t(lang, "no_result_market", snapshot=snapshot)
    return {**state, "answer": answer}


async def build_graph():
    """建 graph。async 是因為要先跟 MCP server 拿 tool 清單（連不上會 raise，由呼叫端處理）。"""
    tools = await _mcp_client.get_tools()

    graph = StateGraph(GraphState)
    graph.add_node("rewrite_question", rewrite_question)
    graph.add_node("extract_filters", extract_filters)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("assemble", assemble)
    graph.add_node("generate", generate)
    graph.add_node("no_result", no_result)

    graph.set_entry_point("rewrite_question")
    graph.add_edge("rewrite_question", "extract_filters")
    graph.add_edge("extract_filters", "agent")
    graph.add_conditional_edges(
        "agent", agent_route, {"tools": "tools", "assemble": "assemble"},
    )
    graph.add_edge("tools", "agent")  # 執行完回 agent 決定要不要再呼叫；輪數上限保證會收斂
    graph.add_conditional_edges(
        "assemble", route_after_assemble,
        {"generate": "generate", "no_result": "no_result"},
    )
    graph.add_edge("generate", END)
    graph.add_edge("no_result", END)

    return graph.compile()
