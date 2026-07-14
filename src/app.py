"""Chainlit 網頁聊天介面。

用法：
    chainlit run src/app.py -w    # 開 http://localhost:8000
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # chainlit run 以 src/ 為 sys.path[0]

import datetime as dt
from urllib.parse import urlsplit

import chainlit as cl
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from chainlit.input_widget import Select

from src import config
from src.graph import build_graph, route_after_retrieve, unique_sources
from src.i18n import STRINGS, detect_lang, detect_question_lang, t
from src.vectorstore import delete_news_older_than

graph = build_graph()

try:  # 啟動時清過期新聞，DB 未起不擋 app
    pruned = delete_news_older_than(config.NEWS_RETENTION_DAYS)
    if pruned:
        print(f"[app] 已清除 {pruned} 筆過期新聞 chunk")
except Exception as e:
    print(f"[app] 新聞清理略過：{e}")


@cl.data_layer
def get_data_layer():
    # 沿用同一個 Postgres（PGVECTOR_URL），供讚/倒讚回饋持久化用
    return SQLAlchemyDataLayer(conninfo=config.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"))


@cl.set_starters
async def starters(user=None, language=None):
    # language 由 Chainlit 帶入瀏覽器語言（如 "zh-TW"）；拿不到就明確用 zh
    lang = detect_lang(language) if language else "zh"
    return [cl.Starter(label=label, message=msg) for label, msg in STRINGS[lang]["starters"]]


def _clean_url(source: str) -> str | None:
    """http(s) URL 回傳去 query/fragment 的乾淨 URL；其他（EDGAR/本地檔）回 None。"""
    if source.startswith(("http://", "https://")):
        split = urlsplit(source)
        return f"{split.scheme}://{split.netloc}{split.path}"
    return None


# ponytail: 有 DB title 就用真標題，沒有（舊資料）才退回 URL slug 當 fallback
def _format_source(source: str, title: str | None = None) -> str:
    """把原始來源字串轉成可讀的 markdown（EDGAR/本地檔案/URL）。"""
    if source.startswith("EDGAR:"):
        parts = source.split(":")
        ticker = parts[1] if len(parts) > 1 else ""
        return f"SEC EDGAR filing ({ticker})" if ticker else "SEC EDGAR filing"

    clean_url = _clean_url(source)
    if clean_url:
        split = urlsplit(source)
        domain = split.netloc.removeprefix("www.")
        if title:
            title = (title[:60] + "…") if len(title) > 60 else title
        else:
            title = split.path.rstrip("/").rsplit("/", 1)[-1]
            title = title.replace("-", " ").replace("_", " ").strip()
            title = (title[:60] + "…") if len(title) > 60 else title
            if title:
                title = title[0].upper() + title[1:]
            else:
                title = domain
        return f"[{title} — {domain}]({clean_url})"

    # 本地路徑：只留檔名
    return source.rsplit("/", 1)[-1]


def _link_citations(body: str, label: str, lang: str, urls: list[str | None]) -> str:
    """把 [來源1]/[Source 1] 這類引用標記轉成 markdown 連結，容錯標籤與數字間的空格。
    urls 依編號順序（1-based）對應；為 None（無連結來源）保留為純文字，
    超出範圍（幻覺編號）則整段移除。
    """
    label = label.strip()
    sep = "" if lang == "zh" else " "
    for i, url in enumerate(urls, start=1):
        if not url:
            continue
        pattern = rf"\[{re.escape(label)}\s*{i}\]"
        replacement = f"[[{label}{sep}{i}]]({url})"  # 外層是 markdown 連結、內層方括號留在顯示文字，相鄰引用才分得開
        body = re.sub(pattern, replacement, body)

    def _drop_out_of_range(m: re.Match) -> str:
        return "" if int(m.group(1)) > len(urls) else m.group(0)

    body = re.sub(rf"\[{re.escape(label)}\s*(\d+)\]", _drop_out_of_range, body)
    return body


def _trim_for_history(answer: str) -> str:
    """存入 history 前去掉趨勢觀點段落並截斷長度，控制 rewrite/generate prompt 的 token 消耗。"""
    answer = answer.split("## 📈", 1)[0].rstrip()
    return answer[: config.HISTORY_ANSWER_MAX_CHARS]


def _chat_settings(label_lang: str, initial_value: str) -> cl.ChatSettings:
    return cl.ChatSettings([
        Select(
            id="language",
            label=t(label_lang, "settings_label"),
            items={"Auto": "auto", "繁體中文": "zh", "English": "en"},
            initial_value=initial_value,
        ),
    ])


@cl.on_chat_start
async def start():
    # ponytail: 對話歷史只存在單次 session 記憶體，重整即清空；要持久化再存 DB
    cl.user_session.set("history", [])
    browser = detect_lang(cl.user_session.get("languages"))
    cl.user_session.set("browser_lang", browser)
    cl.user_session.set("lang_setting", "auto")
    await _chat_settings(browser, "auto").send()


@cl.on_settings_update
async def on_settings_update(settings):
    setting = settings["language"]
    cl.user_session.set("lang_setting", setting)
    browser = cl.user_session.get("browser_lang", "zh")
    new_lang = setting if setting != "auto" else browser
    await _chat_settings(new_lang, setting).send()


class _StepTracker:
    """管理分析進度用的單一 cl.Step，同時間只有一個 step 開著。"""

    def __init__(self, ui_lang: str):
        self.ui_lang = ui_lang
        self.step: cl.Step | None = None

    async def start(self):
        self.step = cl.Step(name=t(self.ui_lang, "step_analyze"), type="tool")
        await self.step.send()

    async def advance(self, name: str):
        """關閉目前 step，開下一個。"""
        if self.step is not None:  # auto_fetch 後 step 已關閉，直接開新的
            await self.step.remove()
        self.step = cl.Step(name=name, type="tool")
        await self.step.send()

    async def close(self):
        if self.step is not None:
            await self.step.remove()
            self.step = None


async def _stream_answer(state: dict, msg: cl.Message, tracker: _StepTracker) -> dict:
    """跑 graph，邊串流 generate 的 token 邊推進 step 顯示，回傳 final state。"""
    final_state = None
    in_think = False  # 保險：reasoning=False 失效時過濾 <think>...</think>

    # 同時訂閱 messages（逐 token）、updates（節點完成通知）與 values（完整 state）
    async for mode, payload in graph.astream(state, stream_mode=["messages", "updates", "values"]):
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
                if tracker.step is not None:  # 第一個 generate token 到，關掉還開著的 step
                    await tracker.close()
                await msg.stream_token(token)
        elif mode == "updates":
            node = next(iter(payload))
            if node == "extract_filters":
                if tracker.step is not None:
                    await tracker.advance(t(tracker.ui_lang, "step_retrieve"))
            elif node == "retrieve":
                partial = payload[node]
                if route_after_retrieve(partial) == "auto_fetch":
                    await tracker.advance(t(tracker.ui_lang, "step_fetch"))
                else:
                    await tracker.advance(t(tracker.ui_lang, "step_generate"))
            elif node == "auto_fetch":
                # 關閉 fetch step；重新檢索會再走一次 retrieve update 開下一個 step
                await tracker.close()
        else:  # values：最後一筆就是 final state
            final_state = payload

    await tracker.close()  # 保險：no_result 路徑沒有 generate token，可能還開著
    return final_state


async def _send_with_sources(msg: cl.Message, final_state: dict, question: str, content_lang: str):
    """來源列附加到訊息 + 產生可下載分析報告（no_result 略過）。"""
    if not final_state["retrieved"]:
        return

    unique = unique_sources(final_state["retrieved"])
    label = t(content_lang, "citation_label")
    urls = [_clean_url(s) for s in unique]
    body = _link_citations(msg.content, label, content_lang, urls)
    msg.content = body

    titles = {}
    for doc in final_state["retrieved"]:
        if doc.get("title") and doc["source"] not in titles:
            titles[doc["source"]] = doc["title"]
    source_list = "\n".join(f"{i}. {_format_source(s, titles.get(s))}" for i, s in enumerate(unique, start=1))
    await msg.stream_token(f"\n\n---\n**{t(content_lang, 'sources_label')}:**\n{source_list}")

    now = dt.datetime.now()
    report = (
        f"# {question}\n\n{body}\n\n---\n"
        f"**{t(content_lang, 'sources_label')}:**\n{source_list}\n\n"
        f"{t(content_lang, 'report_generated_at')}: {now:%Y-%m-%d %H:%M:%S}\n"
    )
    msg.elements = [cl.File(
        name=f"analysis-{now:%Y%m%d-%H%M%S}.md",
        content=report.encode("utf-8"),
        mime="text/markdown",
        display="inline",
    )]


@cl.on_message
async def on_message(message: cl.Message):
    history = cl.user_session.get("history")
    setting = cl.user_session.get("lang_setting", "auto")
    browser = cl.user_session.get("browser_lang", "zh")
    # ui_lang：介面字串（step 名稱等）跟隨設定/瀏覽器語言，不受提問語言影響
    # content_lang：回答/來源/報告內容，auto 時跟隨提問語言（中文問→中文答），判斷不了（純代號）才退回瀏覽器語言
    ui_lang = setting if setting != "auto" else browser
    content_lang = setting if setting != "auto" else (detect_question_lang(message.content) or browser)
    state = {
        "question": message.content, "history": history,
        "company": None, "doc_type": None, "retrieved": [], "answer": "", "fetched": False,
        "lang": content_lang,
    }

    msg = cl.Message(content="")
    tracker = _StepTracker(ui_lang)
    await tracker.start()

    final_state = await _stream_answer(state, msg, tracker)

    answer = final_state["answer"] if final_state else ""
    if not msg.content:
        # no_result 路徑沒有 generate token，用 final state 的 answer 補上
        msg.content = answer

    if final_state:
        await _send_with_sources(msg, final_state, message.content, content_lang)

    await msg.send()

    history.append((message.content, _trim_for_history(answer)))
    cl.user_session.set("history", history[-5:])  # 只留最近 5 輪
