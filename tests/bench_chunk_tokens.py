"""chunk 長度的 token 分佈量測：現行字元切法對中英文到底吃掉幾個 token。

`CHUNK_SIZE=800` 是字元，但 embedding 吃的是 token。中文與英文的字元／token 比
差三倍以上，所以同一個 800 對兩邊語意不同——這支就是把那個落差量出來，讓候選值
有實測依據可選，而不是照抄別人的數字（專案慣例：效能參數不接受純推導）。

兩份報表：
  A. 現況——庫裡既有 chunk 的 token 分佈，依 CJK 比例分中英文兩組。
  B. 候選值——用不同 CHUNK_SIZE／CHUNK_UNIT 重切同一份語料，看塊數與 token 分佈。
     只在記憶體裡切，不寫庫、不跑 embedding。

token 一律用 embedding 模型自己的 tokenizer 算（config.CHUNK_TOKENIZERS）；
實測與 Ollama 回報的 prompt_eval_count 完全相符（中英文皆是），故可當準。

DB 在 container 內，需在 app container 執行：
    docker exec finance_ai_assistant_app python tests/bench_chunk_tokens.py
"""
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, ingest
from src.vectorstore import get_connection

# bge-m3 的 context 上限；超過就會被截斷，等於那塊的尾巴沒進到向量裡
CONTEXT_LIMIT = 8192
# CJK 字元佔比超過此值視為中文塊。財報中英夾雜，用比例而非「有沒有」才分得開
CJK_RATIO = 0.15
SAMPLE_SIZE = 400


def cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    return len(re.findall(r"[一-鿿]", text)) / len(text)


def describe(name: str, values: list[int], unit: str = "") -> None:
    if not values:
        print(f"  {name:<10} （無樣本）")
        return
    s = sorted(values)
    p90 = s[min(int(len(s) * 0.9), len(s) - 1)]
    print(f"  {name:<10} n={len(s):<5} 中位={statistics.median(s):<7.0f}"
          f" p90={p90:<7} max={max(s):<7}{unit}")


def fetch_sample() -> list[tuple[str, str]]:
    """回 [(doc_type, content)]；取夠長的塊才看得出上限是否在咬。"""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT doc_type, content FROM doc_chunks"
            " WHERE content <> '' ORDER BY random() LIMIT %s",
            (SAMPLE_SIZE,),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


def main() -> None:
    count = ingest._token_counter()
    if count is None:
        print(f"！取不到 {config.EMBEDDING_MODEL} 的 tokenizer，token 數無法計算。")
        print("  需 pip install tokenizers，且該模型已登記於 config.CHUNK_TOKENIZERS。")
        return

    rows = fetch_sample()
    if not rows:
        print("！庫內無資料，先匯入再跑。")
        return

    print(f"\n=== A. 現況：庫內既有 chunk（樣本 {len(rows)}，"
          f"切法 CHUNK_UNIT={config.CHUNK_UNIT} CHUNK_SIZE={config.CHUNK_SIZE}）===")
    groups: dict[str, list[tuple[int, int]]] = {"中文": [], "英文": []}
    for doc_type, content in rows:
        lang = "中文" if cjk_ratio(content) > CJK_RATIO else "英文"
        groups[lang].append((len(content), count(content)))

    for lang, pairs in groups.items():
        if not pairs:
            print(f"\n[{lang}] （無樣本）")
            continue
        chars = [c for c, _ in pairs]
        toks = [t for _, t in pairs]
        ratios = [c / t for c, t in pairs if t]
        print(f"\n[{lang}]")
        describe("字元", chars)
        describe("token", toks)
        print(f"  {'字元/token':<10} 中位={statistics.median(ratios):.2f}")
        over = sum(1 for t in toks if t > CONTEXT_LIMIT)
        if over:
            print(f"  ！{over} 塊超過 {CONTEXT_LIMIT} token 上限，尾端會被截斷")

    zh = [r for r in groups["中文"] if r[1]]
    en = [r for r in groups["英文"] if r[1]]
    if zh and en:
        rz = statistics.median(c / t for c, t in zh)
        re_ = statistics.median(c / t for c, t in en)
        print(f"\n→ 中英文字元/token 相差 {max(rz, re_) / min(rz, re_):.1f} 倍"
              f"：同一個 CHUNK_SIZE={config.CHUNK_SIZE} 字元，"
              f"中文約 {config.CHUNK_SIZE / rz:.0f} token、英文約 {config.CHUNK_SIZE / re_:.0f} token")

    # --- B. 候選值 ---
    print("\n=== B. 候選值重切（僅記憶體，不寫庫）===")
    corpus: dict[str, str] = {}
    for lang in ("中文", "英文"):
        want_cjk = lang == "中文"
        texts = [c for _, c in rows if (cjk_ratio(c) > CJK_RATIO) is want_cjk]
        corpus[lang] = "\n\n".join(texts)
    orig = (config.CHUNK_UNIT, config.CHUNK_SIZE, config.CHUNK_OVERLAP)
    try:
        for unit, size, overlap in [
            ("char", 800, 120),   # 現行
            ("token", 384, 50),
            ("token", 600, 75),
            ("token", 900, 100),
        ]:
            config.CHUNK_UNIT, config.CHUNK_SIZE, config.CHUNK_OVERLAP = unit, size, overlap
            ingest._token_counter.cache_clear()
            print(f"\n[{unit} size={size} overlap={overlap}]")
            for lang, text in corpus.items():
                if not text.strip():
                    continue
                pieces = ingest.chunk_text(text)
                describe(lang, [count(p) for p in pieces], unit=" token/塊")
    finally:
        config.CHUNK_UNIT, config.CHUNK_SIZE, config.CHUNK_OVERLAP = orig
        ingest._token_counter.cache_clear()

    print("\n候選值選定後才需重灌全庫；本腳本不改任何資料。")


if __name__ == "__main__":
    main()
