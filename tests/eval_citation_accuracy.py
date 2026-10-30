"""答案層引用正確率：回答裡帶 [來源N] 的句子，句中數字是否真的出自來源 N。

check_answer_format 只驗格式（編號越界、有來源卻沒引用），不看 [來源3] 的內容撐不撐得起
那句話；這支補上這一層。題目沿用 retrieval_golden.json，每題跑完整 graph（含 agent 與
generate），存下回答與當時的來源清單（順序即引用編號），再逐句比對。

判讀不用 LLM：同一個 9B 模型批改自己的回答不可信，財報題的事實又以數字為主，規則比對
可重現。每個「引用句 × 數字」歸為：
  supported   數字出現在被引用的來源（句中引多個來源時任一個有即可）
  misattrib   不在被引用的來源，但在本題另一個來源裡——引錯號
  not_found   不在任何編號來源——幻覺、單位換算（億 vs thousands）或取自行情區塊，需人工看
句中沒有可比對數字的引用句只計數，列出供人工抽查。

指標：引用精確率 = supported ÷ (supported + misattrib + not_found)。

DB 未對 host 開 port，需在 app container 內執行（每題 5～8 分鐘，全跑約 3 小時）：
    docker exec finance_ai_assistant_app python tests/eval_citation_accuracy.py --ids G01,G04
    docker exec finance_ai_assistant_app python tests/eval_citation_accuracy.py --out data/bench/citation.jsonl
改判讀規則後不必重跑生成：
    docker exec finance_ai_assistant_app python tests/eval_citation_accuracy.py --score-only data/bench/citation.jsonl
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.graph import build_graph, unique_sources
from src.i18n import detect_question_lang, t

GOLDEN = Path(__file__).parent / "eval_data" / "retrieval_golden.json"
# 台積電雙掛牌，裸問會被 resolve_market 反問、走不到 generate；問句補上市場（不改 golden set 本身）
QUESTION_OVERRIDE = {"G20": "台積電台股每股盈餘多少？", "G21": "台積電台股購置不動產、廠房及設備花了多少？"}

_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(億)?")
# 年份、季別、單一位數整數太容易巧合命中，不納入比對
_TRIVIAL_RE = re.compile(r"(19|20)\d\d|\d")
# 日期整段先拿掉，否則「6 月 27 日」的 27、「06-30」的 30 會被當成數字比對
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}\s*月\s*\d{1,2}\s*日|\d+\s*年")


def _norm(s: str) -> str:
    return s.replace(",", "")


def citation_re(lang: str) -> re.Pattern:
    # 也接受同一括號引多個來源：[Source 1, Source 4]、【來源1、來源3】
    label = re.escape(t(lang, "citation_label").strip())
    return re.compile(rf"[\[【]{label}\s*\d+(?:\s*[,，、]\s*(?:{label})?\s*\d+)*[\]】]")


def cited_refs(sentence: str, cite: re.Pattern) -> set[int]:
    return {int(n) for m in cite.finditer(sentence) for n in re.findall(r"\d+", m.group())}


def _fmt(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".")


def numbers(sentence: str, cite: re.Pattern) -> dict[str, set[str]]:
    """句中數字 → 比對時可接受的寫法。中文回答把英文來源的 billion/million 換成「億」，
    307.4 億 在來源裡是 30.74 billion 或 30,740 million，三種都算。"""
    text = _DATE_RE.sub(" ", cite.sub(" ", sentence))
    out = {}
    for m in _NUM_RE.finditer(text):
        num = _norm(m.group(1)).rstrip(".")
        if _TRIVIAL_RE.fullmatch(num):
            continue
        variants = {num}
        if m.group(2):
            variants |= {_fmt(float(num) / 10), _fmt(float(num) * 100)}
        out[num + (m.group(2) or "")] = variants
    return out


def _in(variants: set[str], content: str) -> bool:
    # 前後不得緊接數字，避免 12 命中 312；1.50 與 1.5 視為同值
    variants = variants | {v.rstrip("0").rstrip(".") for v in variants if "." in v}
    return any(re.search(rf"(?<![\d.]){re.escape(v)}(?![\d])", content) for v in variants)


def score_record(rec: dict) -> dict:
    cite = citation_re(rec["lang"])
    contents = [_norm(c) for c in rec["sources"]]
    counts = {"supported": 0, "misattrib": 0, "not_found": 0}
    issues, no_number = [], []
    for sentence in re.split(r"[\n。；;]|(?<=[.!?])\s", rec["answer"]):
        refs = {n for n in cited_refs(sentence, cite) if 1 <= n <= len(contents)}
        if not refs:
            continue
        nums = numbers(sentence, cite)
        if not nums:
            no_number.append(sentence.strip())
            continue
        for num, variants in nums.items():
            if any(_in(variants, contents[r - 1]) for r in refs):
                counts["supported"] += 1
                continue
            other = [i + 1 for i, c in enumerate(contents) if i + 1 not in refs and _in(variants, c)]
            kind = "misattrib" if other else "not_found"
            counts[kind] += 1
            issues.append({"kind": kind, "num": num, "refs": sorted(refs), "in": other,
                           "sentence": sentence.strip()[:160]})
    return {**counts, "issues": issues, "no_number": no_number,
            "cited": bool(cite.search(rec["answer"]))}


async def run_one(app, item: dict) -> dict:
    question = QUESTION_OVERRIDE.get(item["id"], item["question"])
    lang = detect_question_lang(question) or "zh"
    state = {
        "question": question, "history": [], "companies": [], "doc_type": None,
        "news_since_days": None, "retrieved": [], "answer": "", "fetched": False,
        "fetch_results": [], "messages": [], "lang": lang, "model": config.LLM_MODEL,
    }
    started = time.monotonic()
    final = await app.ainvoke(state)
    retrieved = final.get("retrieved") or []
    ordered = unique_sources(retrieved)
    return {
        "id": item["id"], "question": question, "lang": lang, "answer": final.get("answer", ""),
        "source_ids": ordered,
        "sources": ["\n".join(d["content"] for d in retrieved if d["source"] == s) for s in ordered],
        "elapsed_s": round(time.monotonic() - started, 1),
    }


def report(records: list[dict]) -> None:
    total = {"supported": 0, "misattrib": 0, "not_found": 0}
    no_number = no_cite = skipped = 0
    for rec in records:
        if not rec["sources"]:
            skipped += 1
            print(f"\n{rec['id']} 無檢索來源（未走到 generate），略過：{rec['answer'][:60]}")
            continue
        s = score_record(rec)
        for k in total:
            total[k] += s[k]
        no_number += len(s["no_number"])
        no_cite += not s["cited"]
        print(f"\n{rec['id']} 來源 {len(rec['sources'])}  支持 {s['supported']}  引錯號 {s['misattrib']}"
              f"  找不到 {s['not_found']}  無數字引用句 {len(s['no_number'])}  {rec['question']}")
        for i in s["issues"]:
            where = f"實際在 {i['in']}" if i["in"] else "不在任何來源"
            print(f"    [{i['kind']}] {i['num']} 引 {i['refs']}，{where}｜{i['sentence']}")
    judged = sum(total.values())
    n = len(records) - skipped
    print(f"\n共 {n} 題（略過 {skipped}），整份回答無任何引用 {no_cite} 題")
    print(f"數字引用 {judged} 筆：支持 {total['supported']}  引錯號 {total['misattrib']}  找不到 {total['not_found']}")
    if judged:
        print(f"引用精確率 {total['supported'] / judged:.0%}（找不到的需人工判讀是否為單位換算或行情數字）")
    print(f"無數字的引用句 {no_number} 句，未判讀")


async def main_async(ids: set[str] | None, out: Path | None) -> None:
    items = [i for i in json.loads(GOLDEN.read_text()) if not ids or i["id"] in ids]
    app = await build_graph()
    records = []
    for item in items:
        rec = await run_one(app, item)
        print(f"[{rec['id']}] {rec['elapsed_s']}s 來源 {len(rec['sources'])}", flush=True)
        records.append(rec)
        if out:
            with out.open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    report(records)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ids", help="逗號分隔的題號，預設全跑")
    p.add_argument("--out", type=Path, help="逐題附加寫入 jsonl，中斷後已跑的題目不會遺失")
    p.add_argument("--score-only", type=Path, help="只重新判讀既有 jsonl，不跑生成")
    args = p.parse_args()
    if args.score_only:
        report([json.loads(line) for line in args.score_only.read_text().splitlines() if line.strip()])
        return
    ids = set(args.ids.split(",")) if args.ids else None
    asyncio.run(main_async(ids, args.out))


if __name__ == "__main__":
    main()
