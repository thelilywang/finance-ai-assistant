"""retrieve_context 的 A/B 效能量測：並行 vs 循序、有快取 vs 無快取。

與 eval_rag_retrieval.py 一樣打真實資料庫，但只看耗時不看檢索品質。
同一份程式碼、同一個容器，用 config 開關切換前後行為，所以數字可比
（MAINTENANCE_LOG 2026-09-10 那組數字是跨 image 比較，回傳筆數都不同，不可比）。

DB 未對 host 開 port，需在 app container 內執行：
    docker exec finance_ai_assistant_app python tests/bench_retrieve.py

可選參數：
    --runs N        每組跑幾次（預設 7，取中位數，第一次另計）
    --pool-sizes    連線池敏感度要測的 max_size，逗號分隔（預設 5,8,12）
    --concurrency   併發情境要測的並行檢索數，逗號分隔（預設 1,2,3,4）
"""
import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, graph, vectorstore

# 六家庫內資料最多的公司；輪流換題避免同一題一直命中同一批 chunk
QUESTIONS = [
    ("AAPL 最新財報與近期新聞", "AAPL"),
    ("MSFT 營收結構與獲利表現", "MSFT"),
    ("NVDA 資料中心業務成長", "NVDA"),
    ("2330 台積電先進製程進展", "2330"),
    ("2454 聯發科手機晶片市況", "2454"),
    ("TSM 美股 ADR 近期表現", "TSM"),
]


def _time_once(question: str, company: str, cold_cache: bool) -> float:
    """跑一次 retrieve_context，回傳毫秒。cold_cache 時先清掉 embedding 快取。"""
    if cold_cache:
        graph._clear_embedding_cache()
    started = time.monotonic()
    graph.retrieve_context(question, company=company)
    return (time.monotonic() - started) * 1000


def measure(label: str, *, parallel: bool, cache: bool, runs: int) -> dict:
    """一組設定跑 runs 次，回傳中位數等統計。

    cache=False 代表每次都清快取（等於每次都要重算 embedding），
    cache=True 則只在最開始清一次，之後都應命中。

    兩者都跑同一組題目、同樣的輪替順序，差別只在快取——否則變動的就不只一個變因。
    """
    config.RETRIEVE_PARALLEL = parallel
    graph._clear_embedding_cache()
    if cache:
        # 先把六題都暖進快取，否則輪替時每題的第一次都是 miss，量到的是混合值
        for question, company in QUESTIONS:
            graph.retrieve_context(question, company=company)

    samples = []
    first = None
    for i in range(runs + 1):
        question, company = QUESTIONS[i % len(QUESTIONS)]
        elapsed = _time_once(question, company, cold_cache=not cache)
        if i == 0:
            first = elapsed  # 第一次含連線池初始化與 Ollama 冷啟動，不併入中位數
        else:
            samples.append(elapsed)

    return {
        "label": label,
        "median": statistics.median(samples),
        "mean": statistics.mean(samples),
        "min": min(samples),
        "max": max(samples),
        "first": first,
        "n": len(samples),
    }


def measure_concurrent(label: str, *, parallel: bool, workers: int, runs: int) -> dict:
    """同時發 workers 個檢索，量整批完成的 wall time 與單筆 p95。

    這組要回答的是「並行檢索互相搶連線時會不會拋 PoolTimeout、p95 有沒有惡化」。
    """
    config.RETRIEVE_PARALLEL = parallel
    graph._clear_embedding_cache()
    # 先把每題的 embedding 暖起來，避免量到的是 Ollama 而不是 DB 競爭
    for question, company in QUESTIONS[:workers]:
        graph.retrieve_context(question, company=company)

    batch_times, per_call, errors = [], [], []
    for _ in range(runs):
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=workers) as pool_exec:
            futures = [
                pool_exec.submit(_time_once, q, c, False)
                for q, c in QUESTIONS[:workers]
            ]
            for f in as_completed(futures):
                try:
                    per_call.append(f.result())
                except Exception as e:  # noqa: BLE001  PoolTimeout 等，記下來不中斷量測
                    errors.append(repr(e))
        batch_times.append((time.monotonic() - started) * 1000)

    ordered = sorted(per_call)
    p95 = ordered[min(int(len(ordered) * 0.95), len(ordered) - 1)] if ordered else float("nan")
    return {
        "label": label,
        "median": statistics.median(batch_times),
        "p95_per_call": p95,
        "errors": errors,
        "n": len(batch_times),
    }


