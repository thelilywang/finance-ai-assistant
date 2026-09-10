"""最小 self-check：ingest_text() 的財報字數警示。
執行：python tests/test_ingest.py
"""
import io
import sys
from contextlib import redirect_stdout
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

short_text = "短內容" * 10  # 遠低於 10000 字元
long_text = "字" * 10000    # 剛好達標

# 財報 + 短文字 → 印出警示，仍正常呼叫 insert_chunks（回傳 chunk 數 > 0）
buf = io.StringIO()
with redirect_stdout(buf):
    n = ingest.ingest_text(short_text, source="s1", company="2330",
                            doc_type="financial_report", published_at=None)
assert WARNING_MARK in buf.getvalue()
assert n > 0

# news + 短文字 → 不印警示
buf = io.StringIO()
with redirect_stdout(buf):
    ingest.ingest_text(short_text, source="s2", company="2330",
                        doc_type="news", published_at=None)
assert WARNING_MARK not in buf.getvalue()

# 財報 + 長文字（>= 10000 字元）→ 不印警示
buf = io.StringIO()
with redirect_stdout(buf):
    ingest.ingest_text(long_text, source="s3", company="2330",
                        doc_type="financial_report", published_at=None)
assert WARNING_MARK not in buf.getvalue()

print("ingest self-check OK")
