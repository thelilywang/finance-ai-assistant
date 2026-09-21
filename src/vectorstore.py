"""pgvector 存取層：負責寫入 chunk 與相似度檢索。

直接用 psycopg + pgvector，不透過 langchain 的 vectorstore 包裝，
方便之後客製化 filter（例如指定公司代號、日期區間）。
"""
from __future__ import annotations

import datetime as dt

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from . import config


def _configure(conn: psycopg.Connection) -> None:
    register_vector(conn)


# open=False：延遲到第一次真的要用連線才連 DB，避免 import 這個模組就連線
# timeout=2：DB 連不上時 2 秒內放棄（原本 psycopg.connect() 是毫秒級失敗，
# ConnectionPool 預設 timeout=30 秒會讓「DB 沒開」的降級路徑變得很慢；
# 正常連線本該在毫秒等級完成，2 秒內連不上代表 DB 真的掛了，拖久也救不回來）
pool = ConnectionPool(
    config.DATABASE_URL,
    # max_size=6：並行檢索最多同時開 4 條（主檢索、同公司新聞、市場新聞、最新財報），
    # 留餘裕給同時進來的另一題；不足時 retrieve_context 記的 pool_waiting 會現形
    min_size=1, max_size=6,
    kwargs={"autocommit": True},
    configure=_configure,
    open=False,
    timeout=2,
)


def get_connection():
    """回傳池化連線的 context manager；用法與原本 `with get_connection() as conn:` 相同。"""
    pool.open()  # 已開過是 no-op
    return pool.connection()


def delete_by_source(source: str) -> None:
    """重匯同一份文件前先清掉舊 chunk，讓 ingest 可重跑（idempotent）。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM doc_chunks WHERE source = %s", (source,))


def source_exists(source: str) -> bool:
    """該來源是否已入庫（讓重複掃描跳過 embedding）。"""
    with get_connection() as conn:
        cur = conn.execute("SELECT 1 FROM doc_chunks WHERE source = %s LIMIT 1", (source,))
        return cur.fetchone() is not None


def delete_news_older_than(days: int) -> int:
    """刪除超過 days 天的新聞 chunk，回傳刪除筆數。

    只刪 doc_type='news'；財報一律保留。published_at 為 NULL 的不刪。
    """
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM doc_chunks WHERE doc_type = 'news'"
            " AND published_at < CURRENT_DATE - %s",
            (days,),
        )
        return cur.rowcount


def delete_threads_older_than(days: int) -> int:
    """刪除超過 days 天的對話 thread，回傳刪除筆數。

    steps/elements/feedbacks 都對 threads 設了 ON DELETE CASCADE，刪 thread 即連帶清掉。
    "createdAt" 是 TEXT（ISO 字串，Chainlit 寫入時用 `datetime.now().isoformat() + "Z"`，
    即本地時間、非 UTC），故在 Python 端用同樣格式算好 cutoff 字串再比大小——
    ISO-8601 字典序與時間序一致，能吃到索引，不能對整欄 cast 成 timestamp（索引會失效）。
    """
    cutoff = (dt.datetime.now() - dt.timedelta(days=days)).isoformat() + "Z"
    with get_connection() as conn:
        cur = conn.execute('DELETE FROM threads WHERE "createdAt" < %s', (cutoff,))
        return cur.rowcount


def insert_chunks(rows: list[dict]) -> None:
    """rows 每筆需含: source, title, doc_type, company, published_at, chunk_index, content, embedding

    切塊出處三欄（chunk_unit／chunk_size／embed_model）由本函式統一補上當下的設定值，
    呼叫端不必傳——出處記的是「這批塊實際上是怎麼切出來的」，那就是寫入當下的 config，
    交給呼叫端傳只會多一個忘記傳就靜默留白的地方。
    """
    provenance = {
        "chunk_unit": config.CHUNK_UNIT,
        "chunk_size": config.CHUNK_SIZE,
        "embed_model": config.EMBEDDING_MODEL,
    }
    rows = [{**provenance, **row} for row in rows]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO doc_chunks
                    (source, title, doc_type, company, published_at, chunk_index, content, embedding,
                     chunk_unit, chunk_size, embed_model)
                VALUES
                    (%(source)s, %(title)s, %(doc_type)s, %(company)s, %(published_at)s,
                     %(chunk_index)s, %(content)s, %(embedding)s,
                     %(chunk_unit)s, %(chunk_size)s, %(embed_model)s)
                """,
                rows,
            )


