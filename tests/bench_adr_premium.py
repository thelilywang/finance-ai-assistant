"""ADR 溢價區塊的 A/B：加了溢價區塊與例外句後，模型是否還會自己換算 EPS。

背景：實測問「台積電台股和 ADR 的 EPS 差多少？」時，模型自己用匯率與 1:5 比例換算
EPS（明確違反 dual_market_warning 的「不得直接相除、相減或換算」），算錯又繞圈。
要量清楚這是不是新加的例外句或溢價區塊本身誘發的。

兩臂，同程式碼同容器，只用環境變數切換（見 src/config.ADR_PREMIUM）：
    off    不呼叫 get_adr_premium，不附溢價區塊（等同該功能不存在）
    block  附溢價區塊（預設）

10-07 結果（當時另有第三臂 full＝block＋例外句，已移除）：ADR 題引用溢價率
block 3/3、full 3/3；EPS 題人工判讀自行換算 block 1/3、full 1/3（皆算錯）；
off 的 EPS 回答 3 次都在 119 字處斷句，原因未查。注意 generate 是 temperature=0，
同臂多次幾乎是同一份回答，--runs 只反映即時行情的變動，不是獨立樣本。
self_convert 是 heuristic，當次兩筆真換算都漏判，請以人工判讀為準。

兩題：
    ADR_Q  台積電的 ADR 與台股表現有什麼差異？——正常使用情境，預期會引用溢價區塊
    EPS_Q  台積電台股和 ADR 的 EPS 差多少？——誘發題，驗證模型是否仍自行換算 EPS

固定 generate 之前的 state：第一次跑某題時，把 src.graph.generate monkeypatch 成
丟出帶 state 複本的例外，跑完整個 compiled graph 到 generate 前一刻為止，把 state
存成 fixture json；之後檔案存在就直接讀，不再重新檢索/跑 agent，避免這兩段的隨機性
汙染 A/B。行情仍在 generate 內即時抓（這是可以接受的，溢價率本來就該是當下算的）。

在 app container 內執行（單臂單題約數十秒到數分鐘，視模型與檢索耗時；
兩臂 × 兩題請留數十分鐘）：
    docker exec -e ADR_PREMIUM=off finance_ai_assistant_app \\
        python tests/bench_adr_premium.py --runs 3 --q both
    docker exec -e ADR_PREMIUM=block finance_ai_assistant_app \\
        python tests/bench_adr_premium.py --runs 3 --q both
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "bench"
RESULT_PATH = FIXTURE_DIR / "adr_ab.jsonl"

ADR_Q = "台積電的 ADR 與台股表現有什麼差異？"
EPS_Q = "台積電台股和 ADR 的 EPS 差多少？"
QUESTIONS = {"adr": ADR_Q, "eps": EPS_Q}

FIELD_PATTERNS = {
    "conclusion": "一句話結論", "facts": "已知事實", "inference": "推論",
    "upside": "利多", "risk": "風險", "recommendation": "建議傾向",
    "trigger": "觸發條件", "next_event": "下一個關鍵事件",
    "tracking_indicators": "建議追蹤指標", "valuation": "估值檢查",
}

# ADR 題：回答中有「溢價」且同段（同一行或鄰近行）有百分比數字，代表確實引用了
# 系統算好的溢價率，而不是空泛提到「溢價」兩字卻沒有數字支撐。
_PREMIUM_RE = re.compile(r"溢價[^\n]{0,30}[\d.]+\s*%|[\d.]+\s*%[^\n]{0,30}溢價")

# EPS 題：模型自行套匯率或股數換算的跡象。heuristic，之後要人工複核：
#   - 31. 開頭的四位以上小數：USD/TWD 匯率的典型長相（如 31.802）
#   - × 5 / * 5 / 乘以 5 / ÷ 5 / 除以 5 / / 5：ADR 換算比例（TSM 1:5）常見的運算寫法
_FX_RE = re.compile(r"31\.\d{4,}")
_RATIO_OP_RE = re.compile(r"[×*]\s*5|\\times\s*5|乘以\s*5|[÷/]\s*5|除以\s*5")


def cites_premium(answer: str) -> bool:
    return bool(_PREMIUM_RE.search(answer))


def self_convert(answer: str) -> bool:
    return bool(_FX_RE.search(answer) or _RATIO_OP_RE.search(answer))


def count_card_fields(answer: str) -> int:
    return sum(1 for pattern in FIELD_PATTERNS.values() if pattern in answer)


async def _build_fixture_state(question: str) -> dict:
    """跑整個 compiled graph 到 generate 前一刻，回傳當時的 state 複本。

    monkeypatch generate 成丟例外是為了不改 src/graph.py 的 compile 介面
    （不加 checkpointer/interrupt_before，那是給人機互動用的，這裡單純要一份
    「generate 要吃的 state」）。例外帶著 dict(state) 複本，外面接住就有了。
    """
    import src.graph as _g

    class _Captured(Exception):
        def __init__(self, state):
            self.state = state

    def _capture_generate(state):
        raise _Captured(dict(state))

    orig_generate = _g.generate
    _g.generate = _capture_generate
    try:
        app = await _g.build_graph()
    finally:
        _g.generate = orig_generate

    initial = {
        "question": question, "history": [], "companies": [], "doc_type": None,
        "news_since_days": None, "retrieved": [], "answer": "",
        "fetched": False, "fetch_results": [], "lang": "zh", "model": "",
    }
    try:
        await app.ainvoke(initial)
        raise RuntimeError("generate 沒被呼叫到，compiled graph 流程可能變了")
    except _Captured as captured:
        state = captured.state
        # messages 是 agent<->tools 往返用的 BaseMessage 物件，不是 JSON 可序列化型別，
        # generate() 本身也不讀這欄——存 fixture 前拿掉，省得另外寫序列化/還原
        state.pop("messages", None)
        return state


def _fixture_path(q_key: str) -> Path:
    return FIXTURE_DIR / f"adr_fixture_{q_key}.json"


async def _load_or_build_fixture(q_key: str) -> dict:
    path = _fixture_path(q_key)
    if path.exists():
        return json.loads(path.read_text())
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    state = await _build_fixture_state(QUESTIONS[q_key])
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    print(f"[fixture] 已產生 {path}")
    return state


async def _run_one(q_key: str, state: dict, run_idx: int) -> dict:
    from src.graph import generate

    started = time.monotonic()
    out = generate(dict(state))
    secs = round(time.monotonic() - started, 1)
    answer = out.get("answer") or ""

    row = {
        "arm": config.ADR_PREMIUM, "q": q_key, "run": run_idx,
        "secs": secs, "chars": len(answer), "answer": answer,
        "card_fields": count_card_fields(answer),
    }
    if q_key == "adr":
        row["cites_premium"] = cites_premium(answer)
    if q_key == "eps":
        row["self_convert"] = self_convert(answer)
    return row


async def main_async(runs: int, q_arg: str) -> None:
    q_keys = ["adr", "eps"] if q_arg == "both" else [q_arg]
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    for q_key in q_keys:
        state = await _load_or_build_fixture(q_key)
        for i in range(runs):
            row = await _run_one(q_key, state, i)
            rows.append(row)
            with RESULT_PATH.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\n=== 臂：ADR_PREMIUM={config.ADR_PREMIUM} ===")
    for q_key in q_keys:
        q_rows = [r for r in rows if r["q"] == q_key]
        avg_secs = sum(r["secs"] for r in q_rows) / len(q_rows)
        print(f"\n--- {q_key}: {QUESTIONS[q_key]} ---")
        print(f"平均耗時    : {avg_secs:.1f}s（{len(q_rows)} 次）")
        if q_key == "adr":
            hits = sum(1 for r in q_rows if r["cites_premium"])
            print(f"cites_premium 命中: {hits}/{len(q_rows)}")
        if q_key == "eps":
            hits = sum(1 for r in q_rows if r["self_convert"])
            print(f"self_convert 命中 : {hits}/{len(q_rows)}")
        avg_fields = sum(r["card_fields"] for r in q_rows) / len(q_rows)
        print(f"平均卡片欄位數: {avg_fields:.1f}")

    print(f"\n結果已 append 至 {RESULT_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--q", choices=["adr", "eps", "both"], default="both")
    args = parser.parse_args()
    asyncio.run(main_async(args.runs, args.q))


if __name__ == "__main__":
    main()
