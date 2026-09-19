"""extract_filters 抽取正確率評估：固定答案題組，逐欄比對，不需 LLM 評分。

換小模型的驗收不能只看耗時。抽錯代號的代價是整條流程查錯公司——prompt 裡那張
對照表存在的原因,正是 9b 都會把「南茂科技」填成 2306（正確 8150）。所以這支
逐欄算正確率,讓「省下 N 秒」與「代號錯 M 題」能放在同一張表上比較。

各欄代價不對稱,故分開報而非合成單一分數：
  companies    抽錯 → 整條流程查錯公司,最嚴重
  in_scope     誤判 false → 正常問題直接被拒答
  market       誤填（該 null 卻猜一個）→ 觸發不必要的反問或查錯市場
  answer_shape 誤判 news → 投資題失去估值素材
  news_since_days 誤填 → 查空或撈進過舊資料

題組的 answer_shape 在 in_scope=false 的題目上為 null,不納入計分——問題已被判
出範疇,後續不會用到該欄。

用 FILTERS_MODEL 切換臂,其餘條件不動（同程式碼、同容器、temperature=0）：
    docker exec finance_ai_assistant_app python tests/eval_extract_filters.py
    docker exec -e FILTERS_MODEL=<候選模型> finance_ai_assistant_app \
        python tests/eval_extract_filters.py
"""
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.graph import extract_filters

ANNOTATIONS = Path(__file__).parent / "eval_data" / "extract_filters_annotations.json"

# 逐欄比對的欄位。news_since_days 只在題目有標注時計分（多數題目不涉及時效窗,
# 全部當成 None 比對會讓這欄的分母灌水成 22 題而稀釋掉真正的三題差異）。
FIELDS = ["companies", "market", "in_scope", "answer_shape", "news_since_days"]


def expected(item, field):
    """題目對某欄的標準答案；回 (有沒有標注, 答案)。"""
    if field == "news_since_days":
        return (field in item), item.get(field)
    if field == "answer_shape" and item.get("answer_shape") is None:
        return False, None  # 範疇外題目不計分
    return True, item.get(field)


def run_one(item, model):
    """跑單題,回 (實得 dict, 秒數)。抽取失敗時 graph 會降級成不過濾,照樣比對。"""
    state = {"question": item["question"], "history": [], "companies": [],
             "market": None, "model": model}
    started = time.monotonic()
    out = extract_filters(dict(state))
    elapsed = time.monotonic() - started
    return {f: out.get(f) for f in FIELDS}, elapsed


def main():
    items = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))
    # 記下實際跑的模型：兩臂的輸出要能事後分辨,否則量出「沒有差異」也無從查證
    arm = config.FILTERS_MODEL or config.LLM_MODEL
    print(json.dumps({"arm_FILTERS_MODEL": config.FILTERS_MODEL or "(沿用主模型)",
                      "實際模型": arm, "題數": len(items)}, ensure_ascii=False))
    print("=" * 72)

    per_field = defaultdict(lambda: [0, 0])   # field -> [對, 總]
    per_cat = defaultdict(lambda: [0, 0])     # category -> [全欄皆對, 總]
    failures = []
    times = []

    for item in items:
        got, elapsed = run_one(item, arm)
        times.append(elapsed)
        wrong = []
        for field in FIELDS:
            scored, want = expected(item, field)
            if not scored:
                continue
            per_field[field][1] += 1
            if got[field] == want:
                per_field[field][0] += 1
            else:
                wrong.append(f"{field}: 得 {got[field]!r} 預期 {want!r}")
        per_cat[item["category"]][1] += 1
        per_cat[item["category"]][0] += int(not wrong)
        if wrong:
            failures.append((item, wrong))
        print(f"[{'PASS' if not wrong else 'FAIL'}] {item['id']}  {item['category']}"
              f"  {elapsed:.1f}s")
        print(f"       Q: {item['question']}")
        if wrong:
            for w in wrong:
                print(f"       ✗ {w}")

    print("=" * 72 + "\n逐欄正確率（代價不對稱,分開看）：")
    for field in FIELDS:
        p, n = per_field[field]
        if n:
            print(f"  {p}/{n}  {p / n:5.1%}  {field}")

    print("\n依 category 全欄皆對：")
    for cat, (p, n) in per_cat.items():
        print(f"  {p}/{n}  {'█' * p}{'░' * (n - p)}  {cat}")

    total = sum(1 for _ in items)
    allright = sum(p for p, _ in per_cat.values())
    times.sort()
    print(f"\n全欄皆對 {allright}/{total}")
    print(f"單題耗時 中位數 {times[len(times) // 2]:.1f}s"
          f"／最快 {times[0]:.1f}s／最慢 {times[-1]:.1f}s／總計 {sum(times):.1f}s")

    if failures:
        print("\nFAIL 清單：")
        for item, wrong in failures:
            print(f"  {item['id']} ({item['category']}) {item['question']}")
            for w in wrong:
                print(f"      {w}")
            if item.get("note"):
                print(f"      註：{item['note']}")


if __name__ == "__main__":
    main()
