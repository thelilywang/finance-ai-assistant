"""用目前的程式碼無頭跑真實 graph，把問答、節點時間軸、圖表錄成 docs/demo/data.json。

流程照抄 src/app.py 的 on_message / _stream_answer / _send_with_sources，只是沒有 chainlit UI。
需在 docker compose 內跑（要連 MCP server、Postgres、host 的 Ollama）：

    docker compose run --rm -v $PWD/scripts:/app/scripts -v $PWD/docs:/app/docs \
        app python -m scripts.record_demo            # 全錄
    ... python -m scripts.record_demo tsmc-adr       # 只重錄指定 id，合併進既有 data.json
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config, tracing  # noqa: E402
from src.logging_setup import setup_logging  # noqa: E402

log = logging.getLogger("record_demo")
OUT = ROOT / "docs" / "demo" / "data.json"

QUESTIONS = [
    ("nvda", "NVDA 最新一季財報重點是什麼？", "美股財報"),
    ("tsmc-adr", "台積電最新一季 EPS 如何？", "雙掛牌 ADR"),
    ("asml", "ASML 近期新聞重點？", "新聞"),
    ("compare", "NVDA 與 GOOGL 近期趨勢比較，投資操作建議？", "多標的比較"),
]


def _detail(node: str, upd: dict) -> str | None:
    """每個節點挑一句人看得懂的摘要；拿不到就回 None，不為此追逐 state 細節。"""
    if node == "extract_filters":
        cos = upd.get("companies") or []
        return "標的：" + "、".join(cos) if cos else None
    if node == "agent":
        calls = getattr(((upd.get("messages") or [None])[-1]), "tool_calls", None) or []
        names = []
        for c in calls:
            arg = next((v for v in (c.get("args") or {}).values() if isinstance(v, str)), "")
            names.append(f"{c['name']}({arg})" if arg else c["name"])
        return "呼叫 " + "、".join(names) if names else "不需補抓"
    if node == "tools":
        return f"{len(upd.get('messages') or [])} 個工具回傳"
    if node == "assemble":
        return f"取得 {len(upd.get('retrieved') or [])} 段資料"
    if node == "generate":
        return f"回答 {len(upd.get('answer') or '')} 字"
    return None


async def _run(graph, state: dict, session_id: str, offset: float) -> tuple[dict, str, list[dict]]:
    """對應 app.py 的 _stream_answer：回傳 (final_state, 串流 token 組成的內容, 時間軸)。"""
    final_state, content, timeline = None, "", []
    t0 = last = time.monotonic()
    async for mode, payload in graph.astream(
        state, stream_mode=["messages", "updates", "values"],
        config=tracing.callbacks(session_id=session_id, user_id="demo",
                                 model=state.get("model"), lang=state.get("lang")),
    ):
        if mode == "messages":
            chunk, metadata = payload
            if metadata.get("langgraph_node") == "generate" and chunk.content:
                content += chunk.content
        elif mode == "updates":
            node = next(iter(payload))
            now = time.monotonic()
            timeline.append({
                "node": node, "start_s": round(offset + last - t0, 1),
                "duration_ms": int((now - last) * 1000), "detail": _detail(node, payload[node] or {}),
            })
            last = now
        else:
            final_state = payload
    return final_state, content, timeline


def _charts(companies: list[str]) -> list[dict]:
    from src.charts import eps_chart, price_chart

    res = []
    for c in companies:
        for kind, fn in (("股價", price_chart), ("EPS", eps_chart)):
            try:
                fig = fn(c)
            except Exception as e:  # noqa: BLE001
                log.warning("圖表生成失敗 %s %s: %s", c, kind, e)
                continue
            if fig is not None:
                res.append({"name": f"{c} {kind}", "figure": json.loads(fig.to_json())})
    return res


async def record(graph, qid: str, question: str, tag: str) -> dict:
    # app.py 的 helper 直接 import（chainlit 在映像內可用；setup_logging 已先呼叫，app.py 內那次是 no-op）
    from src.app import _clean_url, _format_source, _link_citations, _source_meta
    from src.graph import _side_by_side, append_disclaimer, unique_sources
    from src.i18n import detect_question_lang, t

    lang = detect_question_lang(question) or "zh"
    state = {
        "question": question, "history": [], "companies": [], "doc_type": None,
        "news_since_days": None, "retrieved": [], "answer": "", "fetched": False,
        "fetch_results": [], "messages": [], "lang": lang, "model": config.LLM_MODEL,
    }
    sid = f"demo-{uuid.uuid4().hex[:8]}"
    wall0 = time.monotonic()
    final, content, timeline = await _run(graph, state, sid, 0.0)

    picker = None
    if final and final.get("ask_market"):
        # 與 app.py 相同：按 both 後帶著市場重跑，沿用上一輪抽取結果
        picker = "both"
        log.info("%s 雙掛牌反問，模擬選擇 both", qid)
        timeline.append({"node": "picker", "start_s": round(time.monotonic() - wall0, 1),
                         "duration_ms": 0, "detail": "使用者選擇：台股與 ADR 都要"})
        final, content, tl2 = await _run(
            graph,
            {**state, "market": picker, "companies": final["companies"], "ask_market": False,
             "messages": [], "market_confirmed": True, "doc_type": final.get("doc_type"),
             "news_since_days": final.get("news_since_days"),
             "answer_shape": final.get("answer_shape", "full"), "in_scope": final.get("in_scope", True)},
            sid, time.monotonic() - wall0)
        timeline += tl2
    total = round(time.monotonic() - wall0, 1)

    # 以下對應 _send_with_sources：免責聲明、引用連結、來源清單
    answer = (final or {}).get("answer", "")
    body = append_disclaimer(content, lang) if content else answer
    if final and final["retrieved"]:
        unique = unique_sources(final["retrieved"])
        body = _link_citations(body, t(lang, "citation_label"), lang, [_clean_url(s) for s in unique])
        titles, dates = _source_meta(final["retrieved"])
        src_list = "\n".join(f"{i}. {_format_source(s, titles.get(s), dates.get(s))}" for i, s in enumerate(unique, 1))
        body += f"\n\n---\n**{t(lang, 'sources_label')}:**\n{src_list}"
    charts = _charts(_side_by_side(final)) if final and final["retrieved"] else []
    log.info("%s 完成：%.1fs timeline=%d charts=%d", qid, total, len(timeline), len(charts))
    return {"id": qid, "question": question, "tag": tag, "recorded_at": dt.datetime.now().isoformat(timespec="seconds"),
            "total_secs": total, "picker": picker, "timeline": timeline, "answer_md": body, "charts": charts}


async def main(ids: list[str]) -> None:
    from src.graph import build_graph

    todo = [q for q in QUESTIONS if not ids or q[0] in ids]
    if ids and len(todo) != len(ids):
        raise SystemExit(f"未知 id：{set(ids) - {q[0] for q in QUESTIONS}}")
    old = {i["id"]: i for i in json.loads(OUT.read_text("utf-8"))["items"]} if OUT.exists() else {}
    graph = await build_graph()
    try:
        for qid, question, tag in todo:
            old[qid] = await record(graph, qid, question, tag)
            # 每題錄完就寫檔：一題跑 3–10 分鐘，中途掛掉不必重來
            now = dt.date.today().isoformat()
            items = [old[q[0]] for q in QUESTIONS if q[0] in old]
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps({"generated_at": now, "charts_generated_at": now, "items": items},
                                      ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    finally:
        tracing.flush()


if __name__ == "__main__":
    setup_logging("demo")
    asyncio.run(main(sys.argv[1:]))
