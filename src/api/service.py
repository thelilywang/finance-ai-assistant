"""跑 graph 並把串流事件整理成 (type, data)，與傳輸格式（SSE、jobs）無關。"""
from collections.abc import AsyncIterator

from .. import config, tracing
from ..graph import is_fetching, unique_sources
from .schemas import AnswerResult, AskRequest


async def run_graph(
    graph, req: AskRequest, user: str, session_id: str
) -> AsyncIterator[tuple[str, dict]]:
    """事件：step{node}／token{text}／done{AnswerResult}。

    訂閱方式與 cli._ask 相同（messages／updates／values 三模式），
    差別只在輸出端是 yield 事件而非印到終端。
    """
    state = {
        "question": req.question, "history": req.history,
        "companies": [], "doc_type": None, "news_since_days": None,
        "retrieved": [], "answer": "", "fetched": False,
        "fetch_results": [], "messages": [], "lang": req.lang,
        "model": config.LLM_MODEL,
    }
    if req.market:
        # 與 app.py 反問按鈕同義：使用者已指定，不得被重抽或問句校正覆蓋
        state["market"] = req.market
        state["market_confirmed"] = True

    final_state = None
    streaming = False  # 第一個 token 之後不再送 step

    async for mode, payload in graph.astream(
        state,
        stream_mode=["messages", "updates", "values"],
        config=tracing.callbacks(session_id=session_id, user_id=user),
    ):
        if mode == "messages":
            chunk, metadata = payload
            if metadata.get("langgraph_node") != "generate" or not chunk.content:
                continue
            streaming = True
            yield "token", {"text": chunk.content}
        elif mode == "updates":
            if streaming:
                continue
            node = next(iter(payload))
            if node == "extract_filters":
                yield "step", {"node": "retrieve"}
            elif node == "agent" and is_fetching(payload[node]):
                yield "step", {"node": "fetch"}
            elif node == "assemble":
                yield "step", {"node": "generate"}
        else:  # values：最後一筆就是 final state
            final_state = payload

    result = AnswerResult(
        answer=final_state["answer"],
        sources=unique_sources(final_state.get("retrieved") or []),
        ask_market=bool(final_state.get("ask_market")),
        peer_company=final_state.get("peer_company"),
    )
    yield "done", result.model_dump()
