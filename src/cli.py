"""命令列互動介面。

用法：
    python -m src.cli
"""
import asyncio
import uuid

from rich.console import Console
from rich.markdown import Markdown

from . import tracing
from .graph import build_graph, is_fetching
from .i18n import t

console = Console()

# 進度提示與 app.py 共用 i18n 字串；CLI 是單人 debug REPL，不做語言切換，固定中文。
_UI_LANG = "zh"


async def _ask(app, question: str, session_id: str) -> dict:
    """跑 graph，邊串流 generate 的 token 邊印進度，回傳 final state。

    與 app.py 的 _stream_answer 同一套訂閱（messages 逐 token／updates 節點完成／
    values 完整 state），差別只在輸出端：這裡沒有 step 元件，進度就是一行灰字，
    且不需要 tracker——印過就印過了，不用收掉。
    """
    final_state = None
    streaming = False  # 第一個 token 到之前，進度提示還能印

    async for mode, payload in app.astream(
        {"question": question, "history": [], "companies": [], "doc_type": None,
         "news_since_days": None, "retrieved": [], "answer": "",
         "fetched": False, "fetch_results": []},
        stream_mode=["messages", "updates", "values"],
        config=tracing.callbacks(session_id=session_id, user_id="cli"),
    ):
        if mode == "messages":
            chunk, metadata = payload
            if metadata.get("langgraph_node") != "generate" or not chunk.content:
                continue
            if not streaming:
                streaming = True
                console.print()  # 與進度行隔開
            # 逐 token 用 print 而非 rich markup：token 可能含 [ ] 被當成標記吃掉，
            # 完整的 Markdown 渲染留到最後重印。
            print(chunk.content, end="", flush=True)
        elif mode == "updates":
            if streaming:
                continue
            node = next(iter(payload))
            if node == "extract_filters":
                console.print(f"[dim]{t(_UI_LANG, 'step_retrieve')}[/dim]")
            elif node == "agent" and is_fetching(payload[node]):
                console.print(f"[dim]{t(_UI_LANG, 'step_fetch')}[/dim]")
            elif node == "assemble":
                console.print(f"[dim]{t(_UI_LANG, 'step_generate')}[/dim]")
        else:  # values：最後一筆就是 final state
            final_state = payload

    if streaming:
        print()
    return final_state


# async 是被 graph 逼出來的：build_graph 要跟 MCP server 拿 tool 清單，agent 節點本身
# 也是 async，兩者都不能用同步 invoke 驅動（會 TypeError: No synchronous function provided）。
# console.input() 是阻塞呼叫，但這是單人 REPL，沒有並行工作會被它餓到，
# 為此把輸入搬去另一個執行緒不值得。
async def main() -> None:
    # CLI 是短生命週期程序，一次執行算一個 session
    session_id = f"cli-{uuid.uuid4().hex[:8]}"
    app = await build_graph()
    console.print("[bold cyan]財報/新聞 RAG 問答助理[/bold cyan]（輸入 exit 離開）\n")

    try:
        while True:
            question = console.input("[bold]> [/bold]")
            if question.strip().lower() in {"exit", "quit"}:
                break

            result = await _ask(app, question, session_id)

            # 串流時是逐 token 的純文字，最後用 Markdown 重印一次補上排版
            console.print(Markdown(result["answer"]))
            if result["retrieved"]:
                sources = {doc["source"] for doc in result["retrieved"]}
                console.print(f"[dim]參考來源: {', '.join(sources)}[/dim]\n")
    finally:
        # 短生命週期程序結束前一定要送，否則最後幾輪的 trace 會隨程序消失。
        # 放 finally：Ctrl-C 或例外離開時同樣要送。
        tracing.flush()


if __name__ == "__main__":
    asyncio.run(main())
