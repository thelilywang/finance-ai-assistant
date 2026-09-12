"""自檢 retrieve_context 的 query embedding 快取與平行預取，不碰真實 Ollama / DB。

執行：PYTHONDONTWRITEBYTECODE=1 python tests/test_retrieve_context.py
"""
import threading
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.graph as graph


class _Embeddings:
    def __init__(self):
        self.calls = []

    def embed_query(self, question):
        self.calls.append(question)
        return [float(len(self.calls)), 2.0]


original_embeddings = graph.embeddings
original_search = graph.similarity_search
original_pool_stats = graph.pool.get_stats
# 不連 DB，pool 統計只是 log 欄位，給個空的即可
graph.pool.get_stats = lambda: {}
original_model = graph.config.EMBEDDING_MODEL
original_url = graph.config.OLLAMA_BASE_URL
original_size = graph.config.EMBEDDING_CACHE_MAX_ENTRIES
original_ttl = graph.config.EMBEDDING_CACHE_TTL_SECONDS
original_parallel = graph.config.RETRIEVE_PARALLEL
original_monotonic = graph.time.monotonic

try:
    # --- TTL/LRU：相同 query 命中、向量不洩漏可變參照、模型切換與過期皆 miss ---
    fake_embeddings = _Embeddings()
    graph.embeddings = fake_embeddings
    graph.config.EMBEDDING_CACHE_MAX_ENTRIES = 2
    graph.config.EMBEDDING_CACHE_TTL_SECONDS = 10
    now = [100.0]
    graph.time.monotonic = lambda: now[0]
    graph._clear_embedding_cache()

    first, hit = graph._embed_query_cached("AAPL 營收")
    assert hit is False  # 第一次必然 miss
    first[0] = 999.0
    assert graph._embed_query_cached("AAPL 營收") == ([1.0, 2.0], True)
    assert fake_embeddings.calls == ["AAPL 營收"]

    graph.config.EMBEDDING_MODEL = "another-model"
    assert graph._embed_query_cached("AAPL 營收")[1] is False
    assert len(fake_embeddings.calls) == 2  # model 是 cache key 的一部分
    graph.config.EMBEDDING_MODEL = original_model

    now[0] += 11
    assert graph._embed_query_cached("AAPL 營收")[1] is False
    assert len(fake_embeddings.calls) == 3  # TTL 過期

    graph._clear_embedding_cache()
    graph._embed_query_cached("q1")
    graph._embed_query_cached("q2")
    graph._embed_query_cached("q3")
    graph._embed_query_cached("q1")
    assert fake_embeddings.calls[-4:] == ["q1", "q2", "q3", "q1"]  # LRU 淘汰 q1

    # --- 主檢索、同公司新聞、市場新聞候選同時開始；輸出順序維持既有規則 ---
    graph._clear_embedding_cache()
    graph.config.EMBEDDING_CACHE_MAX_ENTRIES = 256
    graph.config.EMBEDDING_CACHE_TTL_SECONDS = 900
    graph.time.monotonic = original_monotonic
    started = []
    started_lock = threading.Lock()
    all_started = threading.Event()

    report = {"id": 1, "source": "report", "doc_type": "financial_report", "company": "AAPL"}
    company_news = {"id": 2, "source": "company-news", "doc_type": "news", "company": "AAPL"}
    duplicate = {"id": 2, "source": "duplicate", "doc_type": "news", "company": "AAPL"}
    market_1 = {"id": 3, "source": "market-1", "doc_type": "news", "company": None}
    market_2 = {"id": 4, "source": "market-2", "doc_type": "news", "company": "MSFT"}

    def fake_search(_vector, **kwargs):
        with started_lock:
            started.append((time.monotonic(), kwargs))
            if len(started) == 3:
                all_started.set()
        assert all_started.wait(0.5), "三段可獨立檢索沒有同時啟動"
        if kwargs.get("exclude_company"):
            return [duplicate, market_1, market_2]
        if kwargs.get("doc_type") == "news":
            return [company_news]
        return [report]

    graph.similarity_search = fake_search
    out = graph.retrieve_context("AAPL 財報", company="AAPL", doc_type="financial_report")
    assert len(started) == 3
    assert max(t for t, _ in started) - min(t for t, _ in started) < 0.2
    assert [d["id"] for d in out] == [1, 2, 3, 4]

    # doc_type 主檢索為空時仍放寬，並維持 relaxed 標記及既有補充順序。
    def fallback_search(_vector, **kwargs):
        if kwargs.get("exclude_company"):
            return [market_1]
        if kwargs.get("doc_type") == "news":
            return [company_news]
        if kwargs.get("doc_type") == "financial_report":
            return []
        return [report]

    graph.similarity_search = fallback_search
    out = graph.retrieve_context("AAPL 財報（fallback）", company="AAPL", doc_type="financial_report")
    assert out[0]["id"] == 1 and out[0]["relaxed"] == "doc_type"
    assert [d["id"] for d in out] == [1, 2, 3]

    # 主結果已有新聞時，同公司新聞預取不會被採用、更不能在 executor 收尾時拖住回覆。
    company_started = threading.Event()
    release_company = threading.Event()
    existing_news = {"id": 5, "source": "existing-news", "doc_type": "news", "company": "AAPL"}

    def unused_candidate_search(_vector, **kwargs):
        if kwargs.get("exclude_company"):
            return []
        if kwargs.get("doc_type") == "news":
            company_started.set()
            assert release_company.wait(1.0)
            return [company_news]
        assert company_started.wait(0.5)
        return [existing_news]

    graph.similarity_search = unused_candidate_search
    start = time.monotonic()
    out = graph.retrieve_context("AAPL 已有新聞", company="AAPL", doc_type="financial_report")
    elapsed = time.monotonic() - start
    release_company.set()
    assert elapsed < 0.2, "未採用的同公司新聞預取不應拖住結果"
    assert out == [existing_news]

    # --- 並行與循序必須產生相同結果：這是 RETRIEVE_PARALLEL 能當回退開關的前提 ---
    def stable_search(_vector, **kwargs):
        if kwargs.get("exclude_company"):
            return [duplicate, market_1, market_2]
        if kwargs.get("doc_type") == "news":
            return [company_news]
        return [report]

    graph.similarity_search = stable_search
    for case in (
        {"company": "AAPL", "doc_type": "financial_report"},
        {"company": "AAPL", "doc_type": None},
        {"company": "AAPL", "doc_type": "financial_report", "news_since_days": 7},
    ):
        graph.config.RETRIEVE_PARALLEL = True
        graph._clear_embedding_cache()
        par = graph.retrieve_context("等價性", **case)
        graph.config.RETRIEVE_PARALLEL = False
        graph._clear_embedding_cache()
        seq = graph.retrieve_context("等價性", **case)
        assert par == seq, f"並行與循序結果不同：{case}"
    graph.config.RETRIEVE_PARALLEL = True

    # 循序路徑也要維持 doc_type 放寬與 relaxed 標記
    graph.similarity_search = fallback_search
    graph.config.RETRIEVE_PARALLEL = False
    graph._clear_embedding_cache()
    out = graph.retrieve_context("AAPL 財報（循序 fallback）", company="AAPL",
                                 doc_type="financial_report")
    assert [d["id"] for d in out] == [1, 2, 3]
    assert out[0]["relaxed"] == "doc_type"
    graph.config.RETRIEVE_PARALLEL = True

    # --- 快取關閉（EMBEDDING_CACHE_*=0）：.env.example 明文承諾的對外契約 ---
    graph.similarity_search = stable_search
    for size, ttl in ((0, 900), (256, 0)):
        graph._clear_embedding_cache()
        graph.config.EMBEDDING_CACHE_MAX_ENTRIES = size
        graph.config.EMBEDDING_CACHE_TTL_SECONDS = ttl
        before = len(fake_embeddings.calls)
        graph._embed_query_cached("關閉快取")
        graph._embed_query_cached("關閉快取")
        assert len(fake_embeddings.calls) - before == 2, f"快取應關閉：size={size} ttl={ttl}"
        assert graph._embed_query_cached("關閉快取")[1] is False
    graph.config.EMBEDDING_CACHE_MAX_ENTRIES = 256
    graph.config.EMBEDDING_CACHE_TTL_SECONDS = 900

    # --- embed 失敗不得寫進快取，否則後續會一直拿到壞向量 ---
    class _Boom:
        def __init__(self):
            self.calls = 0

        def embed_query(self, question):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("ollama 掛了")
            return [7.0, 8.0]

    boom = _Boom()
    graph.embeddings = boom
    graph._clear_embedding_cache()
    try:
        graph._embed_query_cached("會炸的問題")
        raise AssertionError("例外應往外傳，不可被吞掉")
    except RuntimeError:
        pass
    assert graph._embed_query_cached("會炸的問題") == ([7.0, 8.0], False), "失敗不該留下快取項"
    graph.embeddings = fake_embeddings

    # --- 並行分支中任一段檢索失敗，例外要傳出而非回傳半套結果 ---
    def exploding_search(_vector, **kwargs):
        if kwargs.get("exclude_company"):
            raise RuntimeError("market news 查詢失敗")
        if kwargs.get("doc_type") == "news":
            return [company_news]
        return [report]

    graph.similarity_search = exploding_search
    graph._clear_embedding_cache()
    try:
        graph.retrieve_context("市場新聞爆炸", company="AAPL", doc_type="financial_report")
        raise AssertionError("並行分支的例外應往外傳")
    except RuntimeError as e:
        assert "market news 查詢失敗" in str(e)

    # 主檢索失敗同樣要傳出
    def primary_explodes(_vector, **kwargs):
        if kwargs.get("doc_type") == "financial_report":
            raise RuntimeError("主檢索失敗")
        return []

    graph.similarity_search = primary_explodes
    graph._clear_embedding_cache()
    try:
        graph.retrieve_context("主檢索爆炸", company="AAPL", doc_type="financial_report")
        raise AssertionError("主檢索的例外應往外傳")
    except RuntimeError as e:
        assert "主檢索失敗" in str(e)

finally:
    graph.config.RETRIEVE_PARALLEL = original_parallel
    graph.embeddings = original_embeddings
    graph.similarity_search = original_search
    graph.pool.get_stats = original_pool_stats
    graph.config.EMBEDDING_MODEL = original_model
    graph.config.OLLAMA_BASE_URL = original_url
    graph.config.EMBEDDING_CACHE_MAX_ENTRIES = original_size
    graph.config.EMBEDDING_CACHE_TTL_SECONDS = original_ttl
    graph.time.monotonic = original_monotonic
    graph._clear_embedding_cache()

print("retrieve_context self-check OK")
