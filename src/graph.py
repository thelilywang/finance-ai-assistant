"""LangGraph 主流程。

Graph 結構：
    rewrite_question -> extract_filters -> agent <-> tools -> assemble -> (generate | no_result)

- rewrite_question: 多輪對話時把追問改寫成獨立問題，讓 embedding 檢索有效
- extract_filters: 用 LLM 從問題中抽出公司代號/文件類型，供 agent 呼叫 tool 時當已知條件
- agent: 把 MCP tool 綁給 LLM，由 LLM 自行決定檢索/補抓、要不要再呼叫下一個 tool
- tools: 執行 LLM 選定的 MCP tool（ToolNode）；檢索結果明顯夠用時直接收工，不再回 agent
- assemble: 把 tool 回傳結果整理回 retrieved/fetch_results，供下游節點沿用既有格式
- generate: 根據檢索到的 chunk 生成回答，並附上出處來源
- no_result: 找不到相關資料時，誠實告知使用者，避免幻覺

「資料夠不夠新、要不要補抓」不再由程式規則判斷（原 needs_refetch/route_after_retrieve），
改由 LLM 讀 MCP tool 的說明自行決定，判斷準則寫在 src/mcp_server.py 的 tool docstring。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from functools import lru_cache
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, field_validator

from . import config
from .i18n import t
from .logging_setup import log_duration
from .market import get_adr_premium, get_market_snapshot, get_market_snapshots
from .tickers import (
    DUAL_LISTED_NAMES, OTC_ONLY_NAMES, TW_US_DUAL_LISTED, dual_listed_peer, is_tw_ticker,
    normalize_ticker, otc_adr_of,
)
from .tracing import node_span
from .vectorstore import pool, similarity_search


class GraphState(TypedDict):
    question: str
    history: list[tuple[str, str]]  # [(user, assistant), ...] 由呼叫端傳入
    companies: list[str]
    doc_type: str | None
    news_since_days: int | None  # 使用者要求的新聞時效窗（天），None 表示不限日期
    retrieved: list[dict]
    answer: str
    fetched: bool  # 本輪是否呼叫過補抓 tool，no_result 用來決定提示語
    fetch_results: list[str]  # 各補抓 tool 的結果訊息，no_result 用來提示抓取是否失敗
    lang: str
    model: str  # 本輪使用的 Ollama 模型，由 UI 選單決定；空值則用 config.LLM_MODEL
    market: str | None  # 使用者明講的市場（tw/us/both），沒講則 None
    ask_market: bool  # 雙掛牌但沒指明市場，需先反問使用者
    market_confirmed: bool  # 使用者已透過反問按鈕明確指定市場，不得再被重抽或問句校正覆蓋
    in_scope: bool  # extract_filters 判定問題是否屬財經範疇
    off_topic: bool  # 問題不在財經範圍，本輪不檢索、直接請使用者改問
    peer_company: str | None  # 另一市場的對應代號，反問與併陳兩用
    answer_shape: str  # extract_filters 判定的回答形式："news" 或 "full"，決定 generate 輸出哪些決策卡欄位
    allowed_fields: list[str]  # generate 定案後實際輸出的決策卡欄位，供 tracing 區分「意圖如此」與「evidence 不足」
    messages: Annotated[list[BaseMessage], add_messages]  # agent <-> tools 的往返記錄


# reasoning=False 關閉推理段。曾評估對 generate 開啟以顯示推理過程（可解釋性），
# 實測在 qwen3.5:9b 上代價無法接受：單題 186s→1245s，光 generate 就從 87s 變 1053s
# （模型為一句營收問題寫了 30891 字推理，是答案的 21 倍），且首個 token 從 108s 延後
# 到 238s，連體感延遲都更差。壓制推理長度的兩條路也都試過：reasoning='low' 對
# qwen3.5 無效（推理字數與 True 完全相同，層級控制僅 gpt-oss 支援），num_predict
# 則是推理先吃光額度、答案被截成空字串（done_reason=length）。換模型再重新評估。
def _model_of(state: GraphState) -> str:
    """本輪要用的模型。UI 沒選（或舊呼叫端沒帶）就退回預設。"""
    return state.get("model") or config.LLM_MODEL


@lru_cache(maxsize=8)
def _llms(model: str) -> dict:
    """建立某個模型的三個實例。lru_cache 讓同一模型的多個 session 共用，換模型才新建。

    三個實例都帶 num_ctx=config.OLLAMA_NUM_CTX 且務必同值：Ollama 收到不同 num_ctx
    會重新載入模型，三個節點輪流呼叫若值不一致，等於每次切換都多付一次載入時間。
    """
    base = ChatOllama(
        model=model, base_url=config.OLLAMA_BASE_URL, temperature=0, reasoning=False,
        num_ctx=config.OLLAMA_NUM_CTX,
    )
    return {
        # with_retry：Ollama 模型冷啟動/短暫逾時時重試，避免整個 graph 節點直接中斷對話
        "llm": base.with_retry(stop_after_attempt=3),
        "filters": base.with_structured_output(ExtractedFilters).with_retry(
            stop_after_attempt=3
        ),
        # tool-calling 專用：reasoning=False 會讓模型把「我要呼叫某工具」寫成文字而非
        # 產生結構化 tool_calls（實測 A/B：關推理時同一情境完全不發 tool call，開啟則
        # 正常），因此 agent 節點不能沿用關掉推理的實例。
        "tool": ChatOllama(model=model, base_url=config.OLLAMA_BASE_URL, temperature=0,
                           num_ctx=config.OLLAMA_NUM_CTX),
    }


# ns -> ms 的欄位名對照。缺的欄位（例如 structured output 走 include_raw 以外的路徑
# 拿不到 AIMessage）直接不放進回傳的 dict，不補 0 假裝量到了。
_OLLAMA_DURATION_FIELDS_MS = {
    "prompt_eval_duration": "prefill_ms",
    "eval_duration": "decode_ms",
    "load_duration": "load_ms",
}


def _ollama_usage(msg: AIMessage) -> dict:
    """從 ChatOllama 回傳的 AIMessage 取出 token 數與耗時，供併入各節點的 log_duration。

    欄位來自 response_metadata（實測 langchain_ollama 0.x）：prompt_eval_count、
    eval_count、done_reason 為計數/狀態，prompt_eval_duration／eval_duration／
    load_duration 是奈秒、換算成毫秒取整。response_metadata 為空（例如測試用的
    stub LLM）或缺欄位時該項就不放進回傳的 dict，不補假值。
    """
    meta = getattr(msg, "response_metadata", None) or {}
    out: dict = {}
    if "prompt_eval_count" in meta:
        out["prompt_tokens"] = meta["prompt_eval_count"]
    if "eval_count" in meta:
        out["output_tokens"] = meta["eval_count"]
    if "done_reason" in meta:
        out["done_reason"] = meta["done_reason"]
    for src, dst in _OLLAMA_DURATION_FIELDS_MS.items():
        if src in meta:
            out[dst] = round(meta[src] / 1_000_000)
    return out


def _warn_if_truncated(node: str, qid: str, usage: dict) -> None:
    """prompt_tokens 疑似被 Ollama 截斷時記一筆 warning，供回測統計截斷發生率。

    截斷只在原始 prompt 達到 num_ctx 時才發生，截完的長度是 `num_ctx // 2 + 2`
    （10-07 實測兩點：4096 對應 2050、32768 對應 16386，server log 原文
    `limit=16386 prompt=39984 keep=4 new=16386`）。沒被截斷的 prompt，
    prompt_tokens 可以落在 0 到 num_ctx 之間任何值，所以門檻不能用「≥」，
    要用「貼著 limit」來判斷。

    關鍵限制：Ollama 截斷後回報給 client 的 prompt_eval_count 是「截斷後」的
    limit，不是原本的 prompt 長度（client 這端只看得到前者）。prompt_tokens
    一旦截斷就會卡在極接近 limit 的值，這個門檻偵測到的其實是「prompt_tokens
    貼著已知的截斷上限」，不是「原始 prompt 遠大於 num_ctx」。因為
    response_metadata 沒有其他欄位能回推原始長度，暫時沒有更好的替代訊號。

    仍可能誤報：原始 prompt 剛好落在 limit ±8 以內、沒被截斷，也會被判定成
    截斷。
    """
    prompt_tokens = usage.get("prompt_tokens")
    if prompt_tokens is None:
        return
    limit = config.OLLAMA_NUM_CTX // 2 + 2
    if abs(prompt_tokens - limit) <= 8:
        log.warning("prompt 疑似被截斷", extra={"fields": {
            "node": node, "qid": qid, "prompt_tokens": prompt_tokens,
            "num_ctx": config.OLLAMA_NUM_CTX, "limit": limit}})


embeddings = OllamaEmbeddings(model=config.EMBEDDING_MODEL, base_url=config.OLLAMA_BASE_URL)

log = logging.getLogger("graph")


def _qid(question: str) -> str:
    """同一題各節點共用的關聯鍵，回測時用來把一次問答的所有紀錄串起來。

    GraphState 沒有 thread_id，加欄位會擴散到所有呼叫端；問題文字在 rewrite_question
    之後就固定，拿它的短 hash 已足夠關聯，且不必把提問內容寫進 log。
    """
    return hashlib.sha1(question.encode()).hexdigest()[:8]

# query embedding 只取決於模型、端點與問題文字，不會因為 doc_chunks 新增而失效。
# 用程序內短 TTL/LRU 避免 agent 在同一題的 tool loop 重複打 Ollama；不落地，重啟即清空。
_embedding_cache: OrderedDict[tuple[str, str, str], tuple[float, tuple[float, ...]]] = OrderedDict()
_embedding_cache_lock = threading.RLock()


def _clear_embedding_cache() -> None:
    """清空 query embedding 快取；供測試與效能量測使用。"""
    with _embedding_cache_lock:
        _embedding_cache.clear()


def _embed_query_cached(question: str) -> tuple[list[float], bool]:
    """取得 query embedding，命中 TTL/LRU 快取時不重複呼叫 Ollama。回傳 (向量, 是否命中)。

    鎖刻意涵蓋未命中的 embed 呼叫，避免多個同時抵達的相同問題產生重複請求。
    Ollama 在此部署本來就是單一實體，序列化相同 query 的 cold miss 不降低有效吞吐。
    命中與否回傳給呼叫端記錄，避免在鎖內做 I/O。
    """
    max_entries = config.EMBEDDING_CACHE_MAX_ENTRIES
    ttl = config.EMBEDDING_CACHE_TTL_SECONDS
    if max_entries == 0 or ttl == 0:
        return list(embeddings.embed_query(question)), False

    key = (config.EMBEDDING_MODEL, config.OLLAMA_BASE_URL, question)
    with _embedding_cache_lock:
        now = time.monotonic()
        cached = _embedding_cache.pop(key, None)
        if cached is not None and now - cached[0] <= ttl:
            _embedding_cache[key] = cached  # pop + reinsert = 最近使用
            return list(cached[1]), True

        # 過期項已經 pop；失敗不可污染快取。
        vector = tuple(embeddings.embed_query(question))
        _embedding_cache[key] = (now, vector)
        while len(_embedding_cache) > max_entries:
            _embedding_cache.popitem(last=False)
        return list(vector), False


def _format_history(history: list[tuple[str, str]]) -> str:
    """把最近 3 輪對話排成「使用者/助理」逐行文字。"""
    lines = []
    for user, assistant in history[-3:]:
        lines.append(f"使用者: {user}")
        lines.append(f"助理: {assistant}")
    return "\n".join(lines)


# 只在上一則確實是市場反問時才附加。抽成常數是為了讓「這段有條件」一眼看得出來，
# 埋在 f-string 中間的話下一個人很容易又把它改回無條件。
_MARKET_REASK_RULE = """助理上一則是在問「要看台股還是美股」，而新問題是在回答它
（「台股」「美股」「都要」），改寫時務必保留這個選擇：「台股」→「…台股（代號）的…」、
「美股」→「…美股 ADR 的…」、「都要」→「請同時提供台股與美股兩邊的…」。
不可把它當成其他意思（例如業務部門）。
"""

# ask_market 文案是 i18n 模板（公司名、代號會替換），但結尾這句固定，中英各一。
# 比對結尾而非整段，模板裡的變數就不影響判斷。
_REASK_MARKERS = ("請問你要看哪一邊？", "Which one would you like?")


def _last_turn_is_market_reask(history: list[tuple[str, str]]) -> bool:
    """上一則助理回覆是不是雙掛牌的市場反問。

    認文案結尾的固定句，且該輪問句要撿得回雙掛牌代號——兩個條件都成立才算，
    避免使用者自己打出「請問你要看哪一邊？」就觸發那三個模板。
    """
    if not history:
        return False
    _user, assistant = history[-1]
    if not any(m in (assistant or "") for m in _REASK_MARKERS):
        return False
    return _last_dual_listed(history[-1:]) is not None


def rewrite_question(state: GraphState) -> GraphState:
    """有對話歷史時，把追問改寫成不依賴上下文的獨立問題；沒有就直接通過。

    market_confirmed 代表這是反問按鈕選完後的重跑：問句還是原本那句完整問題，
    市場另外帶在 state，改寫沒有任何可改的東西，故直接跳過省一次 LLM 呼叫。
    """
    if state.get("market_confirmed") or not state.get("history"):
        return state

    # 市場消歧那三個模板只在「上一則真的是反問」時才給模型看。它們原本無條件寫在
    # prompt 裡，模型會把「請同時提供台股與美股兩邊的…」當成通用句型往外套：實測
    # 「美股半導體最近如何？」「台股電子股最近表現怎麼樣？」都被改寫成兩邊都要，
    # market 因此抽成 both，撈回使用者沒問的那個市場（tests/eval_multiturn_market.py
    # 的 M4／M5／M6）。條件本來就寫在句子裡，但和一般規則平級擺著等於沒有約束力。
    reask_block = _MARKET_REASK_RULE if _last_turn_is_market_reask(state["history"]) else ""

    prompt = f"""以下是使用者與財經助理的對話紀錄，以及使用者的新問題。
