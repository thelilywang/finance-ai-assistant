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

    latest = {"id": 6, "source": "latest-report", "doc_type": "financial_report",
              "company": "AAPL"}

    def fake_search(_vector, **kwargs):
        with started_lock:
            started.append((time.monotonic(), kwargs))
            if len(started) == 4:
                all_started.set()
        assert all_started.wait(0.5), "四段可獨立檢索沒有同時啟動"
        if kwargs.get("latest_source_only"):
            return [latest]
        if kwargs.get("exclude_company"):
            return [duplicate, market_1, market_2]
        if kwargs.get("doc_type") == "news":
            return [company_news]
        return [report]

    graph.similarity_search = fake_search
    out = graph.retrieve_context("AAPL 財報", company="AAPL", doc_type="financial_report")
    assert len(started) == 4
    assert max(t for t, _ in started) - min(t for t, _ in started) < 0.2
    # 最新一期財報排在最前面，舊資料仍保留在後（比較去年同期還要用得到）
    assert [d["id"] for d in out] == [6, 1, 2, 3, 4]
    assert out[0]["latest_period"] is True

    # doc_type 主檢索為空時仍放寬，並維持 relaxed 標記及既有補充順序。
    def fallback_search(_vector, **kwargs):
        if kwargs.get("latest_source_only"):
            return [latest]
        if kwargs.get("exclude_company"):
            return [market_1]
        if kwargs.get("doc_type") == "news":
            return [company_news]
        if kwargs.get("doc_type") == "financial_report":
            return []
        return [report]

    graph.similarity_search = fallback_search
    out = graph.retrieve_context("AAPL 財報（fallback）", company="AAPL", doc_type="financial_report")
    # 放寬過 doc_type 代表財報撈不到，此時不得再插最新財報席位（id 6 不該出現）
    assert out[0]["id"] == 1 and out[0]["relaxed"] == "doc_type"
    assert [d["id"] for d in out] == [1, 2, 3]

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
        if kwargs.get("latest_source_only"):
            return [latest]
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
            return [fresh(latest)]
        if kwargs.get("exclude_company"):
            return [fresh(market_1)]
        if kwargs.get("doc_type") == "news":
            return [fresh(company_news)]
        return [fresh(report)]

    graph.similarity_search = recording_search
    for parallel in (True, False):
        graph.config.RETRIEVE_PARALLEL = parallel
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
    graph.config.RETRIEVE_PARALLEL = True

    # 最新一期的 chunk 已在主結果裡時不得重複（去重靠 id）
    # 同樣回新 dict 隔離共用 fixture（見 recording_search 的註解）
    def _fresh(d):
        return {k: v for k, v in d.items() if k != "relaxed"}

    def overlapping_search(_vector, **kwargs):
        if kwargs.get("latest_source_only"):
            return [_fresh(report)]  # 與主檢索同一筆
        if kwargs.get("exclude_company"):
            return []
        if kwargs.get("doc_type") == "news":
            return [_fresh(company_news)]
        return [_fresh(report)]

    graph.similarity_search = overlapping_search
    graph._clear_embedding_cache()
    out = graph.retrieve_context("AAPL 重疊", company="AAPL", doc_type="financial_report")
    assert [d["id"] for d in out].count(1) == 1, "最新財報與主結果重疊時不該重複列出"

    # 席位上限為 _LATEST_REPORT_K：撈回一大批也只插前幾塊，不吃掉其他素材的名額
    many = [dict(latest, id=100 + i) for i in range(6)]

    def flooding_search(_vector, **kwargs):
        if kwargs.get("latest_source_only"):
            return [dict(d) for d in many]
        if kwargs.get("exclude_company"):
            return []
        if kwargs.get("doc_type") == "news":
            return [_fresh(company_news)]
        return [_fresh(report)]

    graph.similarity_search = flooding_search
    graph._clear_embedding_cache()
    out = graph.retrieve_context("AAPL 洪水", company="AAPL", doc_type="financial_report")
    inserted = [d["id"] for d in out if d["id"] >= 100]
    assert inserted == [100, 101], f"席位應上限 {graph._LATEST_REPORT_K} 塊，實得 {inserted}"

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
        if kwargs.get("latest_source_only"):
            return [latest]
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
        if kwargs.get("latest_source_only"):
            return []
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
