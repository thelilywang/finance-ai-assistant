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
import datetime as dt
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
    question: str, company: str | None = None, doc_type: str | None = None,
    news_since_days: int | None = None,
) -> str:
    """在向量資料庫中檢索與問題相關的財報/新聞片段。只做檢索，不會自動補抓資料。

    question: 使用者問題（用於語意檢索，通常直接帶原問題即可）。
    company: 台股代號（如 "2330"）或美股 ticker（如 "AAPL"），留空表示不限公司。
    doc_type: 只能填 "financial_report" 或 "news" 其中一個，或留空表示兩種都查。
        不可填多個值（例如 "financial_report,news" 是錯的），想兩種都查就留空。
    news_since_days: 只查最近 N 天內的新聞（財報不受影響），留空表示不限日期。
        問題有指定時效才填（「今天」填 1、「本週」填 7、「最近」填 90），沒指定就留空。

    回傳 JSON 字串：{"summary_for_llm": 整理過的可讀文字, "chunks": 結構化資料陣列}。
    你只需要讀 summary_for_llm，chunks 是給程式組引用用的，不需處理。summary 開頭會
    直接告訴你「目前最新的新聞距今 N 天」，時效判斷請只依據這個數字，不要自己推算日期，
    也不要拿財報的天數來判斷（財報按季發布，距今數十天屬正常，不代表資料過期）。

    依上述「最新新聞距今 N 天」決定是否補抓（若要補抓，呼叫 fetch_company_data 或
    fetch_market_overview，本工具不會幫你補）：
    - 完全查無資料，而問題有指名公司 → 補抓該公司資料。
    - 檢索結果中沒有任何新聞 → 補抓。
    - 有帶 news_since_days 且值不大於 7（問題要求近期資料），而 N 大於 0 → 補抓。
    - 其餘情況，N 大於 3 → 補抓。
    - 以上皆不符合（例如問題不要求最新、且 N 是 0 到 3）→ 不要補抓，直接停止呼叫工具。
    - 補抓完成後，請再呼叫一次本工具重新檢索，確認新資料已入庫，不要直接回報查無資料。
    """
    # LLM 有時會把多個值塞成 "financial_report,news"，那樣過濾會查出空結果；
    # 只認單一合法值，其餘（含多值、空字串）一律視為不過濾
    if doc_type not in ("financial_report", "news"):
        doc_type = None
    # 同理，天數也可能收到字串或 0/負數，非正整數一律視為不過濾
    if not isinstance(news_since_days, int) or isinstance(news_since_days, bool) or news_since_days < 1:
        news_since_days = None

    docs = await asyncio.to_thread(
        retrieve_context, question, company, doc_type, news_since_days
    )
    today = dt.date.today()
    _LABEL = {"news": "新聞", "financial_report": "財報"}
    blocks = []
    news_ages = []
    for d in docs:
        published = d.get("published_at")
        kind = _LABEL.get(d["doc_type"], d["doc_type"])
        if published:
            # 直接算好距今天數：模型讀得到日期卻不見得會跟「今天」相減（實測過的失敗案例）
            age = (today - published).days if isinstance(published, dt.date) else None
            when = f"發布日期：{published}" + (f"，距今 {age} 天" if age is not None else "")
            if age is not None and d["doc_type"] == "news":
                news_ages.append(age)
        else:
            when = "發布日期：不明"
        blocks.append(f"[{kind}｜{d['source']}]（{when}）\n{d['content']}")

    # 時效判斷只看新聞（財報本來就是季度發布，幾十天前很正常），所以直接把
    # 「最新新聞距今幾天」算好放在開頭，免得模型拿財報的天數去套新聞的門檻
    if blocks:
        if news_ages:
            freshness = f"目前最新的「新聞」距今 {min(news_ages)} 天。"
        else:
            freshness = "檢索結果中沒有任何新聞（只有財報）。"
        header = f"今天是 {today}。{freshness}以下是檢索結果：\n\n"
    else:
        header = ""
    summary = header + "\n\n".join(blocks) if blocks else "查無相關資料。"
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
