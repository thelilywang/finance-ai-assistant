"""自檢 retrieve_context 的 query embedding 快取與平行預取，不碰真實 Ollama / DB。"""
import threading
import time

import pytest

import src.graph as graph


class _Embeddings:
    def __init__(self):
        self.calls = []

    def embed_query(self, question):
        self.calls.append(question)
        return [float(len(self.calls)), 2.0]


@pytest.fixture(autouse=True)
def _no_pool_stats(monkeypatch):
    # 不連 DB，pool 統計只是 log 欄位，給個空的即可
    monkeypatch.setattr(graph.pool, "get_stats", lambda: {})
    yield
    graph._clear_embedding_cache()


@pytest.fixture
def fake_embeddings(monkeypatch):
    fake = _Embeddings()
    monkeypatch.setattr(graph, "embeddings", fake)
    return fake


def test_embedding_cache_ttl_and_lru(monkeypatch, fake_embeddings):
    # --- TTL/LRU：相同 query 命中、向量不洩漏可變參照、模型切換與過期皆 miss ---
    monkeypatch.setattr(graph.config, "EMBEDDING_CACHE_MAX_ENTRIES", 2)
    monkeypatch.setattr(graph.config, "EMBEDDING_CACHE_TTL_SECONDS", 10)
    now = [100.0]
    monkeypatch.setattr(graph.time, "monotonic", lambda: now[0])
    graph._clear_embedding_cache()

    first, hit = graph._embed_query_cached("AAPL 營收")
    assert hit is False  # 第一次必然 miss
    first[0] = 999.0
    assert graph._embed_query_cached("AAPL 營收") == ([1.0, 2.0], True)
    assert fake_embeddings.calls == ["AAPL 營收"]

    original_model = graph.config.EMBEDDING_MODEL
    monkeypatch.setattr(graph.config, "EMBEDDING_MODEL", "another-model")
    assert graph._embed_query_cached("AAPL 營收")[1] is False
    assert len(fake_embeddings.calls) == 2  # model 是 cache key 的一部分
    monkeypatch.setattr(graph.config, "EMBEDDING_MODEL", original_model)

    now[0] += 11
    assert graph._embed_query_cached("AAPL 營收")[1] is False
    assert len(fake_embeddings.calls) == 3  # TTL 過期


def test_embedding_cache_lru_eviction(fake_embeddings, monkeypatch):
    monkeypatch.setattr(graph.config, "EMBEDDING_CACHE_MAX_ENTRIES", 2)
    monkeypatch.setattr(graph.config, "EMBEDDING_CACHE_TTL_SECONDS", 10)
    graph._clear_embedding_cache()
    graph._embed_query_cached("q1")
    graph._embed_query_cached("q2")
    graph._embed_query_cached("q3")
    graph._embed_query_cached("q1")
    assert fake_embeddings.calls[-4:] == ["q1", "q2", "q3", "q1"]  # LRU 淘汰 q1


# --- 共用治具資料 ---
REPORT = {"id": 1, "source": "report", "doc_type": "financial_report", "company": "AAPL"}
COMPANY_NEWS = {"id": 2, "source": "company-news", "doc_type": "news", "company": "AAPL"}
DUPLICATE = {"id": 2, "source": "duplicate", "doc_type": "news", "company": "AAPL"}
MARKET_1 = {"id": 3, "source": "market-1", "doc_type": "news", "company": None}
MARKET_2 = {"id": 4, "source": "market-2", "doc_type": "news", "company": "MSFT"}
LATEST = {"id": 6, "source": "latest-report", "doc_type": "financial_report", "company": "AAPL"}


def _stable_search(_vector, **kwargs):
    if kwargs.get("latest_source_only"):
        return [LATEST]
    if kwargs.get("exclude_company"):
        return [DUPLICATE, MARKET_1, MARKET_2]
    if kwargs.get("doc_type") == "news":
        return [COMPANY_NEWS]
    return [REPORT]