若新問題依賴上下文（例如「那毛利率呢？」），請改寫成一個不依賴上下文、可獨立理解的完整問題；
若新問題本身已經獨立完整，原樣輸出即可。只輸出改寫後的問題，不要有其他文字。
改寫只補回問句缺少的資訊，不得增加使用者沒問的東西；使用者只問單一市場（只講台股或
只講美股）時，改寫後也只能有那一個市場，不可擅自擴成兩邊都要。
{reask_block}
對話紀錄：
{_format_history(state["history"])}

新問題：{state['question']}
"""
    started = time.monotonic()
    resp = _llms(_model_of(state))["llm"].invoke(prompt)
    rewritten = resp.content.strip()
    # qid 以改寫「後」的問句計算：下游節點看到的都是改寫後的問句，用改寫前的算會讓
    # 這筆紀錄掛在一個之後再也不出現的 qid 上，同一題的耗時就串不起來。
    question = rewritten or state["question"]
    qid = _qid(question)
    usage = _ollama_usage(resp)
    log_duration(log, "rewrite_question", started, node="rewrite_question",
                 model=_model_of(state), qid=qid, **usage)
    _warn_if_truncated("rewrite_question", qid, usage)
    return {**state, "question": question}


class ExtractedFilters(BaseModel):
    companies: list[str] = []
    doc_type: Literal["financial_report", "news"] | None = None
    news_since_days: int | None = None
    # 使用者是否明講了要看哪個市場。雙掛牌公司（台積電＝2330／TSM）兩邊數字的幣別、
    # 期間與每股基準都不同，沒講清楚就直接挑一邊等於替使用者猜，故據此決定要不要反問。
    market: Literal["tw", "us", "both"] | None = None
    # 問題是否屬於財經範疇。預設 True：模型漏填時當成正常問題照走檢索，
    # 漏放只是多跑一輪，誤判成離題則是正常問題直接被拒答，代價高得多。
    in_scope: bool = True
    # answer_shape 與 doc_type 刻意分開：doc_type 是「這筆資料是什麼類型」（DB 欄位、
    # 檢索過濾、保留策略、MCP 協定都吃它）；answer_shape 是「使用者要什麼形式的回答」。
    # 兩者常相關但不等價——「這則新聞對股價的影響」doc_type=news 卻需要估值欄位。
    # 預設 "full"：漏判只是多輸出幾欄，誤判成 news 會讓投資題失去素材，代價不對稱。
    answer_shape: Literal["news", "full"] = "full"

    @field_validator("companies")
    @classmethod
    def _normalize_companies(cls, v: list[str]) -> list[str]:
        """逐項正規化並去重，保留出現順序；認不得的代號直接丟掉。"""
        out = []
        for raw in v:
            n = normalize_ticker(raw) if raw else None
            if n and n not in out:
                out.append(n)
        return out

    @field_validator("news_since_days")
    @classmethod
    def _clamp_days(cls, v: int | None) -> int | None:
        """夾在 1..365。這個值直接進 SQL 日期比較，模型回 0 或負數會查成「未來的新聞」而全空。"""
        return None if v is None else max(1, min(v, 365))


def _known_codes_block() -> str:
    """把已收錄公司的中文名與代號列給 LLM 抄。

    模型對冷門代號的記憶不可靠——實測「南茂科技」被填成 2306（正確 8150）、
    「IMOS」被填成 3045，代號錯了後面整條流程都在查別家公司。表就在手邊，直接給它抄。
    """
    lines = [f"   - {name}：{tw}（美股 {TW_US_DUAL_LISTED[tw]}）"
             for tw, name in DUAL_LISTED_NAMES.items()]
    lines += [f"   - {name}：{tw}" for tw, name in OTC_ONLY_NAMES.items()]
    return "\n".join(lines)


def _collapse_dual_listing(companies: list[str]) -> list[str]:
    """同一家公司的兩個掛牌被抽成兩個元素時，收斂成台股那一邊。

    「聯電台股美股兩邊比較一下」實測穩定抽出 ['2303', 'UMC']——prompt 要的是「所有
    指名的代號」，而「兩邊」對模型就是兩個代號。但這語意是同一家公司的併陳，不是
    多標的比較，留兩個元素會同時踩到三處 len(companies) > 1 的分支：繞過雙掛牌反問
    與 both 併陳、決策卡開出 comparison 把同一家公司當兩家比、逐家重複抓同一家新聞。

    在抽取端收斂而非在 resolve_market 擋，是因為那三處共用同一個 companies，改源頭
    一次三處都對。判別式是查表比對（dual_listed_peer），順序無關，且不會誤傷真正的
    多標的：['2330','2303'] 是兩家不同公司，['2330','UMC'] 亦然。

    ponytail: 只處理「剛好兩個元素」。['2330','TSM','AAPL'] 這種一組雙掛牌加第三家
    語意真的模糊（可能是台積電兩邊 vs 蘋果），題組裡沒有，不猜，維持現行多標的行為。
    """
    if len(companies) == 2 and dual_listed_peer(companies[0]) == companies[1]:
        return [c for c in companies if is_tw_ticker(c)] or companies[:1]
    return companies


def extract_filters(state: GraphState) -> GraphState:
    """從問題中抽取公司代號 / 文件類型 / 新聞時效窗，抽不出來就設為 None（不過濾）。"""
    # 反問按鈕選完後的重跑：companies 與 market 上一輪都已定案，重抽只會得到同樣的
    # companies 與一個馬上被覆蓋的 market，白花一次 LLM 呼叫。其餘抽取欄位由呼叫端
    # 從上一輪帶過來（見 app.py 的重跑 state）。
    if state.get("market_confirmed") and state.get("companies"):
        return state

    prompt = f"""你是財經助理的前處理模組。請從使用者問題中判斷：
1. companies: 問題指名的所有公司代號組成的陣列，元素是台股代號（4-6 碼數字，如 "2330"）
   或美股 ticker（1-5 個大寫英文字母，如 "AAPL"）；沒有指名就給空陣列 []，只有一家就給
   一個元素的陣列；公司名稱要轉成代號/ticker（如 台積電→"2330"、蘋果→"AAPL"）。
   下列公司請「務必」照這張對照表填，不要憑印象自己想代號：
{_known_codes_block()}
2. doc_type: "financial_report"（財報相關）或 "news"（新聞相關），不確定就設為 null
3. news_since_days: 問題要求的新聞時效窗，換算成天數的整數。對照：
   「今天／即時／現在」→ 1；「這幾天／本週／這星期」→ 7；「這個月／近一個月」→ 30；
   「最近／近期／最新」→ 90；「上一季／近三個月」→ 90；「今年／近一年」→ 365。
   問題沒有任何時效意味（例如「2330 的營收多少？」）就設為 null，表示不限日期
