"""RAG 檢索規則評估：用標注問題集打 search_knowledge_base()，逐 category 檢查規則。

與 test_mcp_tools.py 的差別：那支 monkey-patch retrieve_context 用假資料測回傳格式，
這支不 patch，打真實資料庫測 retrieve_context 的四段補資料規則實際有沒有生效。

不同 category 的「正確」定義不同（放寬重查看的是非空、補新聞看的是筆數上限、
新鮮度看的是 header 文字），所以各自寫判準，不套單一 precision/recall。

DB 跑在 container 內且未對 host 開 port，需在 app container 內執行：
    docker exec finance_ai_assistant_app python tests/eval_rag_retrieval.py
"""
import asyncio
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mcp_server import search_knowledge_base
from src.vectorstore import get_connection

ANNOTATIONS = Path(__file__).parent / "eval_data" / "rag_annotations.json"
TODAY = dt.date.today()


def published_dates(company: str, doc_type: str) -> list[str]:
    """該公司該類型在庫內的所有發布日期（用來區分「檢索沒撈到」與「資料本來就沒有」）。"""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT DISTINCT published_at FROM doc_chunks"
            " WHERE company = %s AND doc_type = %s AND published_at IS NOT NULL"
            " ORDER BY published_at",
            (company, doc_type),
        )
        return [str(r[0]) for r in cur.fetchall()]