def test_parallel_prefetch_starts_together_and_orders_results(monkeypatch, fake_embeddings):
    # --- 主檢索、同公司新聞、市場新聞候選同時開始；輸出順序維持既有規則 ---
    started = []
    started_lock = threading.Lock()
    all_started = threading.Event()

    def fake_search(_vector, **kwargs):
        with started_lock:
            started.append((time.monotonic(), kwargs))
            if len(started) == 4:
                all_started.set()
        assert all_started.wait(0.5), "四段可獨立檢索沒有同時啟動"
        if kwargs.get("latest_source_only"):
            return [LATEST]
        if kwargs.get("exclude_company"):
            return [DUPLICATE, MARKET_1, MARKET_2]
        if kwargs.get("doc_type") == "news":
            return [COMPANY_NEWS]
        return [REPORT]

    monkeypatch.setattr(graph, "similarity_search", fake_search)
    out = graph.retrieve_context("AAPL 財報", company="AAPL", doc_type="financial_report")
    assert len(started) == 4
    assert max(t for t, _ in started) - min(t for t, _ in started) < 0.2
    # 最新一期財報排在最前面，舊資料仍保留在後（比較去年同期還要用得到）
    assert [d["id"] for d in out] == [6, 1, 2, 3, 4]
    assert out[0]["latest_period"] is True


def test_relaxed_doc_type_fallback(monkeypatch, fake_embeddings):
    def fallback_search(_vector, **kwargs):
        if kwargs.get("latest_source_only"):
            return [LATEST]
        if kwargs.get("exclude_company"):
            return [MARKET_1]
        if kwargs.get("doc_type") == "news":
            return [COMPANY_NEWS]
        if kwargs.get("doc_type") == "financial_report":
            return []
        return [REPORT]

    # doc_type 主檢索為空時仍放寬，並維持 relaxed 標記及既有補充順序。
    monkeypatch.setattr(graph, "similarity_search", fallback_search)
    out = graph.retrieve_context("AAPL 財報（fallback）", company="AAPL", doc_type="financial_report")
    # 放寬過 doc_type 代表財報撈不到，此時不得再插最新財報席位（id 6 不該出現）
    assert out[0]["id"] == 1 and out[0]["relaxed"] == "doc_type"
    assert [d["id"] for d in out] == [1, 2, 3]

    # 循序路徑也要維持 doc_type 放寬與 relaxed 標記
    monkeypatch.setattr(graph.config, "RETRIEVE_PARALLEL", False)
    out = graph.retrieve_context("AAPL 財報（循序 fallback）", company="AAPL",
                                 doc_type="financial_report")
    assert [d["id"] for d in out] == [1, 2, 3]
    assert out[0]["relaxed"] == "doc_type"


def test_unused_company_news_prefetch_does_not_block(monkeypatch, fake_embeddings):
    # 主結果已有新聞時，同公司新聞預取不會被採用、更不能在 executor 收尾時拖住回覆。
    company_started = threading.Event()
    release_company = threading.Event()
    existing_news = {"id": 5, "source": "existing-news", "doc_type": "news", "company": "AAPL"}

    def unused_candidate_search(_vector, **kwargs):
        if kwargs.get("latest_source_only"):
            return []
        if kwargs.get("exclude_company"):
            return []
        if kwargs.get("doc_type") == "news":
            company_started.set()
            assert release_company.wait(1.0)
            return [COMPANY_NEWS]
        assert company_started.wait(0.5)
        return [existing_news]

    monkeypatch.setattr(graph, "similarity_search", unused_candidate_search)
    start = time.monotonic()
    out = graph.retrieve_context("AAPL 已有新聞", company="AAPL", doc_type="financial_report")
    elapsed = time.monotonic() - start
    release_company.set()
    assert elapsed < 0.2, "未採用的同公司新聞預取不應拖住結果"
    assert out == [existing_news]


def test_parallel_and_sequential_produce_same_result(monkeypatch, fake_embeddings):
    # --- 並行與循序必須產生相同結果：這是 RETRIEVE_PARALLEL 能當回退開關的前提 ---
    monkeypatch.setattr(graph, "similarity_search", _stable_search)
    for case in (
        {"company": "AAPL", "doc_type": "financial_report"},
        {"company": "AAPL", "doc_type": None},
        {"company": "AAPL", "doc_type": "financial_report", "news_since_days": 7},
    ):
        monkeypatch.setattr(graph.config, "RETRIEVE_PARALLEL", True)
        graph._clear_embedding_cache()
        par = graph.retrieve_context("等價性", **case)
        monkeypatch.setattr(graph.config, "RETRIEVE_PARALLEL", False)
        graph._clear_embedding_cache()
        seq = graph.retrieve_context("等價性", **case)
        assert par == seq, f"並行與循序結果不同：{case}"


