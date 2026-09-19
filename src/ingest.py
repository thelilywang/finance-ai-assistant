"""資料匯入：把財報 PDF 或新聞文字檔切 chunk、embedding 後存進 pgvector。

用法：
    python -m src.ingest --file data/2330_2026Q2.pdf --company 2330 \
        --doc-type financial_report --date 2026-07-01
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import time

from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from . import config
from .vectorstore import delete_by_source, insert_chunks

log = logging.getLogger("ingest")


def load_text(path: str) -> str:
    if path.lower().endswith(".pdf"):
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# 財報全文通常數萬字；低於此值可能是抽到摘要頁或選錯檔案，值得人工確認（僅警示、不擋入庫）
_MIN_FINANCIAL_REPORT_CHARS = 10000


def chunk_text(text: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", " ", ""],
    )
    return splitter.split_text(text)


def _embed_in_batches(embeddings, chunks: list[str], source: str) -> list[list[float]]:
    """分批呼叫 embed_documents，逐批重試一次。

    整份一次送在長 filing 上會失敗（見 MAINTENANCE_LOG「大型 filing 的 embedding
    整批失敗」），且失敗率隨批次大小升高、沒有可查表的門檻，故切小再送。
    重試只做一次：實測失敗是資源／超時型，同一批重送常會過，但連兩次不過就
    不是暫時性問題，繼續重試只是把等待時間拉長。逐批記錄耗時與重試，供回測。
    """
    batch_size = config.EMBED_BATCH_SIZE or len(chunks)
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        started = time.monotonic()
        for attempt in (1, 2):
            try:
                vectors.extend(embeddings.embed_documents(batch))
                break
            except Exception as e:  # noqa: BLE001  ollama 的錯誤型別不在 requests 體系內
                if attempt == 2:
                    raise
                log.warning("embedding 批次失敗，重試一次", extra={"fields": {
                    "source": source, "reason": "embed_batch_failed",
                    "batch_start": start, "batch_size": len(batch), "error": str(e)}})
        log.info("embedding 批次完成", extra={"fields": {
            "source": source, "batch_start": start, "batch_size": len(batch),
            "elapsed_sec": round(time.monotonic() - started, 1)}})
    return vectors


def ingest_text(
    text: str, source: str, company: str | None, doc_type: str, published_at: str | None,
    title: str | None = None,
) -> int:
    """切 chunk → embedding → 寫入 pgvector，回傳寫入的 chunk 數。

    寫入前先 delete_by_source(source) 去重，重跑同一來源不會累積重複資料。
    """
    if not text or not text.strip():
        log.warning("內容為空（可能 PDF 抽不出文字），跳過", extra={"fields": {
            "source": source, "company": company, "reason": "no_content"}})
        return 0

    if doc_type == "financial_report" and len(text.strip()) < _MIN_FINANCIAL_REPORT_CHARS:
        log.warning("財報字數偏低，可能選錯檔案或內容不完整，建議人工確認", extra={"fields": {
            "source": source, "company": company, "reason": "short_report",
            "chars": len(text.strip()), "min_chars": _MIN_FINANCIAL_REPORT_CHARS}})

    delete_by_source(source)

    embeddings = OllamaEmbeddings(model=config.EMBEDDING_MODEL, base_url=config.OLLAMA_BASE_URL)
    chunks = chunk_text(text)
    log.info("開始 embedding", extra={"fields": {
        "source": source, "company": company, "chunks": len(chunks)}})

    vectors = _embed_in_batches(embeddings, chunks, source)

    rows = [
        {
            "source": source,
            "title": title,
            "doc_type": doc_type,
            "company": company,
            "published_at": dt.date.fromisoformat(published_at) if published_at else None,
            "chunk_index": i,
            "content": chunk,
            "embedding": vec,
        }
        for i, (chunk, vec) in enumerate(zip(chunks, vectors))
    ]

    insert_chunks(rows)
    log.info("已寫入 pgvector", extra={"fields": {
        "source": source, "company": company, "rows": len(rows)}})
    return len(rows)


def ingest_file(path: str, company: str, doc_type: str, published_at: str) -> None:
    ingest_text(load_text(path), source=path, company=company,
                doc_type=doc_type, published_at=published_at)


def main() -> None:
    parser = argparse.ArgumentParser(description="匯入財報/新聞文件到 pgvector")
    parser.add_argument("--file", required=True, help="PDF 或 txt 檔路徑")
    parser.add_argument("--company", default=None, help="公司代號，例如 2330")
    parser.add_argument(
        "--doc-type", default="financial_report", choices=["financial_report", "news"]
    )
    parser.add_argument("--date", default=None, help="發布日期 YYYY-MM-DD")
    args = parser.parse_args()

    ingest_file(args.file, args.company, args.doc_type, args.date)


if __name__ == "__main__":
    main()
