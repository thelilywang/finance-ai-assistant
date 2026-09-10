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
    min_size=1, max_size=5,
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
    """rows 每筆需含: source, title, doc_type, company, published_at, chunk_index, content, embedding"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO doc_chunks
                    (source, title, doc_type, company, published_at, chunk_index, content, embedding)
                VALUES
                    (%(source)s, %(title)s, %(doc_type)s, %(company)s, %(published_at)s,
                     %(chunk_index)s, %(content)s, %(embedding)s)
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
) -> list[dict]:
    """回傳最相似的 chunk，附上 source 供引用。

    news_since_days 有值時只限縮新聞的日期（財報不受影響）；
    published_at 為 NULL 的新聞在此條件下會被排除，可接受。

    exclude_company 排除指定公司（用 IS DISTINCT FROM，company 為 NULL 的列也會留下，
    因為市場新聞掃描認不出標題公司時就填 NULL，那些正是要補的市場脈絡）。
    order_by_recency=True 改以發布日期新到舊排序，供「補市場脈絡」這類要新不要準的用途；
    published_at 為 NULL 的排最後，避免無日期的舊文佔住補充名額。
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
