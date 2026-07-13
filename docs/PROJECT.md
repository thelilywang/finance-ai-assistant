# Project Documentation / 專案文件

[English](#english) | [中文](#中文)

---

<a id="english"></a>
## English

A local RAG assistant for stock financial reports and news, built with LangGraph + Ollama + pgvector. See also the main [README](../README.md).

### Architecture

```mermaid
flowchart TD
    U[User question] --> RW[rewrite_question]
    RW --> EF[extract_filters]
    EF --> RT[retrieve]
    RT -->|hits, company + news present| GEN[generate]
    RT -->|company hits but no news, or empty| AF[auto_fetch]
    AF --> RT
    RT -->|still empty after fetch| NR[no_result]
    GEN --> A[Answer + sources + decision card]
    NR --> B["Honest 'no data' reply + market snapshot"]

    subgraph Data pipeline
        SRC[EDGAR / MOPS / Yahoo RSS / udn+cmoney sweep] --> UP[src/update.py]
        UP --> ING[src/ingest.py: chunk + embed]
        ING --> PG[(pgvector: doc_chunks)]
    end
    PG --> RT
    YF[yfinance snapshot] -.prompt only, not stored.-> GEN
```

### LangGraph node flow

`rewrite_question → extract_filters → retrieve → (generate | auto_fetch → retrieve | no_result)`

| Node | Role |
|---|---|
| `rewrite_question` | With chat history, rewrites a follow-up ("what about margins?") into a standalone question so embedding retrieval works; passes through when history is empty |
| `extract_filters` | LLM extracts company code (TW 4-digit or US ticker) / doc type from the question as retrieval filters (null = no filter) |
| `retrieve` | Embeds the question (bge-m3) and runs cosine similarity search in pgvector, top-5; for company questions also blends in top-3 company news and top-2 global market news as decision-card context |
| `auto_fetch` | Runs once (guarded by `fetched`). If a company was named: fetches its reports + news (skipping reports if already retrieved), always also sweeps market-news (top-3, `fetch_market_news`); a company-less empty retrieval sweeps market-news too, so it never dead-ends at `no_result` on the first try. Single-source failures are swallowed, not fatal |
| `generate` | Answers strictly from retrieved chunks with `[SourceN]` citations, folds in a live yfinance market snapshot (price, 52w range, PE, target price, analyst view — prompt-only, never a citable source, degrades silently on failure), then appends a fixed decision-card section (facts w/ citations, inference, valuation, stance, triggers, key event, watch metrics) with a disclaimer; stance is only asserted when filings+news+market data support it, but triggers/key event/watch metrics are always required so the answer never abstains outright |
| `no_result` | When nothing is retrieved even after auto_fetch, honestly says so, still appending the market snapshot and watch items instead of hallucinating |

### Modules (`src/`)

| File | Purpose |
|---|---|
| `config.py` | Central settings from `.env` (DB URL, Ollama URL/models, chunking, top-k, SEC user agent) |
| `vectorstore.py` | psycopg + pgvector access layer: `insert_chunks`, `delete_by_source`, `similarity_search` |
| `ingest.py` | `ingest_text` (chunk → embed → insert, deduped by source) and `ingest_file` (PDF/txt loader); CLI `python -m src.ingest` |
| `update.py` | Manual fetchers: SEC EDGAR (US 10-K/10-Q), MOPS (TW report PDFs), Yahoo Finance RSS news, market-news sweep (udn/cmoney listing pages via trafilatura); CLI `python -m src.update` |
| `market.py` | `get_market_snapshot(company)`: live yfinance quote (price, 52w range, PE, target price, analyst view), formatted for the prompt only — any failure returns `None` and never raises |
| `graph.py` | LangGraph pipeline described above; `build_graph()` returns the compiled app |
| `cli.py` | Terminal chat (single-turn) |
| `app.py` | Chainlit web UI: token streaming, multi-turn (last 5 rounds in session memory), downloadable `.md` analysis per answer |

### DB schema (`db/init.sql`)

Single table `doc_chunks`:

```sql
id BIGSERIAL PK, source VARCHAR(512), doc_type VARCHAR(50),  -- 'financial_report' / 'news'
company VARCHAR(100), published_at DATE, chunk_index INT,
content TEXT, embedding VECTOR(1024),                        -- bge-m3 dimension
created_at TIMESTAMPTZ
```

HNSW cosine index on `embedding`, plus B-tree indexes on `company` and `doc_type`.

### Data sources & update commands

| Data | Source | Command |
|---|---|---|
| US reports | SEC EDGAR (ticker → CIK → latest 10-K/10-Q HTML, text via trafilatura) | `python -m src.update report --market us --company AAPL [--form 10-K]` |
| TW reports | TWSE MOPS (`doc.twse.com.tw/server-java/t57sb01`, two-step PDF download) | `python -m src.update report --market tw --company 2330` |
| News | Yahoo Finance RSS (`.TW` suffix auto-added for 4-digit TW codes) | `python -m src.update news --company 2330 --limit 10` |
| Market news | udn (tw/us) + cmoney (notes/tag) listing pages, article body via trafilatura; titles carrying a 4-digit TW code get auto-tagged with that company; `source_exists()` skips already-ingested articles so re-sweeping is cheap | `python -m src.update market-news [--limit 10]` |
| Live market snapshot | yfinance quote (price, 52w range, PE, target price, analyst view) — prompt-only, never stored in `doc_chunks` | n/a (fetched inline by `generate`) |
| Prune old news | Deletes news chunks older than N days (default 180); reports are never pruned | `python -m src.update prune --days 180` |

Re-running any command on the same source replaces old chunks (idempotent).

### Design decisions

- **`PGVECTOR_URL` instead of `DATABASE_URL`**: Chainlit treats `DATABASE_URL` as its own persistence-layer setting (requiring asyncpg), so the env var was renamed to avoid the collision.
- **No Google News RSS**: since 2024 its links are encoded internal URLs, so article bodies can't be fetched; Yahoo Finance RSS is used instead.
- **Idempotent ingest**: `ingest_text` deletes all chunks for the same `source` before inserting, so updates can be re-run freely without duplicates.
- **Everything local**: Ollama (qwen3.5:9b + bge-m3) keeps sensitive financial documents on-machine.
- **HNSW over IVFFlat**: the vector index is HNSW because it handles incremental inserts well (no cluster rebuild needed), matching this project's fetch-on-demand write pattern.
- **Market snapshot is prompt-only, never stored**: yfinance data is fetched fresh per question and injected into the `generate` prompt; it's excluded from `doc_chunks` and from the citation numbering since it isn't a retrievable source, and any fetch failure is caught and silently degrades to no snapshot.
- **Decision card can't fully abstain**: `generate` always includes triggers, key event, and watch metrics even with thin data, so the answer stays actionable; only the directional "stance" is gated on having filings+news+market data to back it.

### Known limitations

- **MOPS scraping is fragile**: no official API; when it breaks, the CLI prints manual download instructions instead of raising.
- **Chat history is per-session only**: kept in memory (last 5 rounds), cleared on page refresh; persist to DB if needed.
- Answer quality depends on the local model; figures should be verified against the cited sources.
- News recency filtering is a keyword heuristic ("最近", "recent", ...) that caps news at 90 days; for finer control, move the judgment into `extract_filters`.

---

<a id="中文"></a>
## 中文

以 LangGraph + Ollama + pgvector 打造的本地個股財報/新聞 RAG 助理。另見主 [README](../README.md)。

### 架構

```mermaid
flowchart TD
    U[使用者問題] --> RW[rewrite_question]
    RW --> EF[extract_filters]
    EF --> RT[retrieve]
    RT -->|有結果，公司+新聞都在| GEN[generate]
    RT -->|有公司但缺新聞，或全空| AF[auto_fetch]
    AF --> RT
    RT -->|補抓後仍無結果| NR[no_result]
    GEN --> A[回答 + 引用來源 + 決策卡]
    NR --> B[誠實告知查無資料 + 市場快照]

    subgraph 資料管線
        SRC[EDGAR / MOPS / Yahoo RSS / udn+cmoney 掃描] --> UP[src/update.py]
        UP --> ING[src/ingest.py: 切 chunk + embedding]
        ING --> PG[(pgvector: doc_chunks)]
    end
    PG --> RT
    YF[yfinance 即時快照] -.只進 prompt，不入庫.-> GEN
```

### LangGraph 節點流程

`rewrite_question → extract_filters → retrieve → (generate | auto_fetch → retrieve | no_result)`

| 節點 | 職責 |
|---|---|
| `rewrite_question` | 有對話歷史時,把追問(「那毛利率呢?」)改寫成獨立問題,讓 embedding 檢索有效;無歷史直接通過 |
| `extract_filters` | 用 LLM 從問題抽出公司代號(台股 4 碼或美股 ticker)/文件類型作為檢索 filter(null 表示不過濾) |
| `retrieve` | 問題經 bge-m3 embedding 後,在 pgvector 做 cosine 相似度檢索,取 top-5;有指名公司時再補 top-3 該公司新聞與 top-2 全域市場新聞,作為決策卡素材 |
| `auto_fetch` | 只執行一次（`fetched` 保護）。有指名公司:抓財報+新聞(已有財報就只補新聞),並一律加掃市場新聞(`fetch_market_news`, top-3);沒指名公司但檢索全空時也觸發市場新聞掃描,避免第一輪就直接舉手投降。單一來源失敗不中斷整體流程 |
| `generate` | 僅根據檢索到的 chunk 回答並標示 `[來源N]`,並併入即時 yfinance 市場快照(股價、52 週區間、本益比、目標價、分析師評等——僅供 prompt 參考,不算引用來源,失敗時靜默降級),結尾固定追加決策卡一節(附引用的事實、推論、估值、立場、觸發條件、關鍵事件、觀察指標)與免責聲明;立場只在財報+新聞+市場數據都支持時才給,但觸發條件/關鍵事件/觀察指標一律要有,回答不會整段棄權 |
| `no_result` | 補抓後仍查無資料時誠實告知,並附上市場快照與觀察項目,避免幻覺 |

### 模組說明(`src/`)

| 檔案 | 用途 |
|---|---|
| `config.py` | 集中設定,從 `.env` 讀取(DB 連線、Ollama URL/模型、chunk 參數、top-k、SEC user agent) |
| `vectorstore.py` | psycopg + pgvector 存取層:`insert_chunks`、`delete_by_source`、`similarity_search` |
| `ingest.py` | `ingest_text`(切 chunk → embedding → 寫入,依 source 去重)與 `ingest_file`(PDF/txt 載入);CLI `python -m src.ingest` |
| `update.py` | 手動抓取:SEC EDGAR(美股 10-K/10-Q)、MOPS(台股財報 PDF)、Yahoo Finance RSS 新聞、udn/cmoney 市場新聞列表頁掃描(trafilatura 抽文);CLI `python -m src.update` |
| `market.py` | `get_market_snapshot(company)`:即時 yfinance 報價(股價、52 週區間、本益比、目標價、分析師評等),僅供 prompt 使用——失敗一律回傳 `None`,不拋錯 |
| `graph.py` | 上述 LangGraph 流程;`build_graph()` 回傳編譯後的 app |
| `cli.py` | 終端聊天(單輪) |
| `app.py` | Chainlit 網頁介面:token 逐字串流、多輪對話(session 記憶體保留最近 5 輪)、每則回答附可下載 `.md` 分析檔 |

### DB schema(`db/init.sql`)

單一資料表 `doc_chunks`:

```sql
id BIGSERIAL PK, source VARCHAR(512), doc_type VARCHAR(50),  -- 'financial_report' / 'news'
company VARCHAR(100), published_at DATE, chunk_index INT,
content TEXT, embedding VECTOR(1024),                        -- bge-m3 維度
created_at TIMESTAMPTZ
```

`embedding` 上有 HNSW cosine 索引,`company` 與 `doc_type` 各有 B-tree 索引。

### 資料來源與更新指令

| 資料 | 來源 | 指令 |
|---|---|---|
| 美股財報 | SEC EDGAR(ticker → CIK → 最新 10-K/10-Q HTML,trafilatura 抽文字) | `python -m src.update report --market us --company AAPL [--form 10-K]` |
| 台股財報 | 公開資訊觀測站 MOPS(`doc.twse.com.tw/server-java/t57sb01` 兩步下載 PDF) | `python -m src.update report --market tw --company 2330` |
| 新聞 | Yahoo Finance RSS(4 碼台股代號自動加 `.TW`) | `python -m src.update news --company 2330 --limit 10` |
| 市場新聞 | udn(tw/us)+ cmoney(notes/tag)新聞列表頁,內文用 trafilatura 抽取;標題含 4 碼台股代號會自動標記該公司;`source_exists()` 跳過已入庫文章,重複掃描成本很低 | `python -m src.update market-news [--limit 10]` |
| 即時市場快照 | yfinance 報價(股價、52 週區間、本益比、目標價、分析師評等)——僅供 prompt 使用,不寫入 `doc_chunks` | 無(由 `generate` 即時抓取) |
| 清理舊新聞 | 刪除超過 N 天的新聞 chunk(預設 180 天;財報一律保留) | `python -m src.update prune --days 180` |

同一 source 重跑會先刪舊 chunk 再寫入(idempotent)。

### 設計決策

- **用 `PGVECTOR_URL` 而非 `DATABASE_URL`**:Chainlit 會把 `DATABASE_URL` 當成自己的持久化層設定(需 asyncpg),改名避免撞名。
- **不用 Google News RSS**:2024 年後其連結改為編碼過的內部網址,抓不到原文,改用 Yahoo Finance RSS。
- **Idempotent ingest**:`ingest_text` 寫入前先刪除同 `source` 的舊 chunk,更新指令可任意重跑不會重複。
- **全部本地執行**:Ollama(qwen3.5:9b + bge-m3)讓財報這類敏感資料不出本機。
- **HNSW 而非 IVFFlat**:向量索引改用 HNSW,增量寫入不需重建分群,符合本專案隨用隨抓的寫入模式。
- **市場快照只進 prompt,不入庫**:yfinance 資料每次問答即時抓取後併入 `generate` 的 prompt;不寫進 `doc_chunks`,也不計入引用編號,因為它不是可檢索的來源,抓取失敗一律靜默降級成無快照。
- **決策卡不整段棄權**:即使資料稀薄,`generate` 仍固定要求觸發條件、關鍵事件、觀察指標,讓回答保持可執行;只有方向性的「立場」需要財報+新聞+市場數據齊全才會給。

### 已知限制

- **MOPS 爬取脆弱**:無官方 API,掛掉時 CLI 會印手動下載指引而非拋錯。
- **對話歷史僅存單次 session**:記憶體保留最近 5 輪,重整即清空;需要持久化再存 DB。
- 回答品質受本地模型限制,數字請對照引用來源確認。
- 新聞時效過濾為關鍵字啟發式(「最近」「recent」等 → 只取 90 天內新聞);要更準可改由 `extract_filters` 的 LLM 判斷。
