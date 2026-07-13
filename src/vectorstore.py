"""pgvector 存取層：負責寫入 chunk 與相似度檢索。

直接用 psycopg + pgvector，不透過 langchain 的 vectorstore 包裝，
方便之後客製化 filter（例如指定公司代號、日期區間）。
"""
from __future__ import annotations

import psycopg
from pgvector.psycopg import register_vector

from . import config


def get_connection() -> psycopg.Connection:
    conn = psycopg.connect(config.DATABASE_URL, autocommit=True)
    register_vector(conn)
    return conn


def delete_by_source(source: str) -> None:
    """重匯同一份文件前先清掉舊 chunk，讓 ingest 可重跑（idempotent）。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM doc_chunks WHERE source = %s", (source,))


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


def insert_chunks(rows: list[dict]) -> None:
    """rows 每筆需含: source, doc_type, company, published_at, chunk_index, content, embedding"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO doc_chunks
                    (source, doc_type, company, published_at, chunk_index, content, embedding)
                VALUES
                    (%(source)s, %(doc_type)s, %(company)s, %(published_at)s,
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
) -> list[dict]:
    """回傳最相似的 chunk，附上 source 供引用。

    news_since_days 有值時只限縮新聞的日期（財報不受影響）；
    published_at 為 NULL 的新聞在此條件下會被排除，可接受。
    """
    filters = []
    params: dict = {"embedding": query_embedding, "top_k": top_k}

    if company:
        filters.append("company = %(company)s")
        params["company"] = company
    if doc_type:
        filters.append("doc_type = %(doc_type)s")
        params["doc_type"] = doc_type
    if news_since_days is not None:
        filters.append(
            "(doc_type != 'news' OR published_at >= CURRENT_DATE - %(news_since_days)s)"
        )
        params["news_since_days"] = news_since_days

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
        SELECT id, source, doc_type, company, published_at, content,
               1 - (embedding <=> %(embedding)s::vector) AS similarity
        FROM doc_chunks
        {where_clause}
        ORDER BY embedding <=> %(embedding)s::vector
        LIMIT %(top_k)s
    """

    with get_connection() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
