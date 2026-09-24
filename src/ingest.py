"""資料匯入：把財報 PDF 或新聞文字檔切 chunk、embedding 後存進 pgvector。

用法：
    python -m src.ingest --file data/2330_2026Q2.pdf --company 2330 \
        --doc-type financial_report --date 2026-07-01
"""
from __future__ import annotations

import argparse
import datetime as dt
import functools
import logging
import time

from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from . import config
from .logging_setup import log_duration
from .tickers import is_tw_ticker
from .vectorstore import delete_by_source, insert_chunks

log = logging.getLogger("ingest")


def load_text(path: str) -> str:
    if path.lower().endswith(".pdf"):
        started = time.monotonic()
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        # pypdf 解析是純 Python、CPU 密集，疑似佔住 GIL 拖慢同 process 其他補抓執行緒，
        # 先留耗時觀測點，修法待實測數據出來再決定
        log_duration(log, "PDF 解析完成", started, source=path,
                     pages=len(reader.pages), chars=len(text))
        return text
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# 財報全文通常數萬字；低於此值可能是抽到摘要頁或選錯檔案，值得人工確認（僅警示、不擋入庫）
_MIN_FINANCIAL_REPORT_CHARS = 10000


@functools.lru_cache(maxsize=None)
def _token_counter():
    """回傳 embedding 模型自己的 tokenizer 計數函式；不可用時回 None（退回字元計數）。

    ponytail: 用 lru_cache 當 lazy singleton，tokenizer 載入一次就夠，不另建管理類別。
    char 路徑完全不會呼叫到這裡，等於沒有這個依賴。

    刻意不猜 tokenizer：未登記的 embedding 模型一律回 None。用錯的 tokenizer 算出來的
    數字不會報錯、只是靜默地不對（bge-m3 是 t5/sentencepiece，改用 tiktoken 的 BPE
    算中文差約 2 倍且方向相反），那比退回字元計數更難查。
    """
    repo = config.CHUNK_TOKENIZERS.get(config.EMBEDDING_MODEL)
    if not repo:
        log.warning("embedding 模型未登記 tokenizer，chunk 改用字元計數", extra={"fields": {
            "reason": "tokenizer_not_registered", "embed_model": config.EMBEDDING_MODEL}})
        return None
    try:
        from tokenizers import Tokenizer
        tok = Tokenizer.from_pretrained(repo)
    except Exception as e:  # noqa: BLE001  載不到就退回，理由見下
        # 寧可切得不準，也不要讓入庫掛掉（與 _embed_in_batches 的取捨一致）。
        # 但一定要留 log：否則會出現「以為在跑 token 臂、其實整批照字元切」而讓
        # A/B 數字無聲失真的情況。事後可用 doc_chunks.chunk_unit 交叉驗證。
        log.warning("tokenizer 載入失敗，chunk 改用字元計數", extra={"fields": {
            "reason": "tokenizer_load_failed", "repo": repo, "error": str(e)}})
        return None
    return lambda s: len(tok.encode(s).ids)


def chunk_text(text: str) -> list[str]:
    """切 chunk。長度單位由 config.CHUNK_UNIT 決定（char／token）。"""
    length_function = len
    if config.CHUNK_UNIT == "token":
        length_function = _token_counter() or len
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", " ", ""],
        length_function=length_function,
    )
    return splitter.split_text(text)


def _embed_in_batches(embeddings, chunks: list[str], source: str) -> list[list[float]]:
    """分批呼叫 embed_documents，逐批重試一次。

    整份一次送在長 filing 上會失敗（見 MAINTENANCE_LOG「大型 filing 的 embedding
    整批失敗」），且失敗率隨批次大小升高、沒有可查表的門檻，故切小再送。
    重試只做一次：實測失敗是資源／超時型，同一批重送常會過，但連兩次不過就
    不是暫時性問題，繼續重試只是把等待時間拉長。逐批記錄耗時與重試，供回測。

    攔 `Exception` 而非指名 `ollama.ResponseError` 是刻意的：本函式的語意是「這批
    送不過去就重試一次」，與失敗原因無關。會讓一批失敗的不只 Ollama 的 400，還有
    連線逾時、容器 OOM 被殺、連線被 reset（`httpx.*`）；指名只接住其中一種，其餘
    照舊拋穿——正是本次修掉的那個病。換 embedding provider（OpenAI／Bedrock／本地
    模型）時例外型別整組會變，指名的話這裡要跟著改，**而忘記改不會報錯，只會靜默
    退回不重試**。範圍已收到只包一次 `embed_documents()`、連兩次失敗必往上拋、且
    失敗有帶 reason 的 log，不會吞掉錯誤。
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
            except Exception as e:  # noqa: BLE001  刻意廣泛攔截，理由見 docstring
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
    title: str | None = None, market: str | None = None,
) -> int:
    """切 chunk → embedding → 寫入 pgvector，回傳寫入的 chunk 數。

    寫入前先 delete_by_source(source) 去重，重跑同一來源不會累積重複資料。

    market 不傳時由 company 的代號格式推定；市場新聞沒有 company（推不出來），
    由呼叫端依來源指定。推定只發生在這一個地方，檢索端直接讀欄位不再推。
    """
    if market is None and company:
        market = "tw" if is_tw_ticker(company) else "us"
    if not text or not text.strip():
        log.warning("內容為空（可能 PDF 抽不出文字），跳過", extra={"fields": {
            "source": source, "company": company, "reason": "no_content"}})
        return 0

    if doc_type == "financial_report" and len(text.strip()) < _MIN_FINANCIAL_REPORT_CHARS:
        log.warning("財報字數偏低，可能選錯檔案或內容不完整，建議人工確認", extra={"fields": {
            "source": source, "company": company, "reason": "short_report",
            "chars": len(text.strip()), "min_chars": _MIN_FINANCIAL_REPORT_CHARS}})

    delete_started = time.monotonic()
    delete_by_source(source)
    delete_ms = round((time.monotonic() - delete_started) * 1000)

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
            "market": market,
            "published_at": dt.date.fromisoformat(published_at) if published_at else None,
            "chunk_index": i,
            "content": chunk,
            "embedding": vec,
        }
        for i, (chunk, vec) in enumerate(zip(chunks, vectors))
    ]

    insert_started = time.monotonic()
    insert_chunks(rows)
    insert_ms = round((time.monotonic() - insert_started) * 1000)
    log.info("已寫入 pgvector", extra={"fields": {
        "source": source, "company": company, "rows": len(rows),
        "delete_ms": delete_ms, "insert_ms": insert_ms}})
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