def _set_pool_size(max_size: int) -> None:
    """重建連線池成指定 max_size。pool 是模組級單例，量測敏感度必須換掉它。"""
    from psycopg_pool import ConnectionPool

    old = vectorstore.pool
    new = ConnectionPool(
        config.DATABASE_URL, min_size=1, max_size=max_size,
        kwargs={"autocommit": True}, configure=vectorstore._configure,
        open=False, timeout=2,
    )
    vectorstore.pool = new
    graph.pool = new  # graph 是 from ... import pool，要一起換
    try:
        old.close()
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument("--pool-sizes", default="5,8,12")
    ap.add_argument("--concurrency", default="1,2,3,4")
    args = ap.parse_args()

    original_parallel = config.RETRIEVE_PARALLEL
    original_cache_size = config.EMBEDDING_CACHE_MAX_ENTRIES
    original_pool = vectorstore.pool

    try:
        print(f"每組 {args.runs} 次取中位數（第一次另計），單位毫秒\n")

        print("=== 1-4. 並行 x 快取 四組組合 ===")
        rows = []
        for parallel in (False, True):
            for cache in (False, True):
                name = f"{'並行' if parallel else '循序'} + {'有快取' if cache else '無快取'}"
                rows.append(measure(name, parallel=parallel, cache=cache, runs=args.runs))
        for r in rows:
            print(f"  {r['label']:<20} 中位 {r['median']:7.1f}  平均 {r['mean']:7.1f}  "
                  f"最小 {r['min']:7.1f}  最大 {r['max']:7.1f}  首次 {r['first']:7.1f}")

        seq_cold = next(r for r in rows if r["label"] == "循序 + 無快取")["median"]
        par_cold = next(r for r in rows if r["label"] == "並行 + 無快取")["median"]
        seq_warm = next(r for r in rows if r["label"] == "循序 + 有快取")["median"]
        par_warm = next(r for r in rows if r["label"] == "並行 + 有快取")["median"]
        print(f"\n  快取效益（循序）：{seq_cold:.1f} → {seq_warm:.1f} "
              f"（省 {seq_cold - seq_warm:.1f}ms）")
        print(f"  並行效益（無快取）：{seq_cold:.1f} → {par_cold:.1f} "
              f"（{'省' if par_cold < seq_cold else '多'} {abs(seq_cold - par_cold):.1f}ms）")
        print(f"  並行效益（有快取）：{seq_warm:.1f} → {par_warm:.1f} "
              f"（{'省' if par_warm < seq_warm else '多'} {abs(seq_warm - par_warm):.1f}ms）")

        print("\n=== 5. 連線池 max_size 敏感度（並行、無快取）===")
        for size in [int(s) for s in args.pool_sizes.split(",")]:
            _set_pool_size(size)
            r = measure(f"max_size={size}", parallel=True, cache=False, runs=args.runs)
            print(f"  {r['label']:<20} 中位 {r['median']:7.1f}  最大 {r['max']:7.1f}")

        print("\n=== 6. 併發情境（每組先暖快取，只量 DB 競爭）===")
        for size in [int(s) for s in args.pool_sizes.split(",")]:
            _set_pool_size(size)
            print(f"  -- max_size={size} --")
            for workers in [int(c) for c in args.concurrency.split(",")]:
                r = measure_concurrent(f"{workers} 個並行檢索", parallel=True,
                                       workers=workers, runs=max(3, args.runs // 2))
                err = f"  錯誤 {len(r['errors'])} 次：{r['errors'][0]}" if r["errors"] else ""
                print(f"     {r['label']:<16} 批次中位 {r['median']:7.1f}  "
                      f"單筆 p95 {r['p95_per_call']:7.1f}{err}")

    finally:
        config.RETRIEVE_PARALLEL = original_parallel
        config.EMBEDDING_CACHE_MAX_ENTRIES = original_cache_size
        if vectorstore.pool is not original_pool:
            try:
                vectorstore.pool.close()
            except Exception:  # noqa: BLE001
                pass
            vectorstore.pool = original_pool
            graph.pool = original_pool
        graph._clear_embedding_cache()


if __name__ == "__main__":
    main()
