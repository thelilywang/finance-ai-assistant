"""Chainlit 網頁聊天介面。

用法：
    chainlit run src/app.py -w    # 開 http://localhost:8000
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # chainlit run 以 src/ 為 sys.path[0]

import chainlit as cl

from src.graph import build_graph

graph = build_graph()


@cl.on_chat_start
async def start():
    # ponytail: 對話歷史只存在單次 session 記憶體，重整即清空；要持久化再存 DB
    cl.user_session.set("history", [])
    await cl.Message(
        content="財報/新聞 RAG 助理，請輸入問題（例：台積電最新一季毛利率？）"
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    history = cl.user_session.get("history")
    state = {
        "question": message.content, "history": history,
        "company": None, "doc_type": None, "retrieved": [], "answer": "",
    }

    msg = cl.Message(content="")
    final_state = None
    in_think = False  # 保險：reasoning=False 失效時過濾 <think>...</think>
    # 同時訂閱 messages（逐 token）與 values（節點完成後的完整 state）
    async for mode, payload in graph.astream(state, stream_mode=["messages", "values"]):
        if mode == "messages":
            chunk, metadata = payload
            if metadata.get("langgraph_node") != "generate" or not chunk.content:
                continue
            token = chunk.content
            if "<think>" in token:
                in_think = True
            if in_think:
                if "</think>" in token:
                    in_think = False
                    token = token.split("</think>", 1)[1]
                else:
                    continue
            if token:
                await msg.stream_token(token)
        else:  # values：最後一筆就是 final state
            final_state = payload

    answer = final_state["answer"] if final_state else ""
    if not msg.content:
        # no_result 路徑沒有 generate token，用 final state 的 answer 補上
        msg.content = answer

    if final_state and final_state["retrieved"]:
        sources = sorted({doc["source"] for doc in final_state["retrieved"]})
        await msg.stream_token(f"\n\n---\n參考來源: {', '.join(sources)}")

    await msg.send()

    history.append((message.content, answer))
    cl.user_session.set("history", history[-5:])  # 只留最近 5 輪
