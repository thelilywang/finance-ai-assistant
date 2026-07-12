"""LangGraph 主流程。

Graph 結構：
    rewrite_question -> extract_filters -> retrieve -> (no_result | generate)

- rewrite_question: 多輪對話時把追問改寫成獨立問題，讓 embedding 檢索有效
- extract_filters: 用 LLM 從問題中抽出公司代號/文件類型，作為檢索 filter
- retrieve: 把問題 embedding 後去 pgvector 找最相似的 chunk
- generate: 根據檢索到的 chunk 生成回答，並附上出處來源
- no_result: 找不到相關資料時，誠實告知使用者，避免幻覺
"""
from __future__ import annotations

import json
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
1. company: 台股代號（4 碼數字），沒有提到就填 null
2. doc_type: "financial_report"（財報相關）或 "news"（新聞相關），不確定就填 null

只回傳 JSON，不要有其他文字，格式：
{{"company": "2330" 或 null, "doc_type": "financial_report" 或 "news" 或 null}}

使用者問題：{state['question']}
"""
    resp = llm.invoke(prompt).content.strip()
    try:
        # 有些模型會包 markdown code block，去掉
        cleaned = resp.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, AttributeError):
        parsed = {"company": None, "doc_type": None}

    return {**state, "company": parsed.get("company"), "doc_type": parsed.get("doc_type")}


def retrieve(state: GraphState) -> GraphState:
    query_vec = embeddings.embed_query(state["question"])
    docs = similarity_search(
        query_vec, company=state.get("company"), doc_type=state.get("doc_type")
    )
    return {**state, "retrieved": docs}


def route_after_retrieve(state: GraphState) -> str:
    return "generate" if state["retrieved"] else "no_result"


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

參考資料：
{context}
{history_block}
使用者問題：{state['question']}
"""
    resp = llm.invoke(prompt)
    return {**state, "answer": resp.content}


def no_result(state: GraphState) -> GraphState:
    return {
        **state,
        "answer": "資料庫中找不到與這個問題相關的財報或新聞內容，建議先確認是否已匯入對應公司/文件，或換個問法。",
    }


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("rewrite_question", rewrite_question)
    graph.add_node("extract_filters", extract_filters)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.add_node("no_result", no_result)

    graph.set_entry_point("rewrite_question")
    graph.add_edge("rewrite_question", "extract_filters")
    graph.add_edge("extract_filters", "retrieve")
    graph.add_conditional_edges(
        "retrieve", route_after_retrieve, {"generate": "generate", "no_result": "no_result"}
    )
    graph.add_edge("generate", END)
    graph.add_edge("no_result", END)

    return graph.compile()
