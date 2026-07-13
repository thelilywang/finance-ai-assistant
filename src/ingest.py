"""資料匯入：把財報 PDF 或新聞文字檔切 chunk、embedding 後存進 pgvector。

用法：
    python -m src.ingest --file data/2330_2026Q2.pdf --company 2330 \
        --doc-type financial_report --date 2026-07-01
"""
from __future__ import annotations

import argparse
import datetime as dt

from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from . import config
from .vectorstore import delete_by_source, insert_chunks


def load_text(path: str) -> str:
    if path.lower().endswith(".pdf"):
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def chunk_text(text: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", " ", ""],
    )
    return splitter.split_text(text)


def ingest_text(
    text: str, source: str, company: str | None, doc_type: str, published_at: str | None,
    title: str | None = None,
) -> int:
    """切 chunk → embedding → 寫入 pgvector，回傳寫入的 chunk 數。

    寫入前先 delete_by_source(source) 去重，重跑同一來源不會累積重複資料。
    """
    if not text or not text.strip():
        print(f"[ingest] 警告：{source} 內容為空（可能 PDF 抽不出文字），跳過。")
        return 0

    delete_by_source(source)

    embeddings = OllamaEmbeddings(model=config.EMBEDDING_MODEL, base_url=config.OLLAMA_BASE_URL)
    chunks = chunk_text(text)
    print(f"[ingest] {source} 切成 {len(chunks)} 個 chunk，開始 embedding...")

    vectors = embeddings.embed_documents(chunks)

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
    print(f"[ingest] 完成，已寫入 {len(rows)} 筆到 pgvector。")
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
