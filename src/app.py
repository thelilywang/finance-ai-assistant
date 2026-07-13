"""Chainlit 網頁聊天介面。

用法：
    chainlit run src/app.py -w    # 開 http://localhost:8000
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # chainlit run 以 src/ 為 sys.path[0]

import datetime as dt

import chainlit as cl
from chainlit.input_widget import Select

from src.graph import build_graph
from src.i18n import detect_lang, t

graph = build_graph()


@cl.on_chat_start
async def start():
    # ponytail: 對話歷史只存在單次 session 記憶體，重整即清空；要持久化再存 DB
    cl.user_session.set("history", [])
    browser = detect_lang(cl.user_session.get("languages"))
    cl.user_session.set("browser_lang", browser)
    cl.user_session.set("lang_setting", "auto")
    await cl.ChatSettings([
        Select(
            id="language",
            label=t(browser, "settings_label"),
            items={"Auto": "auto", "繁體中文": "zh", "English": "en"},
            initial_value="auto",
        ),
    ]).send()


@cl.on_settings_update
async def on_settings_update(settings):
    cl.user_session.set("lang_setting", settings["language"])


@cl.on_message
async def on_message(message: cl.Message):
    history = cl.user_session.get("history")
    setting = cl.user_session.get("lang_setting", "auto")
    lang = setting if setting != "auto" else cl.user_session.get("browser_lang", "zh")
    state = {
        "question": message.content, "history": history,
        "company": None, "doc_type": None, "retrieved": [], "answer": "", "fetched": False,
        "lang": lang,
    }

    msg = cl.Message(content="")
    final_state = None
    in_think = False  # 保險：reasoning=False 失效時過濾 <think>...</think>
    fetch_notified = False  # auto_fetch 提示只送一次
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
            if payload.get("fetched") and not fetch_notified:
                fetch_notified = True
                await cl.Message(content=t(lang, "fetch_notice")).send()

    answer = final_state["answer"] if final_state else ""
    if not msg.content:
        # no_result 路徑沒有 generate token，用 final state 的 answer 補上
        msg.content = answer

    if final_state and final_state["retrieved"]:
        body = msg.content  # 先留存純回答，避免下載檔重複附上來源列
        sources = sorted({doc["source"] for doc in final_state["retrieved"]})
        await msg.stream_token(f"\n\n---\n{t(lang, 'sources_label')}: {', '.join(sources)}")

        # 附上可下載的分析 .md（no_result 不附）
        now = dt.datetime.now()
        report = (
            f"# {message.content}\n\n{body}\n\n---\n"
            f"{t(lang, 'sources_label')}: {', '.join(sources)}\n\n"
            f"{t(lang, 'report_generated_at')}: {now:%Y-%m-%d %H:%M:%S}\n"
        )
        msg.elements = [cl.File(
            name=f"analysis-{now:%Y%m%d-%H%M%S}.md",
            content=report.encode("utf-8"),
            mime="text/markdown",
            display="inline",
        )]

    await msg.send()

    history.append((message.content, answer))
    cl.user_session.set("history", history[-5:])  # 只留最近 5 輪
