"""LangGraph 主流程。

Graph 結構：
    rewrite_question -> extract_filters -> retrieve -> (generate | auto_fetch -> retrieve | no_result)

- rewrite_question: 多輪對話時把追問改寫成獨立問題，讓 embedding 檢索有效
- extract_filters: 用 LLM 從問題中抽出公司代號/文件類型，作為檢索 filter
- retrieve: 把問題 embedding 後去 pgvector 找最相似的 chunk
- auto_fetch: 檢索不到且問題有指名公司時，自動抓財報/新聞入庫後重新檢索（只重試一次）
- generate: 根據檢索到的 chunk 生成回答，並附上出處來源
- no_result: 找不到相關資料時，誠實告知使用者，避免幻覺
"""
from __future__ import annotations

import json
import re
from typing import TypedDict

from langchain_ollama import ChatOllama, OllamaEmbeddings
from langgraph.graph import StateGraph, END

from . import config
from .i18n import t
from .vectorstore import similarity_search


class GraphState(TypedDict):
    question: str
    history: list[tuple[str, str]]  # [(user, assistant), ...] 由呼叫端傳入
    company: str | None
    doc_type: str | None
    retrieved: list[dict]
    answer: str
    fetched: bool  # auto_fetch 是否已執行過（保證只重試一次）
    lang: str


# reasoning=False 關閉 qwen3.5 的 <think> 推理段，避免污染 JSON 解析與串流輸出
llm = ChatOllama(
    model=config.LLM_MODEL, base_url=config.OLLAMA_BASE_URL, temperature=0, reasoning=False
)
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
    if re.search(r"(?<!\d)\d{4}(?!\d)|(?<![A-Za-z])[A-Z]{2,5}(?![A-Za-z])", state["question"]):
        return state  # ponytail: 已指名公司代號/ticker，視為獨立問題，避免被歷史污染

    prompt = f"""以下是使用者與財經助理的對話紀錄，以及使用者的新問題。
若新問題依賴上下文（例如「那毛利率呢？」），請改寫成一個不依賴上下文、可獨立理解的完整問題；
若新問題本身已經獨立完整，原樣輸出即可。只輸出改寫後的問題，不要有其他文字。

對話紀錄：
{_format_history(state["history"])}

新問題：{state['question']}
"""
    rewritten = llm.invoke(prompt).content.strip()
    return {**state, "question": rewritten or state["question"]}


def extract_filters(state: GraphState) -> GraphState:
    """從問題中抽取公司代號 / 文件類型，抽不出來就設為 None（不過濾）。"""
    prompt = f"""你是財經助理的前處理模組。請從使用者問題中判斷：
1. company: 台股代號（4 碼數字，如 "2330"）或美股 ticker（1-5 個大寫英文字母，如 "AAPL"、"TSLA"），
   沒有明確提到就填 null；公司名稱要轉成代號/ticker（如 台積電→"2330"、蘋果→"AAPL"）
2. doc_type: "financial_report"（財報相關）或 "news"（新聞相關），不確定就填 null

只回傳 JSON，不要有其他文字，格式：
{{"company": "2330" 或 "AAPL" 或 null, "doc_type": "financial_report" 或 "news" 或 null}}

使用者問題：{state['question']}
"""
    resp = llm.invoke(prompt).content.strip()
    try:
        # 有些模型會包 markdown code block，去掉
        cleaned = resp.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, AttributeError):
        parsed = {"company": None, "doc_type": None}

    def _clean(v):  # 模型偶爾回字串 "null"，一律正規化成 None
        return None if not v or (isinstance(v, str) and v.strip().lower() == "null") else v

    company = _clean(parsed.get("company"))
    if not company:
        # ponytail: LLM 漏抽時的確定性 fallback；純英文問題可能誤抓一般單字，屆時改成僅在含中文時啟用
        m = re.search(r"(?<![A-Za-z])[A-Za-z]{1,5}(?![A-Za-z])", state["question"])
        if m:
            company = m.group(0).upper()

    return {**state, "company": company, "doc_type": _clean(parsed.get("doc_type"))}


