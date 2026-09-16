"""命令列互動介面。

用法：
    python -m src.cli
"""
import asyncio
import uuid

from rich.console import Console
from rich.markdown import Markdown

from . import tracing
from .graph import build_graph

console = Console()


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

            result = await app.ainvoke(
                {"question": question, "history": [], "companies": [], "doc_type": None,
                 "news_since_days": None, "retrieved": [], "answer": "",
                 "fetched": False, "fetch_results": []},
                config=tracing.callbacks(session_id=session_id, user_id="cli"),
            )

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