def _company_missing(doc_type: str) -> str | None:
    """找一家「庫內有資料、但完全沒有該 doc_type」的公司；沒有就回 None。

    放寬重查的題目不能寫死標的：補抓會持續補進財報，寫死的那家遲早不再符合情境。
    """
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT company FROM doc_chunks WHERE company IS NOT NULL"
            " GROUP BY company HAVING count(*) FILTER (WHERE doc_type = %s) = 0"
            " ORDER BY count(*) DESC LIMIT 1",
            (doc_type,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def header_age(summary: str) -> int | None:
    """從 summary 開頭抓「最新的[ 公司 的]「新聞」距今 N 天」的 N；沒有就回 None。

    有帶 company 時 header 會標明公司（「最新的 AAPL 的「新聞」」），所以公司名那段要選配。
    """
    m = re.search(r"最新的(?: \S+ 的)?「新聞」距今 (\d+) 天", summary)
    return int(m.group(1)) if m else None


def check_normal(item, chunks, summary):
    """正常案例／市場消歧：至少 1 筆，且該公司該類型確實命中。"""
    if not chunks:
        return False, "chunks 為空"
    want_co, want_dt = item["company"], item["doc_type"]
    hits = [c for c in chunks if c.get("company") == want_co and c.get("doc_type") == want_dt]
    if not hits:
        got = sorted({f"{c.get('company')}/{c.get('doc_type')}" for c in chunks})
        return False, f"無 {want_co}/{want_dt} 命中，實得 {got}"
    # 排序靠前：第一筆就該是目標公司該類型
    first = chunks[0]
    lead = first.get("company") == want_co and first.get("doc_type") == want_dt
    return True, f"{len(hits)} 筆命中 {want_co}/{want_dt}，首筆{'符合' if lead else '非目標(補充資料排前)'}"


def check_relax(item, chunks, summary):
    """放寬重查：該公司確實無該 doc_type 資料，但仍要回得出東西。"""
    co, dt_ = item["company"], item["doc_type"]
    in_db = published_dates(co, dt_)
    if in_db:
        # 情境需要「有該公司的資料、但沒有該 doc_type」——沒有任何資料的公司
        # 測不到放寬（濾掉 doc_type 後仍是空），測到的只是「查無此公司」。
        # 題目寫死標的會過期：補抓一旦補進該公司的財報，情境就永久消失
        # （2026-09-21 實測，庫內 21 家公司已全部都有財報）。故改為現找一家符合的。
        alt = _company_missing(dt_)
        if alt is None:
            return False, (f"前提不成立：{co} 已有 {len(in_db)} 個 {dt_} 日期，"
                           f"且庫內找不到任何「有資料但缺 {dt_}」的公司，此情境目前無法測")
        # 換了標的就得重查：原本的 chunks 是對舊標的檢索出來的，拿來判定沒有意義
        substituted = f"（{co} 已有 {dt_}，改測 {alt}）"
        co = alt
        raw = asyncio.run(search_knowledge_base(item["question"], co, dt_))
        chunks = json.loads(raw)["chunks"]
    else:
        substituted = ""
    if not chunks:
        return False, f"{co} 無 {dt_} 資料且 chunks 為空，放寬規則未觸發{substituted}"
    kinds = sorted({c.get("doc_type") for c in chunks})
    return True, f"{co} 無 {dt_} 資料，放寬後回 {len(chunks)} 筆，類型 {kinds}{substituted}"


def check_report_plus_news(item, chunks, summary):
    """財報補新聞：同公司 news 補充 1..3 筆。"""
    co = item["company"]
    reports = [c for c in chunks if c.get("doc_type") == "financial_report" and c.get("company") == co]
    news = [c for c in chunks if c.get("doc_type") == "news" and c.get("company") == co]
    if not reports:
        return False, f"未回傳 {co} 的 financial_report"
    if not news:
        return False, f"回了 {len(reports)} 筆財報但無 {co} 新聞補充"
    if len(news) > 3:
        return False, f"新聞補充 {len(news)} 筆，超過上限 3"
    return True, f"財報 {len(reports)} 筆 + 同公司新聞補充 {len(news)} 筆"


def check_global_news(item, chunks, summary):
    """全域補 2 條：company 為 null 或不同於查詢公司的新聞，數量 <= 2。"""
    co = item["company"]
    extra = [c for c in chunks
             if c.get("doc_type") == "news" and c.get("company") != co]
    if not extra:
        return False, "無 company 相異／為 null 的補充新聞"
    if len(extra) > 2:
        return False, f"補充新聞 {len(extra)} 筆，超過上限 2"
    cos = [c.get("company") for c in extra]
    return True, f"補充全域新聞 {len(extra)} 筆，company={cos}"


def check_freshness(item, chunks, summary):
    """新鮮度 header：header 報的天數要等於該公司在庫內最新新聞的實際天數。

    標準答案**從資料庫現算**，不寫在 expect 裡。寫死天數（原本是「距今 57 天」這種）
    會隨補抓寫入新新聞而失效——2026-09-21 實測 E1 期望 57 天、實際已是 2 天，
    三題全 FAIL 但程式沒有任何問題，純粹是標注過期。這種題目會定期假警報，
    久了就沒人信它，等於白養一支測試。
    """
    co = item["company"]
    in_db = published_dates(co, "news")
    if not in_db:
        return False, f"前提不成立：{co} 在庫內沒有任何帶日期的新聞，測不到新鮮度"
    # 標準答案是「**實際回傳的** chunk 裡最新那則的天數」，不是庫內最新那則。
    # 兩者常常不同，而且差異是合理的：庫內最新的那筆未必是檢索選中的——例如
    # 2026-09-21 實測，ASML 庫內最新是 2 天前的「Eisman Says Buy Micron And SK
    # Hynix」（掛在 ASML 名下的大盤新聞），而檢索挑的是 3 天前真正講 ASML 的那則。
    # header 要忠實反映的是「這次給 LLM 的素材有多新」，拿庫內最新值去比會製造假警報。
    own_dates = [c["published_at"] for c in chunks
                 if c.get("company") == co and c.get("doc_type") == "news"
                 and c.get("published_at")]
    if not own_dates:
        return False, f"回傳的 chunks 裡沒有 {co} 的新聞，無從驗新鮮度"
    newest = max(dt.date.fromisoformat(str(d)[:10]) for d in own_dates)
    want = (TODAY - newest).days
    got = header_age(summary)
    if got is None:
        return False, f"summary 開頭無新聞天數（開頭：{summary[:40]!r}）"
    if got != want:
        co = item["company"]
        own = [c for c in chunks if c.get("company") == co and c.get("doc_type") == "news"]
        own_ages = sorted({(TODAY - dt.date.fromisoformat(str(c["published_at"])[:10])).days
                           for c in own if c.get("published_at")})
        others = [c for c in chunks
                  if c.get("doc_type") == "news" and c.get("company") != co and c.get("published_at")]
        other_ages = sorted({(TODAY - dt.date.fromisoformat(str(c["published_at"])[:10])).days
                             for c in others})
        return False, (f"header 報 {got} 天，回傳的 {co} 新聞最新為 {want} 天；"
                       f"{co} 自身新聞距今 {own_ages}，非本公司新聞距今 {other_ages}")
    return True, f"header 報距今 {got} 天，與回傳素材最新一則相符"


def check_single_period(item, chunks, summary):
    """單期財報限制：確認庫內該公司財報只有單一日期（是資料限制，不是檢索問題）。"""
    co = item["company"]
    in_db = published_dates(co, "financial_report")
    got = sorted({str(c["published_at"])[:10] for c in chunks
                  if c.get("doc_type") == "financial_report" and c.get("company") == co
                  and c.get("published_at")})
    if len(in_db) != 1:
        return False, f"庫內 {co} 財報有 {len(in_db)} 個日期 {in_db}，非單期，題目前提不成立"
    return True, f"庫內 {co} 財報僅單一日期 {in_db}，檢索回傳日期 {got}，資料不足屬資料限制"


CHECKERS = {
    "正常案例": check_normal,
    "市場消歧": check_normal,
    "doc_type濾空放寬重查": check_relax,
    "doc_type濾空放寬重查(第二樣本)": check_relax,
    "財報補新聞規則": check_report_plus_news,
    "財報補新聞規則(第二樣本)": check_report_plus_news,
    "全域市場新聞補2條": check_global_news,
    "新鮮度header正確性": check_freshness,
    "新鮮度header正確性(邊界值)": check_freshness,
    "新鮮度header正確性(正常範圍)": check_freshness,
    "單期財報限制(誠實標注)": check_single_period,
    "單期財報限制(第二樣本)": check_single_period,
}


def run_one(item):
    raw = asyncio.run(search_knowledge_base(
        item["question"], item["company"], item["doc_type"]))
    out = json.loads(raw)
    assert set(out) == {"summary_for_llm", "chunks"}, f"{item['id']} 回傳結構異常"
    chunks, summary = out["chunks"], out["summary_for_llm"]
    checker = CHECKERS[item["category"]]
    ok, detail = checker(item, chunks, summary)
    return ok, detail, chunks, summary


def main():
    items = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))
    print(f"今天是 {TODAY}，共 {len(items)} 題\n" + "=" * 72)
    by_cat = defaultdict(lambda: [0, 0])
    failures = []
    for item in items:
        ok, detail, chunks, summary = run_one(item)
        by_cat[item["category"]][1] += 1
        by_cat[item["category"]][0] += int(ok)
        if not ok:
            failures.append((item, detail))
        breakdown = defaultdict(int)
        for c in chunks:
            breakdown[f"{c.get('company')}/{c.get('doc_type')}"] += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {item['id']}  {item['category']}")
        print(f"       Q: {item['question']}")
        print(f"       查詢: company={item['company']} doc_type={item['doc_type']}")
        print(f"       回傳 {len(chunks)} 筆: {dict(breakdown)}")
        print(f"       header: {summary.splitlines()[0][:70] if summary else '(空)'}")
        print(f"       判定: {detail}\n")

    print("=" * 72 + "\n依 category 通過率：")
    for cat, (p, n) in by_cat.items():
        print(f"  {p}/{n}  {'█' * p}{'░' * (n - p)}  {cat}")
    total_p = sum(p for p, _ in by_cat.values())
    print(f"\n總計 {total_p}/{len(items)}")
    if failures:
        print("\nFAIL 清單：")
        for item, detail in failures:
            print(f"  {item['id']} ({item['category']}): {detail}")


if __name__ == "__main__":
    main()