def similarity_search(
    query_embedding: list[float],
    top_k: int = config.TOP_K,
    company: str | None = None,
    doc_type: str | None = None,
    news_since_days: int | None = None,
    exclude_company: str | None = None,
    order_by_recency: bool = False,
    latest_source_only: bool = False,
) -> list[dict]:
    """回傳最相似的 chunk，附上 source 供引用。

    news_since_days 有值時只限縮新聞的日期（財報不受影響）；
    published_at 為 NULL 的新聞在此條件下會被排除，可接受。

    exclude_company 排除指定公司（用 IS DISTINCT FROM，company 為 NULL 的列也會留下，
    因為市場新聞掃描認不出標題公司時就填 NULL，那些正是要補的市場脈絡）。
    order_by_recency=True 改以發布日期新到舊排序，供「補市場脈絡」這類要新不要準的用途；
    published_at 為 NULL 的排最後，避免無日期的舊文佔住補充名額。

    latest_source_only=True 只在「該 company 最新 published_at 的那些來源」裡做相似度排序。
    用途是財報檢索的期間維度：結構化來源把整季壓成 2 塊密集數字、PDF 來源散成上百塊
    自然語言，問「最新財報」時舊 PDF 靠塊數多穩定勝出（2330 實測 Q2 那兩塊排在第 242
    名，TOP_K=5 永遠撈不到）。限定在最新那批之內排序即繞過這個顆粒度偏差。
    需與 company 併用；published_at 為 NULL 的來源不參與（無期間可比）。
    """
    filters = []
    params: dict = {"embedding": query_embedding, "top_k": top_k}

    if company:
        filters.append("company = %(company)s")
        params["company"] = company
    if exclude_company:
        # != 不會匹配 NULL，全域新聞（company IS NULL）會被吃掉，故用 IS DISTINCT FROM
        filters.append("company IS DISTINCT FROM %(exclude_company)s")
        params["exclude_company"] = exclude_company
    if doc_type:
        filters.append("doc_type = %(doc_type)s")
        params["doc_type"] = doc_type
    if news_since_days is not None:
        filters.append(
            "(doc_type != 'news' OR published_at >= CURRENT_DATE - %(news_since_days)s)"
        )
        params["news_since_days"] = news_since_days
    if latest_source_only:
        # 同一天可能有多個來源（2454 實測同日兩份 PDF、台股結構化與 PDF 亦可能同日），
        # 故比對「最新日期」而非單一 source。子查詢吃既有的 (company, doc_type) 條件，
        # 不另外放寬，否則會把新聞日期拿來當財報的最新期。
        filters.append(
            "published_at = (SELECT max(published_at) FROM doc_chunks s"
            "  WHERE s.company = %(company)s"
            "    AND (%(doc_type)s IS NULL OR s.doc_type = %(doc_type)s))"
        )
        params.setdefault("doc_type", doc_type)

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    order_clause = (
        "ORDER BY published_at DESC NULLS LAST, embedding <=> %(embedding)s::vector"
        if order_by_recency
        else "ORDER BY embedding <=> %(embedding)s::vector"
    )

    sql = f"""
        SELECT id, source, title, doc_type, company, published_at, content,
               1 - (embedding <=> %(embedding)s::vector) AS similarity
        FROM doc_chunks
        {where_clause}
        {order_clause}
        LIMIT %(top_k)s
    """

    with get_connection() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