def test_latest_report_slot_trigger_conditions(monkeypatch, fake_embeddings):
    # --- 最新財報席位的觸發邊界：只在「指名公司 + 財報問題」成立 ---
    # 這個席位存在的理由是顆粒度不對稱（結構化財報整季 2 塊 vs PDF 上百塊），
    # 亂插會擠掉新聞席位，故觸發條件要有守門的斷言
    # 上鎖是因為並行路徑的未採用預取會在 shutdown(wait=False) 後繼續跑完，
    # 沒鎖的話那條背景查詢可能在下一個子案例 clear() 之後才記進來，算成別人的呼叫
    latest_calls = []
    latest_lock = threading.Lock()

    def recording_search(_vector, **kwargs):
        # 一律回新 dict，模擬正式環境每次查詢都拿到新的 row：共用 fixture 若被就地
        # 寫入，殘留標記會讓最新財報席位誤判成「已放寬」而不觸發（歷史 bug，見
        # MAINTENANCE_LOG）。_relax_doc_type 現已回傳複本，這裡維持隔離當防呆。
        def fresh(d):
            return {k: v for k, v in d.items() if k != "relaxed"}

        if kwargs.get("latest_source_only"):
            with latest_lock:
                latest_calls.append(kwargs)
            return [fresh(LATEST)]
        if kwargs.get("exclude_company"):
            return [fresh(MARKET_1)]
        if kwargs.get("doc_type") == "news":
            return [fresh(COMPANY_NEWS)]
        return [fresh(REPORT)]

    monkeypatch.setattr(graph, "similarity_search", recording_search)
    for parallel in (True, False):
        monkeypatch.setattr(graph.config, "RETRIEVE_PARALLEL", parallel)
        # 新聞問題不插財報席位
        with latest_lock:
            latest_calls.clear()
        graph._clear_embedding_cache()
        out = graph.retrieve_context("AAPL 新聞", company="AAPL", doc_type="news")
        with latest_lock:
            assert latest_calls == [], f"新聞問題不該查最新財報（parallel={parallel}）"
        assert all(d["id"] != 6 for d in out)

        # doc_type 為 None（意圖不明）同樣不插，否則會把財報硬塞進泛用查詢
        with latest_lock:
            latest_calls.clear()
        graph._clear_embedding_cache()
        graph.retrieve_context("AAPL 怎麼樣", company="AAPL", doc_type=None)
        with latest_lock:
            assert latest_calls == [], f"doc_type 未指定不該查最新財報（parallel={parallel}）"

        # 沒有 company 就無從定義「最新一期」（SQL 子查詢依 company 取 max）
        with latest_lock:
            latest_calls.clear()
        graph._clear_embedding_cache()
        graph.retrieve_context("大盤財報", company=None, doc_type="financial_report")
        with latest_lock:
            assert latest_calls == [], f"無 company 不該查最新財報（parallel={parallel}）"

        # 財報問題則必須查，且帶上同一個 company/doc_type
        with latest_lock:
            latest_calls.clear()
        graph._clear_embedding_cache()
        graph.retrieve_context("AAPL 最新財報", company="AAPL", doc_type="financial_report")
        with latest_lock:
            assert len(latest_calls) == 1, f"財報問題應查最新財報（parallel={parallel}）"
            assert latest_calls[0]["company"] == "AAPL"
            assert latest_calls[0]["doc_type"] == "financial_report"


