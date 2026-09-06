"""MCP server：把股價/財報抓取與 RAG 檢索包成 tool，給 Claude Desktop 等外部 MCP client 使用。

用法（Claude Desktop 設定 command 指向 venv 的 python3）：
    python -m src.mcp_server

跟 Chainlit app（app.py）是兩個獨立入口，各自持有自己的 DB 連線池，
共用同一份核心邏輯（fetch_missing_data / retrieve_context / needs_refetch），不重寫兩份。
"""
from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

from .graph import fetch_missing_data, needs_refetch, retrieve_context
from .market import get_market_snapshot
from .tickers import normalize_ticker

mcp = FastMCP("finance-ai-assistant")


@mcp.tool()
async def get_stock_data(ticker: str) -> str:
    """抓取指定股票的最新財報/新聞並匯入資料庫，回傳即時行情快照。

    ticker: 台股代號（如 2330）或美股 ticker（如 AAPL）。
    """
    normalized = normalize_ticker(ticker)
    if normalized is None:
        return f"無法辨識的股票代號：{ticker}"

    await asyncio.to_thread(fetch_missing_data, normalized, False)
    snapshot = await asyncio.to_thread(get_market_snapshot, normalized)
    return snapshot or f"查無 {normalized} 的行情資料，可能是代號錯誤或資料來源暫時無法存取。"


@mcp.tool()
async def query_market_context(question: str, ticker: str | None = None) -> str:
    """根據問題檢索相關的財報/新聞片段並回傳，自動評估資料時效性，
    查無資料或新聞已過期時會先觸發補抓再重新檢索，確保回傳內容盡量最新。

    question: 使用者問題（繁中或英文皆可）。
    ticker: 台股代號或美股 ticker，留空表示不限公司。
    """
    company = normalize_ticker(ticker) if ticker else None
    docs = await asyncio.to_thread(retrieve_context, question, company, None)

    should_fetch = not docs or needs_refetch(docs, company, question)
    if should_fetch:
        has_report = any(d["doc_type"] == "financial_report" for d in docs)
        await asyncio.to_thread(fetch_missing_data, company, has_report)
        docs = await asyncio.to_thread(retrieve_context, question, company, None)

    if not docs:
        return "查無相關資料。"

    blocks = [
        f"[{d['source']}]（{d.get('published_at') or '日期未知'}）\n{d['content']}"
        for d in docs
    ]
    return "\n\n".join(blocks)


if __name__ == "__main__":
    mcp.run()
