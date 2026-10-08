"""多輪對話的市場一致性評估：問美股不該撈回台股資料。

與既有兩支 eval 的差別：
  eval_extract_filters.py  單句進、逐欄比對，state 寫死 history=[]
  eval_rag_retrieval.py    直接把 company 當輸入餵給檢索，不經過改寫與抽取
兩支都測不到「第二輪追問」這條路，而正式環境的失誤正是在那裡發生的
（問「美股醫藥有無其他建議標的」回了整篇台股大盤）。

本支串起 rewrite_question -> extract_filters -> retrieve_context 三段，
判準是**回傳文件的市場分佈**：問句市場為 X 時不得出現非 X 的文件。
不跑 generate——單題 200s+，而要驗的是送進去的素材，generate 只是下游表現。

market 欄現在還沒接進檢索層（similarity_search 無此參數），所以本支上線時
預期是紅燈，那就是基線；接上之後重跑，轉綠才算修好。

在 app container 內執行：
    docker exec finance_ai_assistant_app python tests/eval_multiturn_market.py
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import graph
from src.tickers import is_tw_ticker

ANNOTATIONS = Path(__file__).parent / "eval_data" / "multiturn_annotations.json"

# 市場新聞的 company 為 NULL，推不出市場。檢索端已不再補市場新聞，帶 market 的
# 檢索也會排除市場不明的塊，所以 unknown 配額為 0——出現就是 M1 失誤的形狀。
UNKNOWN_BUDGET = 0


def market_of(doc) -> str:
    """文件的市場別：優先讀 market 欄，欄位為 NULL 才回 unknown。

    刻意不從 company 推——市場新聞的 company 本來就是 NULL，用推的會把已經標好
    市場的市場新聞一律算成 unknown，明明擋對了卻報成失分（實測 M5／M9 就是這樣
    誤判的）。market 欄是寫入端標記的單一事實來源，這裡照讀即可。
    """
    market = doc.get("market")
    if market in ("tw", "us"):
        return market
    # 欄位留白時退回代號推定，讓上線前的舊塊仍看得出歸屬
    company = doc.get("company")
    if company:
        return "tw" if is_tw_ticker(company) else "us"
    return "unknown"


def run_one(item):
    """跑改寫→抽取→檢索，回 (改寫後問句, filters, 文件清單)。"""
    history = [tuple(h) for h in item["history"]]
    state = {"question": item["question"], "history": history,
             "companies": [], "market": None}

    rewritten = graph.rewrite_question(dict(state))["question"] if history else item["question"]

    filters = graph.extract_filters({**state, "question": rewritten})
    # resolve_market 不可略過：雙掛牌選了美股時，company 要由 2330 對齊成 TSM。
    # 少了這一步，company=2330 配上 market=us 是互相矛盾的條件，會過濾出零筆
    # ——那是題組跳過節點造成的假失分，不是檢索層的問題。
    # 反問回答那兩題（「美股」「都要」）的市場是使用者按按鈕確認的，問句本身沒有
    # 市場字樣；不帶 market_confirmed 的話 resolve_market 會把它校正回 None 而再問一次。
    resolved = graph.resolve_market({
        **filters, "question": rewritten,
        "market_confirmed": item["category"] == "反問回答",
    })
    company = (resolved.get("companies") or [None])[0]
    kw = dict(doc_type=filters.get("doc_type"), news_since_days=filters.get("news_since_days"))

    # 「都要」的雙掛牌要兩邊各查一次：兩市場的資料掛在不同 company（2330／TSM），
    # 一次檢索只查得到一邊。正式流程是 _seed_prompt 指示 agent 分兩次呼叫，這裡
    # 直接打 retrieve_context，故自行展開成兩次——否則測到的是「少查一邊」而非市場過濾。
    if resolved.get("market") == "both" and resolved.get("peer_company"):
        docs = []
        for co in (company, resolved["peer_company"]):
            docs += graph.retrieve_context(rewritten, co, **kw)
        return rewritten, resolved, docs

    docs = graph.retrieve_context(rewritten, company, market=resolved.get("market"), **kw)
    return rewritten, resolved, docs


def check(item, rewritten, filters, docs):
    """判市場一致性；回 (通過與否, 說明)。"""
    if not docs:
        return False, "檢索回傳 0 筆"

    tally = Counter(market_of(d) for d in docs)
    want = item["market"]

    if want == "both":
        # 唯一要求兩邊同時出現的情境，任一邊掛零即失敗
        if tally["tw"] and tally["us"]:
            return True, f"台美兩邊都有：{dict(tally)}"
        missing = "台股" if not tally["tw"] else "美股"
        return False, f"「都要」但{missing}掛零：{dict(tally)}"

    wrong = "tw" if want == "us" else "us"
    if tally[wrong]:
        titles = [(d.get("title") or "")[:40] for d in docs if market_of(d) == wrong]
        return False, f"問{want}卻回了 {tally[wrong]} 筆{wrong}文件：{titles}"

    if tally["unknown"] > UNKNOWN_BUDGET:
        return False, (f"unknown（市場新聞）{tally['unknown']} 筆，超過配額 {UNKNOWN_BUDGET}；"
                       f"主檢索僅 {tally[want]} 筆")

    # 主體延續類另外要求命中指定公司——市場對了但查錯家仍是失敗
    if (co := item.get("company")) and not any(d.get("company") == co for d in docs):
        got = sorted({d.get("company") for d in docs})
        return False, f"市場正確但未命中 {co}，實得 {got}"

    return True, f"市場一致：{dict(tally)}"


def main():
    items = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))
    print(f"共 {len(items)} 題，unknown 配額 {UNKNOWN_BUDGET} 筆\n" + "=" * 72)
    by_cat = defaultdict(lambda: [0, 0])
    failures = []

    for item in items:
        rewritten, filters, docs = run_one(item)
        ok, detail = check(item, rewritten, filters, docs)
        by_cat[item["category"]][1] += 1
        by_cat[item["category"]][0] += int(ok)
        if not ok:
            failures.append((item, detail))

        print(f"[{'PASS' if ok else 'FAIL'}] {item['id']}  {item['category']}")
        print(f"       原問句: {item['question']}")
        if rewritten != item["question"]:
            print(f"       改寫後: {rewritten}")
        print(f"       抽取: companies={filters.get('companies')} "
              f"market={filters.get('market')} doc_type={filters.get('doc_type')}")
        print(f"       期望市場: {item['market']}　回傳 {len(docs)} 筆: "
              f"{dict(Counter(market_of(d) for d in docs))}")
        for d in docs:
            print(f"         [{market_of(d):7}] {(d.get('title') or '')[:58]}")
        print(f"       判定: {detail}\n")

    print("=" * 72 + "\n依 category 通過率：")
    for cat, (p, n) in by_cat.items():
        print(f"  {p}/{n}  {'█' * p}{'░' * (n - p)}  {cat}")
    total = sum(p for p, _ in by_cat.values())
    print(f"\n總計 {total}/{len(items)}")
    if failures:
        print("\nFAIL 清單：")
        for item, detail in failures:
            print(f"  {item['id']} ({item['category']}): {detail}")


if __name__ == "__main__":
    main()