4. 完全抽不到公司的情況，companies 設為空陣列 []
5. market: 使用者「明講」要看哪個市場就填 "tw" 或 "us"，明講兩邊都要（如「台股美股都
   看」「兩邊比較」）填 "both"，沒提到市場就填 null。判斷依據只看問法本身：
   - 講「台股」「上市」「台灣」，或直接給台股代號（2330）→ "tw"
   - 講「美股」「ADR」「美國」，或直接給美股 ticker（TSM）→ "us"
   - 只講中文公司名（「台積電」）而沒提市場 → null，不要自己猜
   注意 companies 一律照第 1 點填代號，market 只反映「使用者有沒有講」，兩者互不影響
6. in_scope: 問題是否屬於「上市公司財報、股市、投資、總體經濟」範疇。
   屬於（含一般性的財經知識問題，如「法說會通常看什麼」「除權息要注意什麼」
   「電動車供應鏈有哪些」，這類沒指名公司但仍是財經問題）→ true
   完全不屬於（天氣、食物、健康、旅遊、程式、閒聊）→ false
   拿不定主意就填 true——漏放只是多跑一輪檢索，誤判會讓正常問題直接被拒答
7. answer_shape: 使用者想要的「回答形式」，與第 2 點的資料類型無關。
   - "news"：只想知道發生了什麼事、有什麼影響（如「2330 最近有什麼新聞」
     「NVDA 出了什麼事」），不要求估值、分析師共識或投資建議
   - "full"：需要投資判斷素材（如「該不該買」「估值合理嗎」「最新財報表現」），
     或問題同時涉及新聞與投資決策（如「這則新聞對股價的影響」）
   拿不定主意就填 "full"——少給欄位會讓需要判斷的使用者拿不到素材

