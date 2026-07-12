"""命令列互動介面。

用法：
    python -m src.cli
"""
from rich.console import Console
from rich.markdown import Markdown

from .graph import build_graph

console = Console()


def main() -> None:
    app = build_graph()
    console.print("[bold cyan]財報/新聞 RAG 問答助理[/bold cyan]（輸入 exit 離開）\n")

    while True:
        question = console.input("[bold]> [/bold]")
        if question.strip().lower() in {"exit", "quit"}:
            break

        result = app.invoke(
            {"question": question, "history": [], "company": None, "doc_type": None,
             "retrieved": [], "answer": ""}
        )

        console.print(Markdown(result["answer"]))
        if result["retrieved"]:
            sources = {doc["source"] for doc in result["retrieved"]}
            console.print(f"[dim]參考來源: {', '.join(sources)}[/dim]\n")


if __name__ == "__main__":
    main()
