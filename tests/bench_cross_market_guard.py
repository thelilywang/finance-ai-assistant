"""跨市場素材防線的 A/B：規則掛在哪一欄才有效、代價多少。

檢索層上線 market 過濾後，跨市場素材已經進不到 generate（實測外洩 0 筆），
但留一層防線仍有價值。問題在掛的位置：專案兩次實測都顯示往共用規則區
（trend_rules_common）堆約束會擠掉欄位本職（09-09 字數約束、09-18 幣別約束）。

三臂，同程式碼同容器，只用環境變數切換：
    off     不加（純檢索層防護）
    facts   只加在「已知事實」欄（唯一直接引用檢索素材、必附 [來源N] 的欄位）
    common  加在共用規則區（原階段 5 的作法）

素材是**刻意注入的跨市場資料**：問美股卻只餵台股文件。檢索層已經不會這樣餵了，
但要驗的正是「萬一餵進來，模型擋不擋得住」，故直接組 state 繞過檢索。

量三件事：
    擋住      回答有沒有點明素材市場不符（防線有沒有生效）
    幻覺      有沒有把台股數字當成美股答案寫進去（沒擋住的代價）
    欄位完整  該有的欄位有沒有因為多一條約束而消失（堆約束的代價）

在 app container 內執行（單臂約 3-5 分鐘，三臂請留 15 分鐘）：
    docker exec -e CROSS_MARKET_GUARD=off finance_ai_assistant_app \\
        python tests/bench_cross_market_guard.py
"""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.graph import allowed_fields, generate

# 問句是美股，素材全是台股——檢索層修好後不會再發生，這裡刻意注入來驗最後一道防線
QUESTION = "美股醫藥有無其他建議投資標的？建議操作如何？"

TW_DOCS = [
    {"id": 9001, "source": "https://money.udn.com/money/story/5607/9999001",
     "title": "台股量能回溫 類股輪動推動指數震盪盤堅 | 產業熱點 | 產業 | 經濟日報",
     "doc_type": "news", "company": None, "market": "tw", "published_at": "2026-09-19",
     "content": "台股加權指數今日收在 46,164.72 點，上漲 312 點。法人建議現階段持有"
                "40~50% 現金水位，等待 FOMC 利率決議後再行布局。台股十年期公債殖利率"
                "來到 1.62%，資金面仍偏寬鬆。生技類股中，保瑞（6472）上漲 3.2%。"},
    {"id": 9002, "source": "https://www.cmoney.tw/notes/note-detail.aspx?nid=9999002",
     "title": "台股短線操作難度高 外資賣超集中電子權值",
     "doc_type": "news", "company": None, "market": "tw", "published_at": "2026-09-20",
     "content": "外資連續三日賣超台股，累計賣超 913 億元。分析師指出台股短線操作難度高，"
                "建議降低持股水位至五成以下。台灣生技醫療指數今年以來上漲 12.4%。"},
]

FIELD_PATTERNS = {
    "conclusion": "一句話結論", "facts": "已知事實", "inference": "推論",
    "upside": "利多", "risk": "風險", "recommendation": "建議傾向",
    "trigger": "觸發條件", "next_event": "下一個關鍵事件",
    "tracking_indicators": "建議追蹤指標",
}

# 台股素材裡的數字：出現在回答中即代表被當成美股答案用了
TW_NUMBERS = ["46,164.72", "46164.72", "913", "1.62", "12.4", "6472", "3.2"]

# 點明素材市場不符的說法
GUARD_HITS = ["無美股", "無對應", "沒有美股", "非美股", "台股資料", "不符", "參考資料中無"]


def run_once() -> dict:
    state = {
        "question": QUESTION, "lang": "zh", "companies": [], "market": "us",
        "answer_shape": "full", "retrieved": TW_DOCS, "history": [],
        "market_snapshots": [], "messages": [],
    }
    started = time.monotonic()
    out = generate(dict(state))
    elapsed = time.monotonic() - started
    answer = out.get("answer") or ""

    want = allowed_fields(state, has_market=False)
    present = [f for f in want if FIELD_PATTERNS.get(f, f) in answer]
    leaked = [n for n in TW_NUMBERS if n in answer]
    guarded = [g for g in GUARD_HITS if g in answer]

    return {
        "secs": round(elapsed, 1), "chars": len(answer),
        "fields": f"{len(present)}/{len(want)}",
        "missing": [f for f in want if f not in present],
        "leaked": leaked, "guarded": bool(guarded),
        "answer": answer,
    }


def main() -> None:
    arm = config.CROSS_MARKET_GUARD
    print(f"=== 臂：CROSS_MARKET_GUARD={arm} ===")
    print(f"問句（美股）：{QUESTION}")
    print(f"素材：{len(TW_DOCS)} 筆台股文件（刻意注入的跨市場素材）\n")

    r = run_once()
    print(f"耗時      : {r['secs']}s")
    print(f"字數      : {r['chars']}")
    print(f"欄位完整  : {r['fields']}" + (f"  缺：{r['missing']}" if r["missing"] else ""))
    print(f"擋住      : {'是' if r['guarded'] else '否'}")
    print(f"台股數字外洩: {r['leaked'] or '無'}")
    print("\n--- 回答 ---")
    print(r["answer"])


if __name__ == "__main__":
    main()