使用者問題：{state['question']}
"""
    qid = _qid(state["question"])
    # ponytail: 抽取模型可與主模型不同（config.FILTERS_MODEL），空值即沿用主模型。
    # _llms 以模型名為 key，換模型只是多一個快取項，不必另建實例管理。
    model = config.FILTERS_MODEL or _model_of(state)
    started = time.monotonic()
    # 本節點目前拿不到 usage：with_structured_output 預設只回傳解析後的 Pydantic
    # 物件，原始 AIMessage（含 response_metadata）不在回傳值裡。改成
    # with_structured_output(..., include_raw=True) 可以拿到，但回傳型態會變成
    # {"raw","parsed","parsing_error"} 的 dict，下面 parsed.companies 等既有呼叫
    # 與對應測試都要跟著改——這會動到既有行為，故本次先不做，留給下次要補這個
    # 節點的 usage 時再處理。
    try:
        parsed = _llms(model)["filters"].invoke(prompt)
    except Exception as e:  # noqa: BLE001  結構化輸出解析失敗（模型偏離格式）時降級成不過濾
        log_duration(log, "extract_filters 結構化輸出失敗", started, node="extract_filters",
                     model=model, qid=qid, ok=False, error=str(e))
        return {**state, "companies": [], "doc_type": None, "news_since_days": None,
                "market": None, "in_scope": True, "answer_shape": "full"}
    log_duration(log, "extract_filters", started, node="extract_filters",
                 model=model, qid=qid, ok=True)

    # 呼叫端已指定市場（UI 按鈕點選）時不得被重抽的結果蓋掉——問句本身沒有市場字樣，
    # 重抽必然回 None，等於把使用者剛按下的選擇丟掉又問一次
    market = state.get("market") or parsed.market
    companies = parsed.companies or (state.get("companies") if state.get("market") else []) or []
    companies = _collapse_dual_listing(companies)
    return {**state, "companies": companies, "doc_type": parsed.doc_type,
            "news_since_days": parsed.news_since_days, "market": market,
            "in_scope": parsed.in_scope, "answer_shape": parsed.answer_shape}


def _last_dual_listed(history: list[tuple[str, str]]) -> str | None:
    """從最近的對話往回找上一輪問到的雙掛牌公司代號；找不到回 None。

    只認代號與已收錄的公司名，不做模糊比對——寧可找不到而走一般流程，
    也不要猜錯公司後拿別家數字回答。
    """
    for user, _assistant in reversed(history):
        text = user.upper()
        for tw, name in DUAL_LISTED_NAMES.items():
            if tw in user or name in user or TW_US_DUAL_LISTED[tw] in text.split():
                return tw
    return None


def _primary(state: GraphState) -> str | None:
    """多標的情境下沿用單一公司語意的地方取第一家。

    ponytail: 市場快照、雙掛牌反問、ADR 提醒都是單一公司概念，多標的時
    全部照顧代價遠大於收益；要逐家併陳時再改 generate 的 prompt 結構。
    """
    companies = state.get("companies") or []
    return companies[0] if companies else None


def _is_off_topic(state: GraphState) -> bool:
    """問題是否完全不在財經範圍（天氣、食譜、閒聊），需請使用者改問。

    只看 extract_filters 抽出的 in_scope——那是 LLM 讀懂問題後的判定，
    22 題實測全對，包含相似度門檻擋不掉的「今天天氣如何」「明天會下雨嗎」
    與門檻會誤殺的「法說會通常看什麼」「電動車供應鏈有哪些」。
    判斷併在既有那次 LLM 呼叫裡，不增加延遲。

    ponytail: 曾用相似度門檻當防呆（in_scope 判離題時再確認庫內真的沒資料），
    實測反而更差——短句中文閒聊對本語料的相似度天然落在 0.50 附近，
    「今天天氣如何」0.51、「今天心情不好」0.52 都會越過門檻，把正確的判定推翻。
    弱訊號否決強訊號只會損失準確率，故移除。若日後換模型導致 in_scope 不穩，
    要補的是 few-shot 例子或校準提示，不是把門檻加回來。

    有指名公司一律不判離題——company 過濾本身就是最強的條件，庫內沒這家會直接回空，
    走既有的補抓流程（fetch_company_data），不該在這裡攔下。
    """
    return not state.get("companies") and not state.get("in_scope", True)


# 問句裡「使用者確實講了市場」的字樣。這裡不重做市場判斷，只回答一個更窄的問題：
# 使用者到底有沒有提。extract_filters 抽出的 market 只有 resolve_market 一個消費者，
# 而它唯一要的就是「該不該反問」，故把判斷放在消費端，不動 prompt——09-17／09-18
# 已有兩次「加 prompt 約束反而擠掉同一欄原本職責」的前例。
_TW_WORDS = ("台股", "臺股", "台灣", "臺灣", "上市", "櫃買")
_US_WORDS = ("美股", "美國", "ADR", "adr", "NYSE", "NASDAQ", "那斯達克", "紐約")
_BOTH_WORDS = ("兩邊", "雙邊", "都要", "兩地", "台美", "臺美")


def _market_in_question(question: str) -> str | None:
    """使用者自己講了哪個市場：回 "tw"/"us"/"both"，None 表示他根本沒講。

    只認問句裡明白講出的市場字樣。**打了代號不算表態**：使用者可能只是記得公司的代號
    （「2330 最新財報重點？」），不代表他選了台股那一邊；雙掛牌標的兩邊的幣別、期間、
    每股基準都不同，猜錯的代價大於多問一句。代號與中文公司名一律視為沒講，交給反問。
    """
    tw = any(w in question for w in _TW_WORDS)
    us = any(w in question for w in _US_WORDS)
    if (tw and us) or (any(w in question for w in _BOTH_WORDS) and (tw or us)):
        return "both"
    if tw:
        return "tw"
    if us:
        return "us"
    return None


def resolve_market(state: GraphState) -> GraphState:
    """雙掛牌標的且使用者沒指明市場時，把 company 換成使用者確認過的那一邊。

    只認問句裡明講的市場字樣（「美股」「台股美股兩邊」）才直接照辦；只給代號不算表態
    （打 2330／TSM 可能只是記得代號），一律反問。雙掛牌兩邊的幣別、期間與每股基準都
    不同，猜錯的代價大於多問一句。
    market="both" 則保留原代號並標記，由 generate 併陳兩市場並提醒不可直接相除。
    """
    company = _primary(state)
    market = state.get("market")
    answering_reask = False
    if company is None and market and state.get("history"):
        # 使用者是在回答上一輪的「要台股還是美股」，答句本身（「美股」）不含公司名，
        # 改寫也未必補得回來，故從上一輪問句把雙掛牌代號撿回來，否則會變成不限公司檢索
        company = _last_dual_listed(state["history"])
        answering_reask = True

    # ponytail: 多標的比較時不卡市場反問——兩家公司比較還要先選市場體感很差，
    # 且雙掛牌 + 多標的是罕見交集。要逐家各問一次市場再說。
    if len(state.get("companies") or []) > 1:
        out = {**state, "ask_market": False, "peer_company": None, "off_topic": False}
        _log_resolve_market(state, out)
        return out

    peer = dual_listed_peer(company) if company else None
    if peer is None:
        out = {**state, "companies": [company] if company else [], "ask_market": False,
               "off_topic": _is_off_topic({**state, "companies": [company] if company else []})}
        _log_resolve_market(state, out)
        return out

    # ponytail: 不信任 LLM 抽出的 market 值，只信任問句本身。模型會違反 prompt 第 5 點
    # 自己猜一邊（實測「2330 的營收多少？」抽出 tw），猜了就跳過反問＝替使用者選邊；
    # 也會把明講的「台股美股兩邊」抽成單邊。問句字樣是確定性的，故以它為準。
    # 兩種「市場已經是使用者親口確認過」的情形要跳過校正，否則問句沒有市場字樣就會被
    # 打回 None，變成問了又問的無限反問：market_confirmed 是按下按鈕那條路，
    # answering_reask 是使用者打字回答上一輪反問那條路（答句「美股」裡沒有公司名）。
    if not state.get("market_confirmed") and not answering_reask:
        market = _market_in_question(state.get("question", ""))
        # 校正結果要寫回 state：下游的 assemble 與 generate 讀的是 state["market"]，
        # 只改區域變數的話 both 會在這裡被判對、到下游卻仍讀到舊的單邊值。
        state = {**state, "market": market}

    if market is None:
        # 沒講市場：停下來問，不要替使用者猜一邊
        out = {**state, "companies": [company] if company else [], "ask_market": True,
               "peer_company": peer, "off_topic": False}
        _log_resolve_market(state, out)
        return out

    if market == "both":
        out = {**state, "companies": [company] if company else [], "ask_market": False,
               "peer_company": peer, "off_topic": False}
        _log_resolve_market(state, out)
        return out

    # 講了市場：把 company 對齊到該市場的代號（問「台積電美股」會抽到 2330，要換成 TSM）
    want_tw = market == "tw"
    company = company if is_tw_ticker(company) == want_tw else peer
    out = {**state, "companies": [company] if company else [], "ask_market": False,
           "peer_company": None, "off_topic": False}
    _log_resolve_market(state, out)
    return out


def _log_resolve_market(state: GraphState, out: GraphState) -> None:
    """統一在此記錄各分支的判定結果，取代 5 個 return 各寫一次 log。"""
    log.info("resolve_market", extra={"fields": {
        "node": "resolve_market", "qid": _qid(state.get("question", "")),
        "companies": out.get("companies"), "market": out.get("market"),
        "peer_company": out.get("peer_company"), "ask_market": out.get("ask_market"),
    }})


# 補給決策卡當市場脈絡的新聞條數；候選要多撈幾倍，去重後才補得滿
_MARKET_NEWS_K = 2

# 保留給「最新一期財報」的名額。顆粒度不對稱讓最新財報在純相似度排序裡撈不到
# （見 vectorstore.similarity_search 的 latest_source_only），故給它固定席位而非
# 改動全局排序——後者會傷到「比較去年同期」這類本來就需要舊資料的問法。
# 2 是因為台股結構化財報整季就壓成 2 塊（損益表 + 資產負債表）。
_LATEST_REPORT_K = 2


def _merge_latest_report(docs: list[dict], candidates: list[dict]) -> list[dict]:
    """把最新一期財報的 chunk 併到結果「最前面」，已存在的不重複加。

    放最前面是刻意的：assemble 依出現順序編引用編號，而 generate 的 context 也照序排，
    最新一期該在舊資料之前被讀到。舊資料不移除——「比較去年同期」需要它們。
    """
    seen_ids = {d["id"] for d in docs}
    extra = [d for d in candidates if d["id"] not in seen_ids][:_LATEST_REPORT_K]
    for d in extra:
        d["latest_period"] = True
    return extra + docs


def retrieve_context(question: str, company: str | None = None, doc_type: str | None = None,
                     news_since_days: int | None = None, market: str | None = None) -> list[dict]:
    """向量檢索 + 既有的補資料規則（doc_type 濾空放寬重查、財報補新聞、補全域市場新聞）。

    news_since_days 由 extract_filters 的 LLM 從問題判斷（None 表示不限日期），
    四次檢索共用同一個值。不依賴 GraphState，供 LangGraph 節點與未來的 MCP tool 共用。
    """
    started = time.monotonic()
    query_vec, cache_hit = _embed_query_cached(question)
    embed_ms = round((time.monotonic() - started) * 1000)

    # "both" 是「兩邊都要」＝不限制，不是第三個市場值；不在這裡收掉的話會被當成
    # market='both' 帶進 SQL，過濾出零筆。
    market = market if market in ("tw", "us") else None

    parallel = bool(company) and config.RETRIEVE_PARALLEL
    if parallel:
        docs = _retrieve_parallel(query_vec, company, doc_type, news_since_days, market)
    else:
        docs = _retrieve_sequential(query_vec, company, doc_type, news_since_days, market)

    # pool 統計是決定 max_size 的依據：requests_waiting 持續大於 0 代表連線不夠用，
    # 三段並行各佔一條，連線不足時會等到 timeout 而不是變慢
    stats = pool.get_stats()
    log_duration(log, "retrieve_context", started, node="retrieve", parallel=parallel,
                 qid=_qid(question), cache_hit=cache_hit, embed_ms=embed_ms, chunks=len(docs),
                 pool_waiting=stats.get("requests_waiting", 0),
                 pool_size=stats.get("pool_size", 0))
    return docs


def _relax_doc_type(query_vec, company, news_since_days, market=None) -> list[dict]:
    """doc_type 濾到空就放寬重查，避免問「財報」時把僅有的新聞全濾光。

    標記放寬過，讓呼叫端能告訴 LLM「拿到的不是原本要的類型」；
    掛在每筆 dict 上而非改回傳結構，assemble 與既有測試都不受影響。
    """
    docs = similarity_search(query_vec, company=company, news_since_days=news_since_days,
                             market=market)
    return [{**d, "relaxed": "doc_type"} for d in docs]


def _merge_market_news(docs: list[dict], candidates: list[dict]) -> list[dict]:
    """補 _MARKET_NEWS_K 條市場新聞給決策卡當市場脈絡；候選多撈後去重回補。

    多撈候選再去重，避免撈回的正好都已在 docs 裡而補成 0 條。
    """
    seen_ids = {d["id"] for d in docs}
    extra = []
    for d in candidates:
        if d["id"] in seen_ids:
            continue
        seen_ids.add(d["id"])
        extra.append(d)
        if len(extra) == _MARKET_NEWS_K:
            break
    return docs + extra


def _wants_latest_report(company, doc_type) -> bool:
    """要不要保留最新財報的席位。

    只在「指名公司的財報問題」成立：沒有 company 就無從定義「最新一期」（子查詢依
    company 取 max），doc_type != financial_report 時硬塞財報會擠掉新聞席位。
    刻意不看「最新」這類字眼——問「2330 財報如何」同樣不該拿到半年前的 PDF，
    而真要比較去年同期的問法拿到的舊 chunk 仍在結果裡，只是排在後面。
    """
    return bool(company) and doc_type == "financial_report"


def _latest_report_docs(query_vec, company, doc_type) -> list[dict]:
    """撈最新一期財報裡最相似的幾塊；多撈一點讓 _merge_latest_report 去重後補得滿。"""
    return similarity_search(
        query_vec, top_k=_LATEST_REPORT_K * 2, company=company, doc_type=doc_type,
        latest_source_only=True,
    )


def _retrieve_sequential(query_vec, company, doc_type, news_since_days, market=None) -> list[dict]:
    """循序版本：無 company 時的唯一路徑，也是 RETRIEVE_PARALLEL=0 的回退路徑。

    market 只在沒有 company 時真正起作用——有 company 時市場已由代號鎖定。
    但市場新聞那段補充無論如何都要帶上：它刻意不限公司，正是市場外洩的通道。
    """
    docs = similarity_search(
        query_vec, company=company, doc_type=doc_type, news_since_days=news_since_days,
        market=market,
    )
    if not docs and doc_type:
        docs = _relax_doc_type(query_vec, company, news_since_days, market)
    if not company:
        return docs

    # 放寬過 doc_type 代表原本要的類型撈不到，此時的 docs 已不是財報，不該再插財報席位
    if docs and _wants_latest_report(company, doc_type) and not docs[0].get("relaxed"):
        docs = _merge_latest_report(docs, _latest_report_docs(query_vec, company, doc_type))

    if docs and not any(d["doc_type"] == "news" for d in docs):
        # 財報問題也補 3 條新聞給趨勢段當素材，沒有就交給 LLM 決定要不要補抓
        docs = docs + similarity_search(
            query_vec, top_k=3, company=company, doc_type="news",
            news_since_days=news_since_days,
        )
    if docs:
        # exclude_company 排掉查詢公司自己（否則語意檢索多半又撈回同一家，補了等於沒補；
        # 市場新聞掃描認得出標題公司時會填代號、認不出才是 NULL，所以「全域」不等於
        # company IS NULL，用排除法才涵蓋得完整）；order_by_recency 讓脈絡取新不取準。
        docs = _merge_market_news(docs, similarity_search(
            query_vec, top_k=_MARKET_NEWS_K * 6, doc_type="news",
            news_since_days=news_since_days, exclude_company=company, order_by_recency=True,
            market=market,
        ))
    return docs


def _retrieve_parallel(query_vec, company, doc_type, news_since_days, market=None) -> list[dict]:
    """同公司新聞與市場脈絡最後是否採用要看主檢索結果，但 SQL 本身不依賴它；先並行取
    候選、後過濾即可省掉兩段等待。採用條件與順序和 _retrieve_sequential 完全相同。"""
    want_latest = _wants_latest_report(company, doc_type)
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rag-retrieve")
    try:
        primary: Future = executor.submit(
            similarity_search, query_vec, company=company, doc_type=doc_type,
            news_since_days=news_since_days, market=market,
        )
        latest_report: Future | None = executor.submit(
            _latest_report_docs, query_vec, company, doc_type,
        ) if want_latest else None
        company_news: Future = executor.submit(
            similarity_search, query_vec, top_k=3, company=company, doc_type="news",
            news_since_days=news_since_days,
        )
        market_news: Future = executor.submit(
            similarity_search, query_vec, top_k=_MARKET_NEWS_K * 6, doc_type="news",
            news_since_days=news_since_days, exclude_company=company, order_by_recency=True,
            market=market,
        )

        docs = primary.result()
        if not docs and doc_type:
            # doc_type 放寬是主結果為空才成立，無法預先決定；其餘候選仍可平行等待。
            docs = _relax_doc_type(query_vec, company, news_since_days, market)

        # 與循序版同一個條件與順序：放寬過就不插財報席位
        if docs and latest_report is not None and not docs[0].get("relaxed"):
            docs = _merge_latest_report(docs, latest_report.result())

        if docs and not any(d["doc_type"] == "news" for d in docs):
            docs = docs + company_news.result()

        if docs:
            docs = _merge_market_news(docs, market_news.result())
        return docs
    finally:
        # 未採用的預取不該拖慢「主檢索為空」或「主結果已有新聞」的回覆；已經開始的
        # DB 查詢讓它自行收尾，尚未開始的則取消。需要的 future 都已在上方 result() 完成。
        executor.shutdown(wait=False, cancel_futures=True)


def fetch_missing_data(company: str | None, has_report: bool) -> list[str]:
    """company 為 None 時只補市場總覽新聞；has_report=True 時只補新聞不重抓財報。

    不依賴 GraphState，供 LangGraph 節點與未來的 MCP tool 共用。單一來源失敗不中斷，
    回傳每個來源的結果訊息（成功或失敗皆含），供呼叫端判斷是否要提示使用者。
    """
    try:
        # 延遲 import，避免循環依賴
        from .update import (
            fetch_edgar, fetch_market_news, fetch_mops, fetch_news, fetch_sec_financials,
            fetch_tw_financials,
        )
    except ImportError as e:  # 環境缺套件時降級成不抓，不炸整個對話
        msg = f"匯入失敗（環境缺套件？）：{e}"
        log.error("auto_fetch %s", msg, extra={"fields": {"node": "auto_fetch"}})
        return [msg]

    calls = []
    if company:
        if is_tw_ticker(company):
            # 台股財報走兩軌：官方 OpenAPI 拿精準數字，MOPS 拿 PDF 的文字敘述
            # （管理層討論、風險、展望）。兩軌各自獨立成敗，一軌掛掉仍有另一軌。
            calls = [
                (company, "fetch_tw_financials", lambda: fetch_tw_financials(company)),
                (company, "fetch_mops", lambda: fetch_mops(company)),
                (company, "fetch_news", lambda: fetch_news(company)),
            ]
        else:
            # 美股財報也走兩軌：XBRL 拿精準數字，EDGAR 拿申報全文的文字敘述。
            # 數字在前、新聞維持最後（has_report 靠 calls[-1:] 取新聞，順序是契約）
            calls = [
                (company, "fetch_sec_financials", lambda: fetch_sec_financials(company.upper())),
                (company, "fetch_edgar", lambda: fetch_edgar(company.upper())),
                (company, "fetch_news", lambda: fetch_news(company.upper())),
            ]
        # 已有該公司財報才只補新聞；只有新聞時財報照抓（原本檢查整個 retrieved，害外國發行人的財報永遠沒抓）
        # 依賴「新聞排在最後」這個順序，上面兩個分支都要維持
        if has_report:
            calls = calls[-1:]
    # ponytail: 市場總覽新聞一律補掃，source_exists 會跳過已入庫的，重複觸發便宜
    # company=None：市場總覽與特定公司無關，掛在當次查詢的公司名下會灌水該公司的抓取成功率
    calls.append((None, "fetch_market_news", lambda: fetch_market_news(3)))

    results = []
    for call_company, source, call in calls:
        started = time.monotonic()
        try:
            # 取 FetchResult.ok 而非「沒拋例外就算成功」：查無 CIK、OpenAPI 查無公司、
            # MOPS 改版等失敗都是正常返回 FetchResult(False, ...)，原本全被記成成功。
            result = call()
            results.append(result.detail)
            log_duration(log, "auto_fetch 單一來源完成", started, node="auto_fetch",
                         company=call_company, source=source, ok=result.ok)
        except Exception as e:  # noqa: BLE001  單一來源失敗不中斷
            msg = f"抓取失敗：{e}"
            log_duration(log, "auto_fetch 單一來源失敗", started, node="auto_fetch",
                         company=call_company, source=source, ok=False, error=str(e))
            results.append(msg)
    return results


# ponytail: tool 呼叫輪數上限，取代原本 fetched 布林的「只重試一次」保護。
# LLM 補抓失敗時可能反覆重試，每次都是真實的外部網路請求，必須有硬上限。
# 值由 config 讀環境變數，供 A/B 在同一份程式碼上切換（見 config.MAX_TOOL_ROUNDS）。
_MAX_TOOL_ROUNDS = config.MAX_TOOL_ROUNDS

_mcp_client = MultiServerMCPClient({
    "finance": {
        "transport": "streamable_http",
        "url": config.MCP_SERVER_URL,
        "headers": (
            {"Authorization": f"Bearer {config.MCP_AUTH_TOKEN}"}
            if config.MCP_AUTH_TOKEN else None
        ),
    }
})


def _seed_prompt(state: GraphState) -> str:
    """組 agent 首次進入迴圈的引導訊息，把已知條件交代清楚免得 LLM 重猜。

    # ponytail: 一定要帶今天日期——實測模型會正確讀出資料的發布日期，卻因為不知道
    # 今天是哪天而判定兩個月前的資料「已足夠」，導致該補抓時沒補抓。
    """
    known = [f"今天日期：{dt.date.today()}"]
    companies = state.get("companies") or []
    if len(companies) == 1:
        known.append(f"已知公司代號：{companies[0]}")
    elif len(companies) > 1:
        known.append(
            f"使用者問題同時指名多個標的：{'、'.join(companies)}。"
            f"請「分別」以每一個代號各檢索一次（每次檢索的 company 參數只填一個代號），"
            f"每一家的資料都要拿到，不可只查其中一家。"
        )
    if state.get("peer_company") and state.get("market") == "both":
        # 兩市場各自獨立入庫、company 欄位不同，一次檢索只查得到一邊，必須分開查兩次
        known.append(
            f"這家公司同時在台美兩地掛牌，使用者要求兩邊都看："
            f"請分別以 {companies[0]} 與 {state['peer_company']} 各檢索一次，兩邊資料都要拿到。"
        )
    if state.get("doc_type"):
        known.append(f"已知文件類型：{state['doc_type']}")
    if state.get("news_since_days"):
        known.append(f"使用者要求的新聞時效：只看最近 {state['news_since_days']} 天內的新聞，"
                     f"請把這個天數帶進檢索工具的 news_since_days 參數")
    # 市場是程式已經判定好的（extract_filters／resolve_market），直接指名讓模型照填，
    # 不要它自己從問句再推一次——推錯就會撈回使用者沒問的那個市場。
    # "both" 不指名：那是「兩邊都要」，限制任一邊都會漏掉另一邊。
    if state.get("market") in ("tw", "us"):
        label = "台股" if state["market"] == "tw" else "美股"
        known.append(f"本次檢索的市場：{label}（{state['market']}）。"
                     f"請把 {state['market']} 填進檢索工具的 market 參數，"
                     f"不要檢索另一個市場的資料")
    known_block = "\n".join(known)
    return f"""使用者問題：{state['question']}
{known_block}

