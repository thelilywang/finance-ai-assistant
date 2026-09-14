"""最小 self-check：ingest_text() 的財報字數警示。
執行：python tests/test_ingest.py
"""
import logging
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import ingest


class _FakeEmbeddings:
    def __init__(self, *args, **kwargs):
        pass

    def embed_documents(self, chunks):
        return [[0.0] for _ in chunks]


# 替換掉會連 DB / Ollama 的依賴
ingest.OllamaEmbeddings = _FakeEmbeddings
ingest.delete_by_source = lambda source: None
ingest.insert_chunks = lambda rows: None

WARNING_MARK = "可能選錯檔案或內容不完整"


@contextmanager
def captured_logs():
    """收 ingest 的 log 訊息。警示已從 print 改走 logging，stdout 攔不到。"""
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    ingest.log.addHandler(handler)
    ingest.log.setLevel(logging.INFO)
    try:
        yield records
    finally:
        ingest.log.removeHandler(handler)

short_text = "短內容" * 10  # 遠低於 10000 字元
long_text = "字" * 10000    # 剛好達標

def warned(records) -> bool:
    return any(WARNING_MARK in r.getMessage() for r in records)


# 財報 + 短文字 → 發出警示，仍正常呼叫 insert_chunks（回傳 chunk 數 > 0）
with captured_logs() as records:
    n = ingest.ingest_text(short_text, source="s1", company="2330",
                            doc_type="financial_report", published_at=None)
assert warned(records)
assert n > 0
# 警示帶得出是哪一份來源與短代碼，回測才彙總得動
warning = next(r for r in records if WARNING_MARK in r.getMessage())
assert warning.fields["source"] == "s1"
assert warning.fields["reason"] == "short_report"

# news + 短文字 → 不發警示
with captured_logs() as records:
    ingest.ingest_text(short_text, source="s2", company="2330",
                        doc_type="news", published_at=None)
assert not warned(records)

# 財報 + 長文字（>= 10000 字元）→ 不發警示
with captured_logs() as records:
    ingest.ingest_text(long_text, source="s3", company="2330",
                        doc_type="financial_report", published_at=None)
assert not warned(records)

print("ingest self-check OK")
