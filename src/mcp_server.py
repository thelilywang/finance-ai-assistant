"""MCP server：把 RAG 檢索與財報/新聞抓取拆成單一職責的 tool。

同時服務兩種 client，走完全相同的 MCP 協定與 tool 定義，不維護兩份邏輯：
1. 本專案的 LangGraph agent（src/graph.py 的 agent 節點）
2. Claude Desktop 等外部 MCP client

每個 tool 只做一件事，不在內部自動接力（例如檢索完不會自己去補抓）——
「查到的資料夠不夠新、要不要補抓、補抓完要不要再查一次」全部交給呼叫端的 LLM
依 tool 說明自行判斷，這是刻意的設計，不是遺漏。

Transport 用 streamable-http 而非 stdio，因為需要 Authorization: Bearer 驗證，
stdio 沒有 per-request 驗證的概念。

用法：
    python -m src.mcp_server    # 監聽 0.0.0.0:8000，MCP 端點在 /mcp
"""
from __future__ import annotations

import asyncio
import json

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import config
from .graph import fetch_missing_data, retrieve_context
from .tickers import normalize_ticker
from .update import fetch_market_news

# SDK 預設的 DNS rebinding 防護只認 localhost，會把 docker 內用 service 名稱的連線
# （Host: mcp-server:8000）擋成 421；把實際會用到的 host 列進允許清單，不關掉防護本身。
mcp = FastMCP(
    "finance-ai-assistant",
    transport_security=TransportSecuritySettings(
        allowed_hosts=config.MCP_ALLOWED_HOSTS,
        allowed_origins=config.MCP_ALLOWED_HOSTS,
    ),
)


@mcp.tool()
async def search_knowledge_base(
    question: str, company: str | None = None, doc_type: str | None = None
) -> str:
    """在向量資料庫中檢索與問題相關的財報/新聞片段。只做檢索，不會自動補抓資料。

    question: 使用者問題（用於語意檢索，通常直接帶原問題即可）。
    company: 台股代號（如 "2330"）或美股 ticker（如 "AAPL"），留空表示不限公司。
    doc_type: "financial_report" 或 "news"，留空表示兩種都查。

    回傳 JSON 字串：{"summary_for_llm": 整理過的可讀文字, "chunks": 結構化資料陣列}。
    你只需要讀 summary_for_llm，裡面每個片段都標了來源與發布日期；chunks 是給程式
    後續組引用用的，你不需要處理。

    判斷資料是否足夠新（若不夠新，請自行呼叫 fetch_company_data 或 fetch_market_overview
    補抓，本工具不會幫你補）：
    - 完全查無資料，而問題有指名公司 → 應該補抓該公司資料。
    - 只查到財報、沒有任何新聞 → 通常代表新聞還沒入庫，建議補抓。
    - 問題含「最近／最新／今天／即時／近期」等字眼，但最新一筆新聞不是今天 → 應該補抓。
    - 問題沒有上述字眼，但最新一筆新聞距今超過 2-3 天 → 可以考慮補抓。
    - 補抓完成後，請再呼叫一次本工具重新檢索，確認新資料已入庫，不要直接回報查無資料。
    """
    docs = await asyncio.to_thread(retrieve_context, question, company, doc_type)
    blocks = [
        f"[{d['source']}]（發布日期：{d.get('published_at') or '日期未知'}）\n{d['content']}"
        for d in docs
    ]
    summary = "\n\n".join(blocks) if blocks else "查無相關資料。"
    return json.dumps(
        {"summary_for_llm": summary, "chunks": docs}, default=str, ensure_ascii=False
    )


@mcp.tool()
async def fetch_company_data(ticker: str) -> str:
    """抓取指定公司的最新財報與新聞並匯入資料庫。只做抓取，不會回傳檢索結果。

    ticker: 台股代號（如 "2330"）或美股 ticker（如 "AAPL"）。
    台股自動抓 MOPS 財報、美股自動抓 SEC EDGAR 財報，兩者都會一併抓該公司新聞
    （資料庫已有該公司財報時只補新聞，財報變動頻率低不重抓）。

    抓取會連外部網站，首次約需 1-3 分鐘。抓完後請呼叫 search_knowledge_base
    重新檢索才看得到新資料，本工具不會自動幫你查。

    回傳各資料來源的處理結果訊息（成功或失敗都會列出）。若訊息顯示抓取失敗
    （例如來源網站改版或查無該公司），不要重複呼叫本工具，改為據實回報使用者。
    """
    normalized = normalize_ticker(ticker)
    if normalized is None:
        return f"無法辨識的股票代號：{ticker}"

    # has_report 用既有財報決定只補新聞或連財報一起抓，屬確定性規則，不交給 LLM 判斷
    docs = await asyncio.to_thread(
        retrieve_context, normalized, normalized, "financial_report"
    )
    has_report = any(d["doc_type"] == "financial_report" for d in docs)
    results = await asyncio.to_thread(fetch_missing_data, normalized, has_report)
    return "；".join(results)


@mcp.tool()
async def fetch_market_overview() -> str:
    """抓取整體市場總覽新聞（不限特定公司）並匯入資料庫。只做抓取，不回傳檢索結果。

    適用於使用者詢問大盤走勢、市場氣氛、產業趨勢、總體經濟等不針對單一公司的問題；
    查詢特定公司時通常不需要呼叫本工具（fetch_company_data 已涵蓋該公司新聞）。

    抓完後請呼叫 search_knowledge_base（company 留空）重新檢索才看得到新資料。
    """
    result = await asyncio.to_thread(fetch_market_news, 3)
    return result.detail


def _add_bearer_auth(app):
    """加一層檢查 Authorization: Bearer <MCP_AUTH_TOKEN> 的 middleware，不符回 401。

    # ponytail: SDK 內建的 auth=AuthSettings 是完整 OAuth（issuer_url 必填），
    # 對「單一共享密鑰」這需求太重；要做多 client 各自金鑰時再換成 SDK 的 provider。
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    expected = f"Bearer {config.MCP_AUTH_TOKEN}"

    class _AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.headers.get("authorization") != expected:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    app.add_middleware(_AuthMiddleware)
    return app


if __name__ == "__main__":
    import uvicorn

    http_app = mcp.streamable_http_app()
    if config.MCP_AUTH_TOKEN:
        http_app = _add_bearer_auth(http_app)
    else:
        print("[mcp] MCP_AUTH_TOKEN 未設定，未啟用身分驗證（僅適合本機開發）")
    uvicorn.run(http_app, host="0.0.0.0", port=8000)