請用工具查詢財經資料庫回答上述問題所需的資料。檢索結果會標明每筆資料距今幾天，
請依工具說明判斷是否夠新；不夠新就補抓後再查一次。
取得足夠資料後就停止呼叫工具即可，不需要自己寫出回答——後續會有另一個步驟根據你查到的
資料生成最終回覆。"""


def _trim_for_llm(messages: list[BaseMessage]) -> list[BaseMessage]:
    """送進 agent 的複本裡，把檢索結果的 chunks 拿掉，只留 summary_for_llm。

    chunks 是給 assemble 組引用用的結構化資料，tool 說明本來就叫模型別讀它，
    卻佔了 tool 回傳內容的 57%（實測單次檢索 7177 字中的 4064 字），而且每多跑一輪
    agent 就整份重送一次。state 裡保留完整內容給 assemble，只裁掉送進模型的複本。
    """
    trimmed = []
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.name == "search_knowledge_base":
            try:
                summary = json.loads(_tool_text(msg.content))["summary_for_llm"]
                msg = msg.model_copy(update={"content": summary})
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                log.warning("檢索結果無法裁切，原樣送進模型：%s", e,
                            extra={"fields": {"node": "agent"}})
        trimmed.append(msg)
    return trimmed


async def agent(state: GraphState) -> GraphState:
    """把 MCP tool 綁給 LLM，由它自行決定要呼叫哪個 tool、要不要再呼叫下一個。"""
    tools = await _mcp_client.get_tools()
    messages = state.get("messages") or [HumanMessage(content=_seed_prompt(state))]
    # 實測模型讀到「該補抓」會照做，卻補錯家：2454 距今 18 天該補、NVDA 距今 1 天
    # 不用補，它去補了 NVDA。工具 header 是逐次回傳的，模型得自己記住哪次結果對應
    # 哪一家——程式這邊早就知道了，直接指名，不要它自己對應。
    directive = []
    stale, missing = _stale_companies(state)
    if stale or missing:
        # missing 沒有天數可填，措辭與 stale 分開，硬湊數字會讓訊息與 log 都失真
        parts = [f"{c} 的新聞距今 {age} 天，已過期，請對 {c} 呼叫 fetch_company_data"
                 for c, age in stale]
        parts += [f"{c} 完全沒有檢索到新聞，請對 {c} 呼叫 fetch_company_data"
                  for c in missing]
        directive = [HumanMessage(content="；".join(parts) + "。補抓後請以同樣的代號重新檢索。")]
        log.info("指名過期標的", extra={"fields": {
            "node": "agent", "stale": [c for c, _ in stale], "missing": missing}})
    messages = messages + directive
    started = time.monotonic()
    resp = await _llms(_model_of(state))["tool"].bind_tools(tools).ainvoke(
        _trim_for_llm(messages)
    )
    # round 從既有訊息推算，與 agent_route 的算法一致，回測時可看出 tool loop 跑了幾輪、每輪多久
    rounds = sum(1 for m in messages if isinstance(m, AIMessage) and m.tool_calls)
    qid = _qid(state["question"])
    usage = _ollama_usage(resp)
    log_duration(log, "agent", started, node="agent", model=_model_of(state),
                 qid=qid, round=rounds + 1,
                 tool_calls=len(getattr(resp, "tool_calls", None) or []), **usage)
    _warn_if_truncated("agent", qid, usage)
    # directive 一併寫回 state：只塞給這次呼叫的話，下一輪模型讀到的歷史裡沒有它，
    # 又會回到「知道要補抓但不知道補哪家」。重複指名由 _news_ages_by_company 只讀
    # 最後一次補抓之後的檢索擋掉，不是靠舊 directive 自然失效。
    return {**state, "messages": directive + [resp]}


def agent_route(state: GraphState) -> str:
    """LLM 還要呼叫 tool 就去 tools，否則收工；超過輪數上限一律強制收工。"""
    rounds = sum(1 for m in state["messages"] if isinstance(m, AIMessage) and m.tool_calls)
    if rounds >= _MAX_TOOL_ROUNDS:
        log.info("已達 tool 呼叫輪數上限，停止呼叫工具",
                 extra={"fields": {"node": "agent", "rounds": rounds, "limit": _MAX_TOOL_ROUNDS}})
        return "assemble"
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else "assemble"


def _tool_text(content) -> str:
    """取出 ToolMessage 的文字內容。

    MCP tool 經 langchain-mcp-adapters 回來的是 content block 陣列
    （[{"type": "text", "text": ...}]），本地 tool 則是純字串，兩種都要能讀。
    """
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return str(content)


def assemble(state: GraphState) -> GraphState:
    """把 tool 回傳結果整理回下游節點沿用的既有欄位。

    retrieved 累積所有 search_knowledge_base 的 chunks 並依 id 去重——多標的與
    雙掛牌會分次檢索，只取最後一次會把前幾次的結果靜默丟掉；補抓後重查則會拿到
    重複的 id，不去重會讓 generate 的 context 出現整段重複內容。
    補抓類 tool 的訊息填進 fetched/fetch_results 供 no_result 使用。
    """
    retrieved: list[dict] = []
    seen: set = set()
    fetch_results: list[str] = []
    fetched = False
    for msg in state["messages"]:
        if not isinstance(msg, ToolMessage):
            continue
        if msg.name == "search_knowledge_base":
            try:
                chunks = json.loads(_tool_text(msg.content)).get("chunks", [])
            except (json.JSONDecodeError, TypeError, AttributeError) as e:
                log.warning("解析檢索結果失敗，視為查無資料：%s", e,
                            extra={"fields": {"node": "assemble"}})
                continue
            for c in chunks:
                if c.get("id") not in seen:
                    seen.add(c.get("id"))
                    retrieved.append(c)
        elif msg.name in ("fetch_company_data", "fetch_market_overview"):
            fetched = True
            fetch_results.append(_tool_text(msg.content))
    return {**state, "retrieved": retrieved, "fetched": fetched, "fetch_results": fetch_results}


def _news_age_days(doc: dict) -> int | None:
    """新聞距今幾天；非新聞、無發布日期或日期格式異常都回 None。"""
    if doc.get("doc_type") != "news":
        return None
    published = doc.get("published_at")
    if isinstance(published, str):
        try:
            published = dt.date.fromisoformat(published[:10])
        except ValueError:
            return None
    if not isinstance(published, dt.date):
        return None
    return (dt.date.today() - published).days


def _news_ages_by_company(state: GraphState) -> dict[str, list[int]] | None:
    """把所有 search_knowledge_base 回傳的新聞按 company 分組，各自算距今天數。

    多標的的新鮮度必須逐家判斷：合併後取 min 會讓最新的那家代表全部。
    直接讀訊息串而非 assemble(state)["retrieved"]，因為後者已經合併過。
    內容一律經 _tool_text：MCP tool 回來的是 content block 陣列而非字串，
    直接 json.loads 會丟 TypeError 被下面的 except 吞掉，靜默退化成「沒有新聞」。

    只看最後一次補抓之後的檢索。補抓前那次的結果描述的是補抓前的狀態，
    留著會讓 min 永遠停在舊天數——實測 2454 在 round 2 就補抓成功、新聞已是 0 天，
    卻因 round 1 的 16 天還在訊息串裡而被重複指名到輪數上限，白花 38.9 秒。
    assemble 反過來要累積全部歷史，那是檢索涵蓋率，與「現在最新是幾天」不同問題。

    若補抓之後一次檢索都沒有，回傳 None：這種情況無從判斷「新聞是否存在」，
    只代表還沒查——不能當成「查了但沒有」。
    """
    msgs = state["messages"]
    last_fetch = max(
        (i for i, m in enumerate(msgs)
         if isinstance(m, ToolMessage) and m.name == "fetch_company_data"),
        default=-1,
    )
    tail = msgs[last_fetch + 1:]
    if not any(isinstance(m, ToolMessage) and m.name == "search_knowledge_base" for m in tail):
        return None
    ages: dict[str, list[int]] = {}
    for m in tail:
        if not isinstance(m, ToolMessage) or m.name != "search_knowledge_base":
            continue
        try:
            chunks = json.loads(_tool_text(m.content)).get("chunks") or []
        except (json.JSONDecodeError, AttributeError, TypeError):
            continue
        for doc in chunks:
            company = doc.get("company")
            age = _news_age_days(doc)
            if company and age is not None:
                ages.setdefault(company, []).append(age)
    return ages


def _fresh_limit(state: GraphState) -> int:
    """新聞算「夠新」的天數上限，與 mcp_server.search_knowledge_base 的判準一致。

    問題明確要求近期（時效窗 <= 7 天）就要求當天的新聞，否則 3 天內都算夠新。
    時效窗由 extract_filters 抽出，與檢索過濾共用同一個判斷，不再各自比對問題字串；
    窗是 90 天（「最近三個月」）時要求當天新聞太嚴，故以 7 天為界而非「有值就收緊」。
    """
    days = state.get("news_since_days")
    return 0 if days is not None and days <= 7 else 3


def _stale_companies(state: GraphState) -> tuple[list[tuple[str, int]], list[str]]:
    """多標的時逐家判斷新鮮度，回傳（過期的家與其天數, 完全沒檢索到的家）。

    新鮮度必須逐家算：合併後取 min 會讓最新的那家代表全部（實測 ASML 65 天被全域
    新聞 0 天蓋掉）。route_after_tools 用它決定要不要回 agent，agent 用它把「哪一家
    過期」寫進訊息——實測模型收到「該補抓」會照做，卻補錯家，因為 header 是逐次
    回傳的，得自己記住哪次結果對應哪家。兩處共用這裡，判準才不會各自漂移。

    ages 為 None（補抓後尚未檢索）時兩者皆回空：沒有可判斷的檢索就不指名，
    交還 LLM 依 tool 說明自行先查庫，否則每家都會落進 missing，變成叫模型
    重抓剛抓完的公司、或在首輪還沒查庫時就白白補抓。
    """
    ages = _news_ages_by_company(state)
    if ages is None:
        return [], []
    limit = _fresh_limit(state)
    stale, missing = [], []
    for c in state.get("companies") or []:
        if not ages.get(c):
            missing.append(c)
        elif min(ages[c]) > limit:
            stale.append((c, min(ages[c])))
    return stale, missing


# 決策卡欄位 id，任何 shape 都無條件輸出（決策 9「不整段棄權」的迴歸防線）
_UNCONDITIONAL_FIELDS = ["conclusion", "facts", "inference", "upside", "risk"]
# news shape 預設不生成的五欄（決策 6）
_FULL_ONLY_FIELDS = ["valuation", "consensus", "scenario", "earnings_call", "recommendation"]
# 現行全 13 欄，ANSWER_SHAPE_GATING=0 時原樣回傳
_ALL_FIELDS = _UNCONDITIONAL_FIELDS + ["comparison"] + _FULL_ONLY_FIELDS + [
    "trigger", "next_event", "tracking_indicators",
]


def allowed_fields(state: GraphState, has_market: bool | None = None) -> list[str]:
    """依 answer_shape 與實際 evidence 決定本次允許輸出哪些欄位。

    唯一的 output schema decision source，generate 與 market_block 共用。
    純函式不碰網路，方便用 assert script 測試——這是本案唯一新增的抽象，
    由測試需求驅動，不是預留彈性。

    has_market=None 表示「行情尚未抓取」，此時依賴行情的欄位先留在候選集，
    供呼叫端判斷要不要抓；抓完後再以 True/False 呼叫一次定案(見兩段式)。
    """
    multi = len(state.get("companies") or []) > 1
    if not config.ANSWER_SHAPE_GATING:
        # 回退路徑也要濾家數，否則單一公司題會出現一張沒有比較對象的表
        return [f for f in _ALL_FIELDS if f != "comparison" or multi]

    shape = state.get("answer_shape") or "full"
    retrieved = state.get("retrieved") or []
    has_financial_report = any(d.get("doc_type") == "financial_report" for d in retrieved)
    has_news = any(d.get("doc_type") == "news" for d in retrieved)
    has_news_with_date = any(
        d.get("doc_type") == "news" and _news_age_days(d) is not None for d in retrieved
    )

    fields = list(_UNCONDITIONAL_FIELDS)

    if shape == "full":
        # 沒有檢索素材就不可能做定性對比，強行要求會直接違反反幻覺原則
        if multi and retrieved:
            fields.append("comparison")
        # has_market=None（第一段候選）視同「可能有」，先留在候選集供 needs_market 判斷
        market_ok = has_market is not False
        if market_ok:
            fields += ["valuation", "consensus", "scenario"]
        if has_financial_report:
            fields.append("earnings_call")
        if has_financial_report and has_news and market_ok:
            fields.append("recommendation")

    if retrieved:
        fields.append("trigger")
        fields.append("tracking_indicators")
    if has_news_with_date or has_market:
        fields.append("next_event")

    return fields


_FIELD_LINE_RE = re.compile(r"^- \*\*(.+?)\*\*[：:]", re.MULTILINE)


def append_disclaimer(answer: str, lang: str) -> str:
    """回答結尾補上免責聲明，已經有的話原樣回傳。

    冪等是必要的而不只是保險：streaming 端與 generate 節點都會經過這條路徑，
    不擋重複呼叫就會在畫面上看到兩句。
    """
    disclaimer = t(lang, "disclaimer")
    if not answer.strip() or disclaimer in answer:
        return answer
    return f"{answer.rstrip()}\n\n{disclaimer}"


def check_answer_format(answer: str, fields: list[str], ordered_count: int, lang: str,
                        source_markets: list[str | None] | None = None,
                        market: str | None = None) -> list[dict]:
    """事後檢查決策卡是否符合 prompt 訂的格式，只寫 log、不擋輸出、不改寫輸出。

    回傳結構化 dict 而非字串，是為了讓 log 之後能被彙總分析（例如數
    unknown_citation_marker 出現幾次、都是哪些標記），不是預留彈性。
    這裡只做 regex 與集合運算，不做任何會 raise 的操作，呼叫端不必包 try。
    """
    violations: list[dict] = []

    # (a) 欄位集合比對。預期欄名一律經 t() 取回，不手寫第二份清單，
    # 否則 i18n 改字會讓這裡的期望值悄悄與實際輸出脫鉤。
    expected_names = set()
    for f in fields:
        raw = t(lang, f"trend_field_{f}")
        m = _FIELD_LINE_RE.match(raw)
        if not m:
            # 抽不到就會讓該欄從預期集合消失，模型正確輸出它反而被誤報成
            # unexpected_fields——驗證層自己產生假警報，比沒有驗證層更糟。
            log.error("trend_field 不符 '- **欄名**：' 格式，欄位檢查將失準", extra={"fields": {
                "node": "check_answer_format", "field_id": f, "lang": lang, "raw": raw}})
            continue
        expected_names.add(m.group(1))

    actual_names = set(_FIELD_LINE_RE.findall(answer))
    missing = expected_names - actual_names
    unexpected = actual_names - expected_names
    if missing:
        violations.append({"rule": "missing_fields", "detail": sorted(missing)})
    if unexpected:
        violations.append({"rule": "unexpected_fields", "detail": sorted(unexpected)})

    # (b) 免責聲明
    if t(lang, "disclaimer") not in answer:
        violations.append({"rule": "missing_disclaimer", "detail": t(lang, "disclaimer")})

    # (c)(d) 引用標記：先分離「合法標記」與「其他中括號」，markdown 連結
    # 的 [text](url) 排除在外（後面緊接 "("）。
    # prompt 寫半形 []，但模型在中文語境實測輸出全形【】（含 [即時市場數據]），
    # 所以兩種都要認——只認半形等於對真實輸出全盲。
    label = t(lang, "citation_label").strip()
    citation_re = re.compile(rf"[\[【]{re.escape(label)}\s*(\d+)[\]】]")
    out_of_range = sorted({
        int(n) for n in citation_re.findall(answer) if not (1 <= int(n) <= ordered_count)
    })
    if out_of_range:
        violations.append({"rule": "citation_out_of_range", "detail": out_of_range})

    bracket_re = re.compile(r"[\[【]([^\]】]+)[\]】](?!\()")
    unknown = sorted({
        m.group(1) for m in bracket_re.finditer(answer)
        if not re.fullmatch(rf"{re.escape(label)}\s*\d+", m.group(1))
        # 欄名被當行內標籤用（prompt 要求「明確標示為推論」，模型就寫【推論】）
        # 是遵守指示，不是自創引用標記；不排除掉的話假警報會淹掉真正要數的東西。
        and m.group(1).strip() not in expected_names
    })
    if unknown:
        violations.append({"rule": "unknown_citation_marker", "detail": unknown})

    # (e) 跨市場引用：問美股卻引用了台股來源。正常流程走不到這裡——市場不明且是
    # 雙掛牌時 resolve_market 會停下來反問使用者（ask_market），問句講了市場則由
    # similarity_search 的 market 過濾把另一邊擋在檢索外，模型手上根本沒有那些素材。
    # 這條是那兩層萬一失效時的可觀測性：來源沒標市場（market 為 NULL）而混進來、
    # 或 both 路徑兩邊併陳時，都會在這裡留下記錄。
    # ponytail: 只寫 log 不擋輸出——前兩層是真正的防線，這層的作用是讓「防線破了」
    # 這件事數得出頻率。log 若真的開始出現再考慮升級成重生成。
    if market in ("tw", "us") and source_markets:
        wrong = sorted({
            n for n in (int(x) for x in citation_re.findall(answer))
            if 1 <= n <= len(source_markets)
            and source_markets[n - 1] in ("tw", "us")
            and source_markets[n - 1] != market
        })
        if wrong:
            violations.append({"rule": "cross_market_citation",
                               "detail": {"market": market, "cited": wrong}})

    return violations


def route_after_tools(state: GraphState) -> str:
    """檢索結果明顯夠用就直接收工，否則交還給 agent 決定下一步。

    只把「資料明顯夠用 → 停止呼叫工具」這一種判斷收回程式，判準與
    src/mcp_server.py 的 search_knowledge_base docstring 一致，但新鮮度必須
    跟那邊一樣逐家算：這裡的 retrieved 是各家與全域新聞合併後的結果，
    取 min 會讓最新的那筆代表全部（實測 ASML 65 天被全域新聞 0 天蓋掉），
    故多標的改為每家各自取自己的新聞天數，全都夠新才收工。資料不足、
    不夠新、有公司完全沒檢索到新聞、或剛跑完補抓 tool 時一律回 agent，
    「要不要補抓、補抓完要不要再查」仍然全部由 LLM 決定，09-07 改造的核心設計不變。

    省下的是純粹重複的第二輪決策：模型讀完檢索結果後只為了說一句「夠了，停」，
    實測就要花約 106 秒，佔單題總耗時四成。
    """
    last = next(
        (m for m in reversed(state["messages"]) if isinstance(m, ToolMessage)), None
    )
    # 剛跑完補抓 tool：要不要再查一次是 LLM 的決定，不能在這裡替它收工
    if last is None or last.name != "search_knowledge_base":
        return "agent"

    # 捷徑的前提是「一次檢索涵蓋全部所需資料」，多標的的 retrieved 是各家與全域市場
    # 新聞合併後的結果，min 會讓最新的那筆代表全部，過期的那家永遠等不到補抓。
    # 實測題「台積電與ASML」：ASML 新聞距今 65 天，卻因全域新聞 0 天而跳過 agent。
    # 但「回 agent」本身要價 96 至 277 秒，且模型常只回一句「夠了，停」，所以不是
    # 多標的就回，而是逐家各自取自己那次檢索的新聞天數——全都夠新才收工。
    # ponytail: 只認 chunks 上的 company 欄；沒有任何一家被檢索到時交還 LLM。
    if len(state.get("companies") or []) > 1:
        stale, missing = _stale_companies(state)
        if stale or missing:
            # 過期或漏查都回 agent；「哪一家過期」由 agent 節點寫進訊息，
            # 條件邊只能回字串、不能改 messages，故兩處共用 _stale_companies。
            return "agent"
        log.info("各家新聞都夠新，跳過 agent 決策", extra={"fields": {
            "node": "tools", "companies": state["companies"]}})
        return "assemble"

    ages = [age for doc in assemble(state)["retrieved"]
            if (age := _news_age_days(doc)) is not None]
    # 查無資料或結果中完全沒有新聞：交給 LLM 判斷要不要補抓
    if not ages:
        return "agent"
    limit = _fresh_limit(state)
    if min(ages) <= limit:
        log.info("新聞夠新，跳過 agent 決策", extra={"fields": {
            "node": "tools", "news_age_days": min(ages), "limit": limit}})
        return "assemble"
    return "agent"


def route_after_assemble(state: GraphState) -> str:
    return "generate" if state["retrieved"] else "no_result"


def route_after_resolve_market(state: GraphState) -> str:
    """本輪要不要檢索。兩種「先回問使用者就收工」的情況集中在這裡分岔。"""
    if state.get("ask_market"):
        return "ask_market"
    if state.get("off_topic"):
        return "off_topic"
    return "agent"


# 會跑很久的 tool（補抓要打外部站台並做 embedding，中位 67.6s），對照組是
# search_knowledge_base（中位 0.5s）。名稱與 mcp_server.py 的 @mcp.tool() 函式名綁定，
# 那邊改名這邊要跟著改——比對不中只會少一句提示，不影響回答正確性。
_FETCH_TOOLS = {"fetch_company_data", "fetch_market_overview"}


def is_fetching(update: dict) -> bool:
    """agent 這一輪選的 tool 裡有沒有補抓。update 是 agent 節點回傳的 state。

    放在 graph.py 而非顯示層：app.py 與 cli.py 兩個介面都要判斷，而 app.py 在模組
    層級 import chainlit，CLI 從那邊拿會把整個 chainlit 拖進來。
    """
    messages = (update or {}).get("messages") or []
    if not messages:
        return False
    # agent 回傳 directive + [resp]，LLM 的回應固定在最後一則
    calls = getattr(messages[-1], "tool_calls", None) or []
    return any(c.get("name") in _FETCH_TOOLS for c in calls)


def unique_sources(retrieved: list[dict]) -> list[str]:
    """依出現順序去重的來源列表，引用編號與來源列表共用這個順序。"""
    ordered = []
    for doc in retrieved:
        if doc["source"] not in ordered:
            ordered.append(doc["source"])
    return ordered


def _side_by_side(state: GraphState) -> list[str]:
    """本題要併陳的代號清單：market 為 both 且有 peer 時，把 peer_company 併入 companies。

    行情抓取、跨市場判斷、missing 清單三處都要看同一份清單，只有其中一處漏併 peer
    就會出現「判定成 both 卻只抓到一邊行情」的落差。
    """
    codes = list(state.get("companies") or [])
    if state.get("peer_company") and state.get("market") == "both":
        codes.append(state["peer_company"])
    return codes


def cross_market_split(state: GraphState) -> tuple[list[str], list[str]] | None:
    """本題要並排的代號是否橫跨台美兩市場；是則回 (台股代號, 美股代號)，否則 None。

    看的是最後要並排的那組代號，而非只看雙掛牌：多標的比較題（2330 vs NVDA）
    才是最需要幣別提醒的場合，而它沒有 peer_company。雙掛牌併陳是其中一個特例，
    peer_company 併進來一起判斷。
    """
    cross = _side_by_side(state)
    tw = [c for c in cross if is_tw_ticker(c)]
    us = [c for c in cross if not is_tw_ticker(c)]
    return (tw, us) if tw and us else None


def _adr_premium_block(lang: str, snapshots: dict, premium_text: str | None) -> str:
    """ADR_PREMIUM=off 時不附；兩邊行情都成功且溢價率算得出來才附上，任一邊缺就不硬湊。

    抽成純函式方便單元測試：generate() 需要 stub LLM 才能整段驅動，這段純字串組裝不需要。
    """
    if config.ADR_PREMIUM == "off" or len(snapshots) != 2 or not premium_text:
        return ""
    return f"\n\n### {t(lang, 'adr_premium_header')}\n{premium_text}"


def generate(state: GraphState) -> GraphState:
    # 計時起點在節點開頭而非 LLM 呼叫前：get_market_snapshot 是 blocking 網路呼叫且擋在
    # first token 前（實測 2.50-3.55s），不納進 elapsed_ms 就量不到它的影響。
    started = time.monotonic()
    lang = state.get("lang", "zh")
    src_label = t(lang, "citation_label")  # 引用標記跟隨回答語言（[來源1] / [Source 1]）
    ordered = unique_sources(state["retrieved"])
    context_blocks = []
    for idx, src in enumerate(ordered, start=1):
        docs = [d for d in state["retrieved"] if d["source"] == src]
        date = docs[0].get("published_at") or "日期未知"
        contents = "\n".join(d["content"] for d in docs)
        context_blocks.append(f"[{src_label}{idx}] {src}（{date}）\n{contents}")
    context = "\n\n".join(context_blocks)

    history_block = ""
    if state.get("history"):
        history_block = f"\n先前對話（僅供理解語境）：\n{_format_history(state['history'])}\n"

    market_block = ""
    companies = state.get("companies") or []
    # 第一段：行情尚未抓取，先算候選集
    candidate = allowed_fields(state, has_market=None)
    # 只要候選集裡有任一欄吃行情就抓——yfinance 是 blocking 且未快取的網路呼叫
    # (實測 2.50-3.55s)，擋在 first token 前面，抓來沒人用純屬浪費。
    needs_market = bool({"valuation", "consensus", "scenario"} & set(candidate))
    # 行情逐家併陳；抓失敗的家數在 prompt 中明講，不靜默留白
    # market=both 時要把 peer_company 併入，否則雙掛牌併陳只抓得到台股那一邊
    quote_codes = _side_by_side(state)
    snapshots: dict[str, str] = {}
    premium_block = ""
    # 雙掛牌併陳（market=both）時要順便算 ADR 溢價率；與行情抓取並行，
    # 否則會在 first token 前多擋一輪 yfinance 網路呼叫的時間。off 時完全不算。
    adr_split = None
    if (config.ADR_PREMIUM != "off" and state.get("market") == "both"
            and state.get("peer_company") and needs_market):
        adr_split = cross_market_split(state)
    premium_text = None
    if needs_market and quote_codes:
        market_started = time.monotonic()
        if adr_split:
            tw_codes, us_codes = adr_split
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="market_adr") as executor:
                snapshots_future = executor.submit(get_market_snapshots, quote_codes)
                premium_future = executor.submit(get_adr_premium, tw_codes[0], us_codes[0])
                snapshots = snapshots_future.result()
                premium_text = premium_future.result()
        else:
            snapshots = get_market_snapshots(quote_codes)
        # node 標 market 而非 generate：這是 generate 節點內的行情抓取，不是生成呼叫，
        # 兩者混在同一個 node 值會讓耗時彙總把 3-7 秒的抓取算進生成中位數。
        log_duration(log, "market_snapshots", market_started, node="market",
                     requested=len(quote_codes), succeeded=len(snapshots),
                     failed=len(quote_codes) - len(snapshots))
    if snapshots:
        blocks = "\n\n".join(f"### {c}\n{text}" for c, text in snapshots.items())
        note = ""
        missing = [c for c in quote_codes if c not in snapshots]
        if missing:
            note = t(lang, "market_partial_note",
                     shown="、".join(snapshots), others="、".join(missing)) + "\n"
        premium_block = _adr_premium_block(lang, snapshots, premium_text)
        blocks += premium_block
        market_block = (
            "\n即時市場數據（Yahoo Finance，僅供估值/時機參考，非檢索來源，不參與來源編號）：\n"
            f"{note}{blocks}\n"
        )
    # 第二段：行情結果已知，定案。全部抓失敗時依賴行情的欄位自動被剔除，
    # 不會留下一個沒有素材的空欄叫模型寫「資料不足」。
    fields = allowed_fields(state, has_market=bool(snapshots))

    # 本題橫跨台美兩市場時，明講兩邊不可直接換算——幣別、期間、每股基準三者都不同，
    # 沒這句提醒模型很容易把台幣 EPS 與美元 EPS 相除當成「匯率」或「溢價」。
    # 觸發看的是「最後要並排的那組代號」而非只看雙掛牌：多標的比較題（2330 vs NVDA）
    # 才是最需要這句的場合，而它沒有 peer_company。雙掛牌併陳是其中一個特例，
    # peer_company 併進來一起判斷。
    dual_block = ""
    split = cross_market_split(state)
    if split:
        tw, us = split
        dual_block = "\n" + t(lang, "dual_market_warning",
                              tw="、".join(tw), us="、".join(us)) + "\n"

    # 這些台股標的有 ADR 但取不到其財報，明講一句免得使用者以為系統漏了美股那邊
    otc = otc_adr_of(companies[0]) if len(companies) == 1 else None
    if otc:
        dual_block += "\n請在回答開頭附上這句說明：" + t(
            lang, "otc_adr_note",
            name=OTC_ONLY_NAMES.get(companies[0], companies[0]),
            us=otc, tw=companies[0],
        ) + "\n"

    # 跨市場素材的防線掛在哪裡由設定決定（見 config.CROSS_MARKET_GUARD）。預設掛在
    # 「已知事實」欄：它是唯一直接引用檢索素材、且必附 [來源N] 的欄位，素材market 不對
    # 的話第一個出問題的就是它；掛在共用規則區則會對每一欄都加一條約束。
    guard = t(lang, "cross_market_guard")
    field_lines = []
    for f in fields:
        line = t(lang, f"trend_field_{f}")
        if f == "facts" and config.CROSS_MARKET_GUARD == "facts":
            line += guard
        field_lines.append(line)

    trend_block = "\n".join([
        t(lang, "trend_header"),
        *field_lines,
        t(lang, "trend_rules_common")
        + (guard if config.CROSS_MARKET_GUARD == "common" else ""),
    ])

    prompt = f"""你是專業的財經分析助理。請根據下方參考資料回答使用者問題。