def retrieve(state: GraphState) -> GraphState:
    # ponytail: 關鍵字啟發式判斷時效性，要更準再交給 extract_filters 的 LLM 判斷
    recent = re.search(r"最近|近期|這幾天|本週|近日|最新|recent|lately|latest", state["question"], re.I)
    query_vec = embeddings.embed_query(state["question"])
    docs = similarity_search(
        query_vec, company=state.get("company"), doc_type=state.get("doc_type"),
        news_since_days=90 if recent else None,
    )
    if not docs and state.get("doc_type"):
        # ponytail: doc_type 濾到空就放寬重查，避免問「財報」時把僅有的新聞全濾光
        docs = similarity_search(
            query_vec, company=state.get("company"),
            news_since_days=90 if recent else None,
        )
    if state.get("company") and docs and not any(d["doc_type"] == "news" for d in docs):
        # ponytail: 財報問題也補 3 條新聞給趨勢段當素材，沒有就交給 route 觸發 auto_fetch
        news = similarity_search(
            query_vec, top_k=3, company=state["company"], doc_type="news",
            news_since_days=90 if recent else None,
        )
        docs = docs + news
    if state.get("company") and docs:
        # ponytail: 補 2 條全域市場新聞給決策卡當市場脈絡（market-news 入庫多為 company=NULL）
        seen_ids = {d["id"] for d in docs}
        market = similarity_search(query_vec, top_k=2, doc_type="news",
                                   news_since_days=90 if recent else None)
        docs = docs + [d for d in market if d["id"] not in seen_ids]
    return {**state, "retrieved": docs}


def auto_fetch(state: GraphState) -> GraphState:
    """資料不足時自動補抓：有指名公司抓其財報+新聞，一律加掃市場總覽新聞。單一來源失敗不中斷，抓完標記 fetched。"""
    try:
        from .update import fetch_edgar, fetch_mops, fetch_news, fetch_market_news  # 延遲 import，避免循環依賴
    except ImportError as e:  # 環境缺套件時降級成查無資料，不炸整個對話
        print(f"[auto_fetch] 匯入失敗（環境缺套件？）：{e}")
        return {**state, "fetched": True}

    company = state.get("company")
    calls = []
    if company:
        if company.isdigit() and len(company) == 4:
            calls = [lambda: fetch_mops(company), lambda: fetch_news(company)]
        else:
            calls = [lambda: fetch_edgar(company.upper()), lambda: fetch_news(company.upper())]
        if state["retrieved"]:  # 已有財報資料，只缺新聞
            calls = calls[-1:]
    # ponytail: 市場總覽新聞一律補掃，source_exists 會跳過已入庫的，重複觸發便宜
    calls.append(lambda: fetch_market_news(3))

    for call in calls:
        try:
            call()
        except Exception as e:  # noqa: BLE001  單一來源失敗不中斷
            print(f"[auto_fetch] 抓取失敗：{e}")

    return {**state, "fetched": True}


def route_after_retrieve(state: GraphState) -> str:
    if state["retrieved"]:
        if (state.get("company") and not state.get("fetched")
                and not any(d["doc_type"] == "news" for d in state["retrieved"])):
            return "auto_fetch"  # 有財報但沒新聞：補抓新聞給趨勢段
        return "generate"
    if not state.get("fetched"):
        return "auto_fetch"  # 沒指名公司也掃市場新聞，別直接舉手投降
    return "no_result"


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
{history_block}
使用者問題：{state['question']}
"""
    resp = llm.invoke(prompt)
    return {**state, "answer": resp.content}


def no_result(state: GraphState) -> GraphState:
    lang = state.get("lang", "zh")
    if state.get("fetched"):
        answer = t(lang, "no_result_fetched", company=state.get("company"))
    else:
        answer = t(lang, "no_result_plain")
    return {**state, "answer": answer}


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("rewrite_question", rewrite_question)
    graph.add_node("extract_filters", extract_filters)
    graph.add_node("retrieve", retrieve)
    graph.add_node("auto_fetch", auto_fetch)
    graph.add_node("generate", generate)
    graph.add_node("no_result", no_result)

    graph.set_entry_point("rewrite_question")
    graph.add_edge("rewrite_question", "extract_filters")
    graph.add_edge("extract_filters", "retrieve")
    graph.add_conditional_edges(
        "retrieve", route_after_retrieve,
        {"generate": "generate", "auto_fetch": "auto_fetch", "no_result": "no_result"},
    )
    graph.add_edge("auto_fetch", "retrieve")  # 抓完重新檢索；fetched=True 保證不會無限迴圈
    graph.add_edge("generate", END)
    graph.add_edge("no_result", END)

    return graph.compile()
