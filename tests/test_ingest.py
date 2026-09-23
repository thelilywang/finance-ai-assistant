"""ingest_text() 的財報字數警示。"""
import logging

import pytest

from src import ingest

WARNING_MARK = "可能選錯檔案或內容不完整"

SHORT_TEXT = "短內容" * 10  # 遠低於 10000 字元
LONG_TEXT = "字" * 10000    # 剛好達標


class _FakeEmbeddings:
    def __init__(self, *args, **kwargs):
        pass

    def embed_documents(self, chunks):
        return [[0.0] for _ in chunks]


@pytest.fixture(autouse=True)
def _stub_deps(monkeypatch):
    # 替換掉會連 DB / Ollama 的依賴
    monkeypatch.setattr(ingest, "OllamaEmbeddings", _FakeEmbeddings)
    monkeypatch.setattr(ingest, "delete_by_source", lambda source: None)
    monkeypatch.setattr(ingest, "insert_chunks", lambda rows: None)


def _warned(records) -> bool:
    return any(WARNING_MARK in r.getMessage() for r in records)


def test_short_financial_report_warns(caplog):
    with caplog.at_level(logging.INFO, logger="ingest"):
        n = ingest.ingest_text(SHORT_TEXT, source="s1", company="2330",
                                doc_type="financial_report", published_at=None)
    assert _warned(caplog.records)
    assert n > 0
    # 警示帶得出是哪一份來源與短代碼，回測才彙總得動
    warning = next(r for r in caplog.records if WARNING_MARK in r.getMessage())
    assert warning.fields["source"] == "s1"
    assert warning.fields["reason"] == "short_report"


def test_short_news_does_not_warn(caplog):
    with caplog.at_level(logging.INFO, logger="ingest"):
        ingest.ingest_text(SHORT_TEXT, source="s2", company="2330",
                            doc_type="news", published_at=None)
    assert not _warned(caplog.records)


def test_long_financial_report_does_not_warn(caplog):
    with caplog.at_level(logging.INFO, logger="ingest"):
        ingest.ingest_text(LONG_TEXT, source="s3", company="2330",
                            doc_type="financial_report", published_at=None)
    assert not _warned(caplog.records)


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


CHUNKS = [f"c{i}" for i in range(1000)]


def test_embed_in_batches_splits_by_batch_size(monkeypatch):
    # 實測（JPM 10-Q／1533 塊）：400 以下 2/2 成功、600 是 1/2、不分批 0/2，故預設 400。
    # 這裡只驗分批邏輯本身，不連 Ollama。
    monkeypatch.setattr(ingest.config, "EMBED_BATCH_SIZE", 400)
    emb = _RecordingEmbeddings()
    vectors = ingest._embed_in_batches(emb, CHUNKS, "s")
    # 依 EMBED_BATCH_SIZE 切批，且回傳的向量數與輸入塊數一致（錯位會讓 content 配到別人的向量）
    assert emb.batches == [400, 400, 200], emb.batches
    assert len(vectors) == len(CHUNKS)


def test_embed_in_batches_zero_means_no_split(monkeypatch):
    # 0 代表不分批：整份一次送（A/B 對照組用）
    monkeypatch.setattr(ingest.config, "EMBED_BATCH_SIZE", 0)
    emb = _RecordingEmbeddings()
    ingest._embed_in_batches(emb, CHUNKS, "s")
    assert emb.batches == [1000], emb.batches


def test_embed_in_batches_retries_once_on_failure(monkeypatch, caplog):
    # 單批失敗一次會重試並成功，總向量數不受影響（實測 400 那次就是靠重試過關）
    monkeypatch.setattr(ingest.config, "EMBED_BATCH_SIZE", 400)
    emb = _RecordingEmbeddings(fail_first_n=1)
    with caplog.at_level(logging.INFO, logger="ingest"):
        vectors = ingest._embed_in_batches(emb, CHUNKS, "s")
    assert len(vectors) == len(CHUNKS)
    assert any(r.fields.get("reason") == "embed_batch_failed" for r in caplog.records)


def test_embed_in_batches_raises_after_two_failures(monkeypatch):
    # 連兩次失敗才往上拋：不是暫時性問題，繼續重試只是把等待時間拉長
    monkeypatch.setattr(ingest.config, "EMBED_BATCH_SIZE", 400)
    emb = _RecordingEmbeddings(fail_first_n=2)
    with pytest.raises(RuntimeError):
        ingest._embed_in_batches(emb, CHUNKS, "s")


ZH_TEXT = "本公司本季合併營收為新台幣八千三百五十億元，較去年同期成長百分之三十九點五。" * 120


def _chunk_with(monkeypatch, unit, text=ZH_TEXT):
    monkeypatch.setattr(ingest.config, "CHUNK_UNIT", unit)
    ingest._token_counter.cache_clear()  # 避免沿用上一輪的 tokenizer 判定
    return ingest.chunk_text(text)


def test_chunk_text_char_unit(monkeypatch):
    # char：以字元計，每塊不超過 CHUNK_SIZE 個「字元」
    char_chunks = _chunk_with(monkeypatch, "char")
    assert max(len(c) for c in char_chunks) <= ingest.config.CHUNK_SIZE


def test_chunk_text_token_unit(monkeypatch, caplog):
    # token：中文約 1.60 字元／token，同樣的 CHUNK_SIZE 下每塊裝得下「更多字元」
    # （800 token ≈ 1280 字元），所以塊會變大、總塊數變少。驗塊的大小而非塊數——
    # 塊數在短文字上可能碰巧相同，大小才直接反映單位換了沒。
    # 沒裝 tokenizers（或未登記模型）時會退回字元計數，切法與 char 完全相同、
    # 不算失敗，但必須留下 log——否則會出現「以為在跑 token 臂、其實照字元切」
    # 而讓 A/B 數字無聲失真的情況。
    char_chunks = _chunk_with(monkeypatch, "char")
    with caplog.at_level(logging.INFO, logger="ingest"):
        token_chunks = _chunk_with(monkeypatch, "token")
    fell_back = any(
        r.fields.get("reason") in ("tokenizer_load_failed", "tokenizer_not_registered")
        for r in caplog.records
    )
    if fell_back:
        assert [len(c) for c in token_chunks] == [len(c) for c in char_chunks]
    else:
        # 每塊的 token 數仍受 CHUNK_SIZE 約束（這才是換單位的目的）
        _count = ingest._token_counter()
        assert max(_count(c) for c in token_chunks) <= ingest.config.CHUNK_SIZE
        # 而字元數會超過 CHUNK_SIZE——證明限制的確實是 token 不是字元
        assert max(len(c) for c in token_chunks) > ingest.config.CHUNK_SIZE, \
            [len(c) for c in token_chunks]


def test_chunk_text_token_unit_unregistered_model_falls_back(monkeypatch, caplog):
    # 未登記的 embedding 模型：不猜 tokenizer，退回字元計數並記 log
    char_chunks = _chunk_with(monkeypatch, "char")
    monkeypatch.setattr(ingest.config, "EMBEDDING_MODEL", "some-unregistered-model")
    with caplog.at_level(logging.INFO, logger="ingest"):
        unreg_chunks = _chunk_with(monkeypatch, "token")
    assert any(r.fields.get("reason") == "tokenizer_not_registered" for r in caplog.records)
    assert [len(c) for c in unreg_chunks] == [len(c) for c in char_chunks]
