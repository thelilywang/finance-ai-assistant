"""ADR 溢價/EPS 等值區塊的 A/B：模型是否照抄程式算好的數字，而不是自己換算。

背景：實測問「台積電台股和 ADR 的 EPS 差多少？」時，block（只有溢價區塊）與
之前的 full（溢價區塊＋例外句）兩組都是 3 次裡有 1 次讓模型自己換算 EPS，而且
兩次都算錯：block 把 27.25 TWD 換成「8.57 USD」，full 算成 4.31×31.839×5=686 TWD
（應該除以 5）。其餘幾次照規則拒絕換算，回答「無法計算差額」，等於沒答到問題。

正確答案很單純：同一季 ADR EPS ÷ 比例 × 匯率，就是每股台股的 EPS 等值。這個數字
現在由 get_adr_premium 算好交給模型（見 src/market.py 的 eps_equiv），模型只需要
照著引用。本檔新增 eps 臂驗證這件事。

三臂，同程式碼同容器，只用環境變數切換（見 src/config.ADR_PREMIUM）：
    off    不呼叫 get_adr_premium，不附溢價區塊（等同該功能不存在）
    block  附溢價區塊，不附 EPS 等值
    eps    溢價區塊再加 EPS 等值換算

10-07 block/full A/B 結果：ADR 題引用溢價率兩臂都 3/3；EPS 題人工判讀自行換算
兩臂都 1/3（皆算錯）；off 的 EPS 回答 3 次都在 119 字處斷句，原因未查（見
MAINTENANCE_LOG／程式碼追蹤，generate 本身無任何截斷邏輯，推測是模型自己提早
結束生成）。generate 是 temperature=0，同臂多次幾乎是同一份回答，--runs 只反映
即時行情的變動，不是獨立樣本，故改成多種問法而非只靠 --runs 增加樣本。

10-07 block/eps A/B（--q all --runs 1）：ADR 題兩臂都引用溢價率；EPS 三種問法
eps 臂 3/3 引用 EPS 等值（eps2 結尾把 0.7% 差距誤歸因於股價溢價），block 臂 3/3
答錯（2 次自行換算算錯、1 次拒答）。注意：當時 Ollama 以 4096 context 執行，
generate 的 prompt 被截到 2050 token（server.log "truncating input prompt"），
兩臂條件相同但結果需在修好截斷後重驗。

拿掉 self_convert：上次兩筆真的換算都漏抓，heuristic 不可靠，改由人工判讀是否
自行換算。

五題：
    adr    台積電的 ADR 與台股表現有什麼差異？——正常使用情境，預期會引用溢價區塊
    eps    台積電台股和 ADR 的 EPS 差多少？——誘發題，驗證模型是否仍自行換算 EPS
    eps2   台積電 ADR 和台股的每股盈餘誰比較高？——換個問法的誘發題
    eps3   TSM 的 EPS 換算成台股每股是多少？——換個問法的誘發題
    invest 台積電台股現在適合買進嗎？——單一公司投資題，看決策卡 card_fields 完整度
           （問句明講「台股」是刻意的：台積電雙掛牌，裸問「台積電現在適合買進嗎？」
           會被 resolve_market 判定市場不明而反問，graph 在 ask_market 就結束、
           generate 永遠不會被呼叫，fixture 建不起來——實測踩過一次才發現）

num_ctx A/B（截斷修好後，決定預設值用）：同程式碼同容器，只用
`docker exec -e OLLAMA_NUM_CTX=...` 切換（見 src/config.OLLAMA_NUM_CTX），容器
不必重啟——config 在每個新 python 程序 import 時讀環境變數。結果每列多印
num_ctx 與該次 generate 呼叫的 usage 欄位（prompt_tokens／output_tokens／
done_reason／prefill_ms／decode_ms，來自 _ollama_usage，見下方 _LastUsage）。
跑法：
    docker exec -e OLLAMA_NUM_CTX=4096  finance_ai_assistant_app \\
        python tests/bench_adr_premium.py --q adr,eps,eps2,invest --out data/bench/numctx_ab.jsonl
    docker exec -e OLLAMA_NUM_CTX=16384 finance_ai_assistant_app \\
        python tests/bench_adr_premium.py --q adr,eps,eps2,invest --out data/bench/numctx_ab.jsonl
    docker exec -e OLLAMA_NUM_CTX=32768 finance_ai_assistant_app \\
        python tests/bench_adr_premium.py --q adr,eps,eps2,invest --out data/bench/numctx_ab.jsonl
invest 題的 fixture 用 32768 建（避免 agent 階段被截斷汙染檢索結果），其餘既有
fixture（adr/eps/eps2）沿用 4096 時期建的，不重建。

10-07 num_ctx A/B 結果（data/bench/numctx_ab.jsonl，4 題 × 3 組）：
    4096   截斷 4/4、決策卡 0～1 欄、cites_source 0/4、100% GPU、SIZE 5.5 GB
    16384  截斷 0/4、決策卡 9 欄、cites_source 4/4、100% GPU、SIZE 5.9 GB
    32768  截斷 0/4、決策卡 9 欄、cites_source 4/4、100% GPU、SIZE 6.6 GB
16384 與 32768 兩組結果幾乎相同（回答內容、決策卡欄位、引用情況）。adr 題的
cites_premium 當時用舊判斷規則（要求回答裡同時出現「溢價」兩字與百分比）在
16384／32768 兩組判成 False，但回答其實寫了「高於台股現價 19.03%」這類沒有
「溢價」兩字的句子——已改成比對數值（見 cites_premium）。eps2 題的
cites_eps_equiv 是模型真的沒用 EPS 等值（直接比較 27.25 TWD 與 4.31 USD），
待改 generate 指示（不在本次範圍）。

`_llms` 用 lru_cache，key 不含 num_ctx，同一程序內切換 OLLAMA_NUM_CTX 不會重建
ChatOllama 實例；建 fixture 前後都要呼叫 `_llms.cache_clear()`。

固定 generate 之前的 state：第一次跑某題時，把 src.graph.generate monkeypatch 成
丟出帶 state 複本的例外，跑完整個 compiled graph 到 generate 前一刻為止，把 state
存成 fixture json；之後檔案存在就直接讀，不再重新檢索/跑 agent，避免這兩段的隨機性
汙染 A/B。行情仍在 generate 內即時抓（這是可以接受的，溢價率本來就該是當下算的）。

在 app container 內執行（單臂單題約數十秒到數分鐘，視模型與檢索耗時；
三臂 × 四題請留數十分鐘）：
    docker exec -e ADR_PREMIUM=off finance_ai_assistant_app \\
        python tests/bench_adr_premium.py --runs 3 --q all
    docker exec -e ADR_PREMIUM=block finance_ai_assistant_app \\
        python tests/bench_adr_premium.py --runs 3 --q all
    docker exec -e ADR_PREMIUM=eps finance_ai_assistant_app \\
        python tests/bench_adr_premium.py --runs 3 --q all

compare_rule A/B（eps2 跨幣別直接比大小的修正，見 src/config.ADR_COMPARE_RULE）：
同程式碼同容器，只用環境變數切換，各跑 eps、eps2、eps3 三題。每列多印一欄
compare_rule，供人工對照兩臂的回答原文（結論方向是否正確、有沒有引用換算值）：
    docker exec -e ADR_COMPARE_RULE=off finance_ai_assistant_app \\
        python tests/bench_adr_premium.py --q eps,eps2,eps3 --out data/bench/compare_rule_ab.jsonl
    docker exec -e ADR_COMPARE_RULE=on finance_ai_assistant_app \\
        python tests/bench_adr_premium.py --q eps,eps2,eps3 --out data/bench/compare_rule_ab.jsonl
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
from src.logging_setup import setup_logging  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "bench"
RESULT_PATH = FIXTURE_DIR / "adr_ab.jsonl"

ADR_Q = "台積電的 ADR 與台股表現有什麼差異？"
EPS_Q = "台積電台股和 ADR 的 EPS 差多少？"
EPS2_Q = "台積電 ADR 和台股的每股盈餘誰比較高？"
EPS3_Q = "台積電 ADR 的 EPS 折合成台股本股每股是多少？"
INVEST_Q = "台積電台股現在適合買進嗎？"
QUESTIONS = {"adr": ADR_Q, "eps": EPS_Q, "eps2": EPS2_Q, "eps3": EPS3_Q, "invest": INVEST_Q}
ALL_Q_KEYS = list(QUESTIONS)
# invest 的 fixture 一律用這個 num_ctx 建（見檔案開頭 num_ctx A/B 說明），
# 其餘題沿用既有 fixture，不受這個常數影響。
INVEST_FIXTURE_NUM_CTX = 32768

FIELD_PATTERNS = {
    "conclusion": "一句話結論", "facts": "已知事實", "inference": "推論",
    "upside": "利多", "risk": "風險", "recommendation": "建議傾向",
    "trigger": "觸發條件", "next_event": "下一個關鍵事件",
    "tracking_indicators": "建議追蹤指標", "valuation": "估值檢查",
}

EPS_Q_KEYS = {"eps", "eps2", "eps3"}

# ADR 題：回答裡任一「數字%」與區塊算出的溢價率（取絕對值）相差 ≤0.5 個百分點即算引用。
# 不看用詞：模型會寫「溢價 19.03%」「高於台股 19.03%」「約 19%」。0.5 只留給模型四捨五入
# 到整數（如 19.03 寫成「約 19%」）——比對值已是 generate 實際拿到的區塊，沒有行情差距。
# ponytail: 只看「有沒有一個接近溢價率的百分比」，不看那個數字在講什麼。溢價接近 0
# （漲跌幅 0.19%／0.72% 會落入 ±0.5）或接近同篇其他百分比（如營收年增 19.3%）時會
# 誤判為引用；目前只測 2330/TSM、溢價約 19%，與同篇其他百分比差很遠。換標的前要改成
# 比對數字前後的用詞。
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

# 區塊文字裡「ADR premium vs 2330: +19.03%」這一行抓出溢價率，供 cites_premium 比對。
_PREMIUM_BLOCK_RE = re.compile(r"ADR premium vs \S+: ([+-]?[\d.]+)%")

# 是否引用了 [來源N] 格式的出處編號，不管引用幾個或第幾號。
_CITATION_RE = re.compile(r"\[來源\d+\]")


def cites_source(answer: str) -> bool:
    return bool(_CITATION_RE.search(answer))

# EPS 題：區塊文字裡「… = 27.41 TWD (vs …」這一段抓出 EPS 等值的數字，供 cites_eps_equiv 比對。
_EPS_BLOCK_RE = re.compile(r"=\s*([\d.]+)\s*TWD\s*\(vs")


def cites_premium(answer: str, premium_pct: float | None) -> bool:
    """回答中是否出現與區塊算出的溢價率相近的百分比數字（見上方 _PCT_RE 註解）。

    premium_pct 為 None（off 臂沒有溢價區塊）一律回 False：沒有區塊時模型寫出的
    溢價數字只可能是自己算的，不算引用。
    """
    if premium_pct is None:
        return False
    target = abs(premium_pct)
    return any(abs(float(m) - target) <= 0.5 for m in _PCT_RE.findall(answer))


_DECIMAL_RE = re.compile(r"\d+\.\d+")


def cites_eps_equiv(answer: str, eps_equiv: float | None) -> bool:
    """回答中是否出現與區塊算出的 EPS 等值相近的小數數字。

    比對值是 generate 實際拿到的區塊（區塊印到小數兩位），0.05 容許模型四捨五入到
    小數一位（27.46 寫成 27.5、27.41 寫成 27.4）。
    """
    if eps_equiv is None:
        return False
    return any(abs(float(m) - eps_equiv) <= 0.05 for m in _DECIMAL_RE.findall(answer))


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
    if q_key == "invest":
        # invest 的 fixture 要在 agent 階段不被截斷的前提下建，否則檢索結果本身
        # 就被污染，之後所有 num_ctx 臂都在比較被污染過的檢索——固定拉高
        # config.OLLAMA_NUM_CTX 建完就還原，不影響呼叫端當下要測的 num_ctx。
        #
        # 陷阱（實測踩到）：src.graph._llms 用 lru_cache(model) 快取 ChatOllama
        # 三個實例，cache key 只有 model 名稱、不含 num_ctx。建 fixture 時把
        # num_ctx 動態調到 32768 會讓快取塞進 num_ctx=32768 的實例；還原環境變數
        # 不會讓已建好的物件重建，之後同一行程內 generate() 仍會沿用這份 32768
        # 的實例（實測現象：num_ctx=4096 跑 invest 題，prompt_tokens=5083 完全沒被
        # 截斷，server.log 也找不到對應的 truncating 行，可見送進去的 num_ctx
        # 根本不是 4096）。清快取逼下一次 _llms() 用當下的 config.OLLAMA_NUM_CTX
        # 重新建立，建完 fixture 後再清一次還原給外層呼叫端用。
        import src.graph as _g

        orig_num_ctx = config.OLLAMA_NUM_CTX
        config.OLLAMA_NUM_CTX = INVEST_FIXTURE_NUM_CTX
        _g._llms.cache_clear()
        try:
            state = await _build_fixture_state(QUESTIONS[q_key])
        finally:
            config.OLLAMA_NUM_CTX = orig_num_ctx
            _g._llms.cache_clear()
    else:
        state = await _build_fixture_state(QUESTIONS[q_key])
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    print(f"[fixture] 已產生 {path}")
    return state


def _parse_block(text: str | None) -> tuple[float | None, float | None]:
    """從溢價區塊文字抓 (premium_pct, eps_equiv)，見 _PREMIUM_BLOCK_RE / _EPS_BLOCK_RE。

    text 是 None（off 臂沒有區塊）或 regex 沒命中都回 None，不當例外處理。
    """
    if text is None:
        return None, None
    m_premium = _PREMIUM_BLOCK_RE.search(text)
    premium_pct = float(m_premium.group(1)) if m_premium else None
    m_eps = _EPS_BLOCK_RE.search(text)
    eps_equiv = float(m_eps.group(1)) if m_eps else None
    return premium_pct, eps_equiv


def _generate_capturing(state: dict) -> tuple[dict, dict, str | None]:
    """呼叫 generate，連帶拿到該次呼叫實際用到的 _ollama_usage 與溢價區塊文字。

    不改 src/：generate 內部已經呼叫 _ollama_usage(resp) 算出 usage dict、
    以及（market=both 時）呼叫 get_adr_premium 算出溢價區塊字串，兩者都沒有
    回傳給呼叫端。這裡 monkeypatch 這兩個 src.graph 模組全域名稱，讓它們照常
    運作、只是順手把回傳值記一份下來——比對值因此是模型實際看到的那份區塊，
    不是 bench 另外算一次（另算一次會有秒級行情差距）。get_adr_premium 是在
    executor 的 thread pool 裡被呼叫的，用 dict 存結果即可，不需要鎖。
    """
    import src.graph as _g

    usage: dict = {}
    block_text: dict = {"value": None}
    orig_usage = _g._ollama_usage
    orig_premium = _g.get_adr_premium

    def _wrapped_usage(msg):
        result = orig_usage(msg)
        usage.update(result)
        return result

    def _wrapped_premium(tw_code, us_code):
        text = orig_premium(tw_code, us_code)
        block_text["value"] = text
        return text

    _g._ollama_usage = _wrapped_usage
    _g.get_adr_premium = _wrapped_premium
    try:
        out = _g.generate(state)
    finally:
        _g._ollama_usage = orig_usage
        _g.get_adr_premium = orig_premium
    return out, usage, block_text["value"]


async def _run_one(q_key: str, state: dict, run_idx: int) -> dict:
    started = time.monotonic()
    out, usage, block_text = _generate_capturing(dict(state))
    secs = round(time.monotonic() - started, 1)
    answer = out.get("answer") or ""
    premium_pct, eps_equiv = _parse_block(block_text)

    row = {
        "arm": config.ADR_PREMIUM, "compare_rule": config.ADR_COMPARE_RULE,
        "num_ctx": config.OLLAMA_NUM_CTX,
        "q": q_key, "run": run_idx,
        "secs": secs, "chars": len(answer), "answer": answer,
        "card_fields": count_card_fields(answer),
        "cites_source": cites_source(answer),
        "premium_pct": premium_pct, "eps_equiv": eps_equiv,
        **usage,
    }
    if q_key == "adr":
        row["cites_premium"] = cites_premium(answer, premium_pct)
    if q_key in EPS_Q_KEYS:
        row["cites_eps_equiv"] = cites_eps_equiv(answer, eps_equiv)
    return row


async def main_async(runs: int, q_arg: str, out_path: Path) -> None:
    q_keys = ALL_Q_KEYS if q_arg == "all" else q_arg.split(",")
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    for q_key in q_keys:
        state = await _load_or_build_fixture(q_key)
        for i in range(runs):
            row = await _run_one(q_key, state, i)
            rows.append(row)
            with out_path.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\n=== 臂：ADR_PREMIUM={config.ADR_PREMIUM} "
          f"ADR_COMPARE_RULE={config.ADR_COMPARE_RULE} num_ctx={config.OLLAMA_NUM_CTX} ===")
    for q_key in q_keys:
        q_rows = [r for r in rows if r["q"] == q_key]
        avg_secs = sum(r["secs"] for r in q_rows) / len(q_rows)
        print(f"\n--- {q_key}: {QUESTIONS[q_key]} ---")
        print(f"平均耗時    : {avg_secs:.1f}s（{len(q_rows)} 次）")
        if q_key == "adr":
            hits = sum(1 for r in q_rows if r["cites_premium"])
            print(f"cites_premium 命中  : {hits}/{len(q_rows)}")
        if q_key in EPS_Q_KEYS:
            hits = sum(1 for r in q_rows if r["cites_eps_equiv"])
            print(f"cites_eps_equiv 命中: {hits}/{len(q_rows)}")
        avg_fields = sum(r["card_fields"] for r in q_rows) / len(q_rows)
        print(f"平均卡片欄位數: {avg_fields:.1f}")
        for r in q_rows:
            print(f"  run={r['run']} prompt_tokens={r.get('prompt_tokens')} "
                  f"output_tokens={r.get('output_tokens')} done_reason={r.get('done_reason')} "
                  f"prefill_ms={r.get('prefill_ms')} decode_ms={r.get('decode_ms')}")

    print(f"\n結果已 append 至 {out_path}")


def main() -> None:
    setup_logging("bench")  # bench 是 CLI 進入點，沒呼叫就只落 stderr（見專案慣例）
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--q", default="all",
                         help="題目 key（見 QUESTIONS），逗號分隔可跑多題，或 all")
    parser.add_argument("--out", type=Path, default=RESULT_PATH,
                         help="結果 jsonl 路徑，預設 data/bench/adr_ab.jsonl")
    args = parser.parse_args()
    if args.q != "all":
        bad = [k for k in args.q.split(",") if k not in QUESTIONS]
        if bad:
            parser.error(f"未知的 --q key：{bad}（可用：{ALL_Q_KEYS}）")
    asyncio.run(main_async(args.runs, args.q, args.out))


if __name__ == "__main__":
    main()
