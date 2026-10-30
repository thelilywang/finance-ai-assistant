"""檢索品質 golden set：Hit@5、Recall@5、MRR@5，回答「檢索結果對不對」。

eval_rag_retrieval.py 驗的是補資料規則有沒有生效，不看相關性；這支補上相關性。
標注不寫死 chunk id（重灌或補抓後 id 會變），而是「公司 + 類型 + 內容 regex」：
符合三者的塊視為答案所在的塊。regex 寫得越窄，相關集合越接近人工標注。

公司與類型直接給正確值，等於假設 extract_filters 抽對了——量的是向量排序本身，
抽取正確率另見 eval_extract_filters.py。每題量三種結果：
  hnsw     similarity_search 前 5（正式環境走 HNSW 索引）
  exact    同條件關掉索引的精確排序，與 hnsw 的差距就是近似索引在過濾下漏掉的
  context  retrieve_context 整段回傳（含最新財報席位、同公司新聞），即送進 agent 的內容

指標：
  Hit@5     前 5 至少一塊相關的題數比例
  Recall@5  前 5 的相關塊數 ÷ min(相關塊總數, 5)
  MRR@5     第一塊相關塊名次的倒數平均（沒命中記 0）

DB 未對 host 開 port，需在 app container 內執行：
    docker exec finance_ai_assistant_app python tests/eval_retrieval_golden.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg

from src import graph
from src.vectorstore import get_connection, similarity_search

GOLDEN = Path(__file__).parent / "eval_data" / "retrieval_golden.json"
K = 5
# EDGAR 全文偶有 inline XBRL 標籤整串攤平成一塊（「nvda:DataCenterMember2025-01-27…」），
# 字面上含關鍵詞、語意上是雜訊，統計它佔前 5 名的比例
XBRL_NOISE = re.compile(r"(us-gaap|[a-z]+:[A-Za-z]+Member)\d{4}-\d{2}-\d{2}")


def relevant_count(item: dict) -> int:
    with get_connection() as conn:
        return conn.execute(
            "SELECT count(*) FROM doc_chunks WHERE company = %s AND doc_type = %s AND content ~* %s",
            (item["company"], item["doc_type"], item["relevant"]),
        ).fetchone()[0]


def exact_search(vec: list[float], company: str, doc_type: str) -> list[dict]:
    """與 similarity_search 同條件，但關掉索引掃描，得到精確的前 K 名。"""
    with get_connection() as conn, conn.transaction():
        conn.execute("SET LOCAL enable_indexscan = off")
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                "SELECT id, content FROM doc_chunks WHERE company = %s AND doc_type = %s"
                " ORDER BY embedding <=> %s::vector LIMIT %s",
                (company, doc_type, vec, K),
            )
            return cur.fetchall()


def score(docs: list[dict], pattern: str, total: int) -> tuple[bool, float, float]:
    hits = [bool(re.search(pattern, d["content"], re.IGNORECASE)) for d in docs[:K]]
    first = next((i for i, h in enumerate(hits) if h), None)
    recall = sum(hits) / min(total, K) if total else 0.0
    return any(hits), recall, 1 / (first + 1) if first is not None else 0.0


def main() -> None:
    items = json.loads(GOLDEN.read_text())
    arms = {"hnsw": [], "exact": [], "context": []}
    noise = 0
    print(f"{'id':4} {'相關塊':>5}  hnsw(hit/R@5/rr)  exact(hit/R@5/rr)  context(hit)  問題")
    for item in items:
        total = relevant_count(item)
        vec, _ = graph._embed_query_cached(item["question"])
        hnsw = similarity_search(vec, top_k=K, company=item["company"], doc_type=item["doc_type"])
        exact = exact_search(vec, item["company"], item["doc_type"])
        context = graph.retrieve_context(item["question"], item["company"], item["doc_type"])
        s_h = score(hnsw, item["relevant"], total)
        s_e = score(exact, item["relevant"], total)
        # context 筆數不固定，只看有沒有任何一塊相關
        c_hit = any(re.search(item["relevant"], d["content"], re.IGNORECASE) for d in context)
        noise += sum(1 for d in hnsw if XBRL_NOISE.search(d["content"]))
        arms["hnsw"].append(s_h)
        arms["exact"].append(s_e)
        arms["context"].append((c_hit, 0.0, 0.0))
        fmt = lambda s: f"{'Y' if s[0] else '-'} {s[1]:.2f} {s[2]:.2f}"  # noqa: E731
        print(f"{item['id']:4} {total:>5}  {fmt(s_h):16}  {fmt(s_e):17}  {'Y' if c_hit else '-':12}  {item['question']}")

    n = len(items)
    print(f"\n共 {n} 題（公司與類型給定，量向量排序本身）")
    for name in ("hnsw", "exact"):
        rows = arms[name]
        print(f"  {name:6} Hit@5 {sum(r[0] for r in rows) / n:.0%}  Recall@5 {sum(r[1] for r in rows) / n:.2f}"
              f"  MRR@5 {sum(r[2] for r in rows) / n:.2f}")
    print(f"  hnsw 前 {K} 名中 XBRL 標籤雜訊塊 {noise}/{n * K}")
    print(f"  context 任一塊相關 {sum(r[0] for r in arms['context']) / n:.0%}")


if __name__ == "__main__":
    main()
