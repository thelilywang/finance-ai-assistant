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
from .vectorstore import similarity_search


class GraphState(TypedDict):
    question: str
    history: list[tuple[str, str]]  # [(user, assistant), ...] 由呼叫端傳入
    company: str | None
    doc_type: str | None
    retrieved: list[dict]
    answer: str
    fetched: bool  # auto_fetch 是否已執行過（保證只重試一次）


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
    recent = re.search(r"最近|近期|這幾天|本週|近日|recent|lately|latest", state["question"], re.I)
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
    return {**state, "retrieved": docs}


def auto_fetch(state: GraphState) -> GraphState:
    """檢索不到時自動抓該公司的財報+新聞入庫。單一來源失敗不中斷，抓完標記 fetched。"""
    try:
        from .update import fetch_edgar, fetch_mops, fetch_news  # 延遲 import，避免循環依賴
    except ImportError as e:  # 環境缺套件時降級成查無資料，不炸整個對話
        print(f"[auto_fetch] 匯入失敗（環境缺套件？）：{e}")
        return {**state, "fetched": True}

    company = state["company"]
    if company.isdigit() and len(company) == 4:
        calls = [lambda: fetch_mops(company), lambda: fetch_news(company)]
    else:
        calls = [lambda: fetch_edgar(company.upper()), lambda: fetch_news(company.upper())]

    for call in calls:
        try:
            call()
        except Exception as e:  # noqa: BLE001  單一來源失敗不中斷
            print(f"[auto_fetch] 抓取失敗：{e}")

    return {**state, "fetched": True}


def route_after_retrieve(state: GraphState) -> str:
    if state["retrieved"]:
        return "generate"
    if state.get("company") and not state.get("fetched"):
        return "auto_fetch"
    return "no_result"


def generate(state: GraphState) -> GraphState:
    context_blocks = []
    for i, doc in enumerate(state["retrieved"], start=1):
        context_blocks.append(
            f"[來源{i}] {doc['source']}（{doc.get('published_at') or '日期未知'}）\n{doc['content']}"
        )
    context = "\n\n".join(context_blocks)

    history_block = ""
    if state.get("history"):
        history_block = f"\n先前對話（僅供理解語境）：\n{_format_history(state['history'])}\n"

    prompt = f"""你是專業的財經分析助理。請根據下方參考資料回答使用者問題。
規則：
- 只根據參考資料回答，不要編造資料中沒有的數字或事實
- 回答中明確標示引用的來源編號，例如「根據[來源1]...」
- 如果參考資料不足以完整回答，誠實說明還缺什麼資訊
- 回答務必簡潔：先給結論，最多 2-3 段，不要展示推敲過程

輸出格式（嚴格遵守）：
1. 先簡潔回答問題
2. 然後固定追加以下一節：

## 📈 投資趨勢觀點
（以資深投資經理人的角色，僅根據上述參考資料，用 2-4 句話給出該個股近期的投資/操作趨勢觀點：
趨勢方向、值得關注的點、風險。不得引入資料以外的資訊。）

以上非投資建議，僅為資料解讀，投資請自行判斷。

參考資料：
{context}
{history_block}
使用者問題：{state['question']}
"""
    resp = llm.invoke(prompt)
    return {**state, "answer": resp.content}


def no_result(state: GraphState) -> GraphState:
    if state.get("fetched"):
        answer = (
            f"已嘗試自動抓取「{state.get('company')}」的財報與新聞，但仍查無資料。"
            "可能是未上市公司（如 SpaceX）、代號/ticker 有誤，或該來源暫時無法取得。"
            "若你有相關文件，可手動匯入：python -m src.ingest --file <路徑> --company <代號>"
        )
    else:
        answer = (
            "資料庫中找不到與這個問題相關的財報或新聞內容。"
            "問題若有指名上市公司（代號或 ticker）會自動抓取資料，"
            "也可以手動匯入：python -m src.ingest --file <路徑> --company <代號>，或換個問法。"
        )
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