def test_latest_report_slot_dedup_and_cap(monkeypatch, fake_embeddings):
    def _fresh(d):
        return {k: v for k, v in d.items() if k != "relaxed"}

    # 最新一期的 chunk 已在主結果裡時不得重複（去重靠 id）
    def overlapping_search(_vector, **kwargs):
        if kwargs.get("latest_source_only"):
            return [_fresh(REPORT)]  # 與主檢索同一筆
        if kwargs.get("exclude_company"):
            return []
        if kwargs.get("doc_type") == "news":
            return [_fresh(COMPANY_NEWS)]
        return [_fresh(REPORT)]

    monkeypatch.setattr(graph, "similarity_search", overlapping_search)
    out = graph.retrieve_context("AAPL 重疊", company="AAPL", doc_type="financial_report")
    assert [d["id"] for d in out].count(1) == 1, "最新財報與主結果重疊時不該重複列出"

    # 席位上限為 _LATEST_REPORT_K：撈回一大批也只插前幾塊，不吃掉其他素材的名額
    many = [dict(LATEST, id=100 + i) for i in range(6)]

    def flooding_search(_vector, **kwargs):
        if kwargs.get("latest_source_only"):
            return [dict(d) for d in many]
        if kwargs.get("exclude_company"):
            return []
        if kwargs.get("doc_type") == "news":
            return [_fresh(COMPANY_NEWS)]
        return [_fresh(REPORT)]

    monkeypatch.setattr(graph, "similarity_search", flooding_search)
    graph._clear_embedding_cache()
    out = graph.retrieve_context("AAPL 洪水", company="AAPL", doc_type="financial_report")
    inserted = [d["id"] for d in out if d["id"] >= 100]
    assert inserted == [100, 101], f"席位應上限 {graph._LATEST_REPORT_K} 塊，實得 {inserted}"


def test_embedding_cache_disabled(monkeypatch, fake_embeddings):
    # --- 快取關閉（EMBEDDING_CACHE_*=0）：.env.example 明文承諾的對外契約 ---
    monkeypatch.setattr(graph, "similarity_search", _stable_search)
    for size, ttl in ((0, 900), (256, 0)):
        graph._clear_embedding_cache()
        monkeypatch.setattr(graph.config, "EMBEDDING_CACHE_MAX_ENTRIES", size)
        monkeypatch.setattr(graph.config, "EMBEDDING_CACHE_TTL_SECONDS", ttl)
        before = len(fake_embeddings.calls)
        graph._embed_query_cached("關閉快取")
        graph._embed_query_cached("關閉快取")
        assert len(fake_embeddings.calls) - before == 2, f"快取應關閉：size={size} ttl={ttl}"
        assert graph._embed_query_cached("關閉快取")[1] is False


def test_embed_failure_not_cached(monkeypatch):
    # --- embed 失敗不得寫進快取，否則後續會一直拿到壞向量 ---
    class _Boom:
        def __init__(self):
            self.calls = 0

        def embed_query(self, question):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("ollama 掛了")
            return [7.0, 8.0]

    monkeypatch.setattr(graph, "embeddings", _Boom())
    graph._clear_embedding_cache()
    with pytest.raises(RuntimeError):
        graph._embed_query_cached("會炸的問題")
    assert graph._embed_query_cached("會炸的問題") == ([7.0, 8.0], False), "失敗不該留下快取項"


def test_parallel_branch_exception_propagates(monkeypatch, fake_embeddings):
    # --- 並行分支中任一段檢索失敗，例外要傳出而非回傳半套結果 ---
    def exploding_search(_vector, **kwargs):
        if kwargs.get("latest_source_only"):
            return [LATEST]
        if kwargs.get("exclude_company"):
            raise RuntimeError("market news 查詢失敗")
        if kwargs.get("doc_type") == "news":
            return [COMPANY_NEWS]
        return [REPORT]

    monkeypatch.setattr(graph, "similarity_search", exploding_search)
    with pytest.raises(RuntimeError, match="market news 查詢失敗"):
        graph.retrieve_context("市場新聞爆炸", company="AAPL", doc_type="financial_report")


def test_primary_search_exception_propagates(monkeypatch, fake_embeddings):
    # 主檢索失敗同樣要傳出
    def primary_explodes(_vector, **kwargs):
        if kwargs.get("latest_source_only"):
            return []
        if kwargs.get("doc_type") == "financial_report":
            raise RuntimeError("主檢索失敗")
        return []

    monkeypatch.setattr(graph, "similarity_search", primary_explodes)
    with pytest.raises(RuntimeError, match="主檢索失敗"):
        graph.retrieve_context("主檢索爆炸", company="AAPL", doc_type="financial_report")
