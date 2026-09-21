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

# --- chunk_text：長度單位（config.CHUNK_UNIT）---
# 單位錯不會報錯，只會讓 CHUNK_SIZE 對中英文語意不同（真實語料實測 bge-m3 中文
# 1.60、英文 3.84 字元／token，差 2.4 倍），故這裡驗的是「走到哪條計數路徑」。

_orig_unit = ingest.config.CHUNK_UNIT
zh_text = "本公司本季合併營收為新台幣八千三百五十億元，較去年同期成長百分之三十九點五。" * 120


def _chunk_with(unit, text=zh_text):
    ingest.config.CHUNK_UNIT = unit
    ingest._token_counter.cache_clear()  # 避免沿用上一輪的 tokenizer 判定
    return ingest.chunk_text(text)


try:
    # char：以字元計，每塊不超過 CHUNK_SIZE 個「字元」
    char_chunks = _chunk_with("char")
    assert max(len(c) for c in char_chunks) <= ingest.config.CHUNK_SIZE

    # token：中文約 1.60 字元／token，同樣的 CHUNK_SIZE 下每塊裝得下「更多字元」
    # （800 token ≈ 1280 字元），所以塊會變大、總塊數變少。驗塊的大小而非塊數——
    # 塊數在短文字上可能碰巧相同，大小才直接反映單位換了沒。
    # 沒裝 tokenizers（或未登記模型）時會退回字元計數，切法與 char 完全相同、
    # 不算失敗，但必須留下 log——否則會出現「以為在跑 token 臂、其實照字元切」
    # 而讓 A/B 數字無聲失真的情況。
    with captured_logs() as records:
        token_chunks = _chunk_with("token")
    fell_back = any(
        r.fields.get("reason") in ("tokenizer_load_failed", "tokenizer_not_registered")
        for r in records
    )
    if fell_back:
        assert [len(c) for c in token_chunks] == [len(c) for c in char_chunks]
        print("  (tokenizer 不可用，已退回字元計數並留下 log)")
    else:
        # 每塊的 token 數仍受 CHUNK_SIZE 約束（這才是換單位的目的）
        _count = ingest._token_counter()
        assert max(_count(c) for c in token_chunks) <= ingest.config.CHUNK_SIZE
        # 而字元數會超過 CHUNK_SIZE——證明限制的確實是 token 不是字元
        assert max(len(c) for c in token_chunks) > ingest.config.CHUNK_SIZE, \
            [len(c) for c in token_chunks]

    # 未登記的 embedding 模型：不猜 tokenizer，退回字元計數並記 log
    _orig_model = ingest.config.EMBEDDING_MODEL
    ingest.config.EMBEDDING_MODEL = "some-unregistered-model"
    with captured_logs() as records:
        unreg_chunks = _chunk_with("token")
    assert any(r.fields.get("reason") == "tokenizer_not_registered" for r in records)
    assert [len(c) for c in unreg_chunks] == [len(c) for c in char_chunks]
    ingest.config.EMBEDDING_MODEL = _orig_model
finally:
    ingest.config.CHUNK_UNIT = _orig_unit
    ingest._token_counter.cache_clear()

print("ingest self-check OK")