規則：
- 只根據參考資料回答，不要編造資料中沒有的數字或事實
- 回答中明確標示引用的來源編號，例如「根據[{src_label}1]...」
- 引用編號僅限 [{src_label}1] 到 [{src_label}{len(ordered)}]，不得使用其他編號
- 如果參考資料不足以完整回答，誠實說明還缺什麼資訊
- 回答務必簡潔：先給結論，最多 2-3 段、每段不超過 3 句，段落間空一行，不要展示推敲過程
- 回答時區分【已知事實】（附來源編號）與【推論】，不確定的事明說不確定
- 不得輸出信心百分比；所有數字必須出自參考資料或即時市場數據，不得自行估算
- 即使資料有限，也要給出可執行的觀察建議（觸發條件、關鍵事件、追蹤指標），不得整段棄權
{t(lang, "answer_lang_rule")}

輸出格式（嚴格遵守）：
1. 先簡潔回答問題
2. 然後固定追加以下一節：

{trend_block}

參考資料：
{context}
{market_block}{dual_block}{history_block}
使用者問題：{state['question']}
"""
    resp = _llms(_model_of(state))["llm"].invoke(prompt)
    # 免責聲明是固定常數，由程式追加而非要模型複誦：實測 40 筆真實回答只有 11 筆
    # 命中，且寬鬆比對（只找「非投資建議」等關鍵詞）僅多撈到 1 筆——不是模型改寫，
    # 是整段「固定追加」區塊沒生出來時跟著一起掉。文案解不了格式契約（同一個坑
    # 09-09、09-18 已踩過兩次），故從 prompt 移除、改在這裡補。
    answer = append_disclaimer(resp.content or "", lang)
    # 已知端到端瓶頸在本地模型生成，prompt/回應長度是判斷「慢在輸入還是輸出」的依據；
    # 只記長度不記內容，避免把提問寫進 log（保留策略未定前先不落地個資）
    qid = _qid(state["question"])
    usage = _ollama_usage(resp)
    log_duration(log, "generate", started, node="generate", model=_model_of(state),
                 qid=qid, prompt_chars=len(prompt),
                 answer_chars=len(answer), retrieved=len(state.get("retrieved") or []),
                 **usage)
    _warn_if_truncated("generate", qid, usage)
    # 來源編號 → 該來源的市場，對齊 ordered 的順序（索引 n-1 即 [來源n]）
    doc_market = {d["source"]: d.get("market") for d in state["retrieved"]}
    violations = check_answer_format(
        answer, fields, len(ordered), lang,
        source_markets=[doc_market.get(s) for s in ordered], market=state.get("market"))
    if violations:
        log.warning("決策卡格式違規", extra={"fields": {
            "node": "generate", "qid": _qid(state["question"]),
            "violations": violations, "allowed_fields": fields}})
    return {**state, "answer": answer, "allowed_fields": fields}


def no_result(state: GraphState) -> GraphState:
    lang = state.get("lang", "zh")
    company = _primary(state)
    if state.get("fetched"):
        answer = t(lang, "no_result_fetched", company=company)
        results = state.get("fetch_results") or []
        if results:
            answer += "\n\n" + "\n".join(f"- {r}" for r in results)
    else:
        answer = t(lang, "no_result_plain")
    if company:
        snapshot = get_market_snapshot(company)
        if snapshot:
            answer += "\n\n" + t(lang, "no_result_market", snapshot=snapshot)
    return {**state, "answer": answer}


def off_topic(state: GraphState) -> GraphState:
    """問題不在財經範圍：直接請使用者改問，本輪不檢索也不補抓。"""
    return {**state, "answer": t(state.get("lang", "zh"), "off_topic"), "retrieved": []}


def ask_market(state: GraphState) -> GraphState:
    """雙掛牌但沒指明市場：直接回問使用者要看哪一邊，本輪不檢索也不抓資料。

    刻意不猜一邊先答——台股與美股的幣別、期間、每股基準都不同，猜錯不會報錯，
    只會給出看似合理的錯誤數字，比多問一句的代價高得多。
    """
    company = _primary(state)
    tw = company if is_tw_ticker(company) else state["peer_company"]
    us = state["peer_company"] if is_tw_ticker(company) else company
    answer = t(state.get("lang", "zh"), "ask_market",
               name=DUAL_LISTED_NAMES.get(tw, tw), tw=tw, us=us)
    return {**state, "answer": answer, "retrieved": []}


async def build_graph():
    """建 graph。async 是因為要先跟 MCP server 拿 tool 清單（連不上會 raise，由呼叫端處理）。"""
    tools = await _mcp_client.get_tools()

    graph = StateGraph(GraphState)
    # node_span 包在註冊這一層而非直接裝飾函式：assemble 另外被 route_after_tools 內部
    # 呼叫一次（只為了看 retrieved），裝飾函式會讓每次路由判斷都多送一個假節點 span。
    # 包在這裡則「是圖上的節點」才產生 span，測試也繼續拿到未包裝的原函式。
    graph.add_node("rewrite_question", node_span(rewrite_question))
    graph.add_node("extract_filters", node_span(extract_filters))
    graph.add_node("resolve_market", node_span(resolve_market))
    graph.add_node("ask_market", node_span(ask_market))
    graph.add_node("off_topic", node_span(off_topic))
    graph.add_node("agent", node_span(agent))
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("assemble", node_span(assemble))
    graph.add_node("generate", node_span(generate))
    graph.add_node("no_result", node_span(no_result))

    graph.set_entry_point("rewrite_question")
    graph.add_edge("rewrite_question", "extract_filters")
    graph.add_edge("extract_filters", "resolve_market")
    # 雙掛牌又沒指明市場就先反問，本輪不檢索——猜錯市場給的是看似合理的錯誤數字
    graph.add_conditional_edges(
        "resolve_market", route_after_resolve_market,
        {"ask_market": "ask_market", "off_topic": "off_topic", "agent": "agent"},
    )
    graph.add_conditional_edges(
        "agent", agent_route, {"tools": "tools", "assemble": "assemble"},
    )
    # 資料明顯夠用就直接收工，否則回 agent 決定要不要補抓；輪數上限保證會收斂
    graph.add_conditional_edges(
        "tools", route_after_tools, {"agent": "agent", "assemble": "assemble"},
    )
    graph.add_conditional_edges(
        "assemble", route_after_assemble,
        {"generate": "generate", "no_result": "no_result"},
    )
    graph.add_edge("generate", END)
    graph.add_edge("no_result", END)
    graph.add_edge("ask_market", END)
    graph.add_edge("off_topic", END)

    return graph.compile()
