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

# --- _embed_in_batches：分批、重試、失敗才拋 ---
# 實測（JPM 10-Q／1533 塊）：400 以下 2/2 成功、600 是 1/2、不分批 0/2，故預設 400。
# 這裡只驗分批邏輯本身，不連 Ollama。

class _RecordingEmbeddings:
    """記下每批大小；fail_first_n 指定前幾次呼叫要拋錯（模擬資源型失敗）。"""

    def __init__(self, fail_first_n: int = 0):
        self.batches = []
        self.calls = 0
        self.fail_first_n = fail_first_n

    def embed_documents(self, chunks):
        self.calls += 1
        if self.calls <= self.fail_first_n:
            raise RuntimeError("Post \".../tokenize\": EOF")
        self.batches.append(len(chunks))
        return [[0.0] for _ in chunks]


chunks = [f"c{i}" for i in range(1000)]

# 依 EMBED_BATCH_SIZE 切批，且回傳的向量數與輸入塊數一致（錯位會讓 content 配到別人的向量）
ingest.config.EMBED_BATCH_SIZE = 400
emb = _RecordingEmbeddings()
vectors = ingest._embed_in_batches(emb, chunks, "s")
assert emb.batches == [400, 400, 200], emb.batches
assert len(vectors) == len(chunks)

# 0 代表不分批：整份一次送（A/B 對照組用）
ingest.config.EMBED_BATCH_SIZE = 0
emb = _RecordingEmbeddings()
ingest._embed_in_batches(emb, chunks, "s")
assert emb.batches == [1000], emb.batches

# 單批失敗一次會重試並成功，總向量數不受影響（實測 400 那次就是靠重試過關）
ingest.config.EMBED_BATCH_SIZE = 400
emb = _RecordingEmbeddings(fail_first_n=1)
with captured_logs() as records:
    vectors = ingest._embed_in_batches(emb, chunks, "s")
assert len(vectors) == len(chunks)
assert any(r.fields.get("reason") == "embed_batch_failed" for r in records)

# 連兩次失敗才往上拋：不是暫時性問題，繼續重試只是把等待時間拉長
emb = _RecordingEmbeddings(fail_first_n=2)
try:
    ingest._embed_in_batches(emb, chunks, "s")
except RuntimeError:
    pass
else:
    raise AssertionError("連續失敗應往上拋")

ingest.config.EMBED_BATCH_SIZE = 400  # 還原，避免影響後續
print("ingest self-check OK")
