# finance-ai-assistant

[English](#english) | [中文](#中文)

---

<a id="english"></a>
## English

A financial report & news RAG assistant for individual stocks, built with LangGraph + Ollama (local LLM) + pgvector. All inference runs on your machine — sensitive financial data never leaves it.

### Features

- **Q&A over reports and news** with source citations, plus an investment manager's trend view (with disclaimer) at the end of each answer
- **One-command data updates**: SEC EDGAR (US reports), TWSE MOPS (TW reports), Yahoo Finance RSS (news); idempotent re-runs
- **Auto-fetch on demand**: ask about a company not yet in the DB and it fetches its data automatically (listed companies only)
- **Chainlit web UI**: ChatGPT-style token streaming, multi-turn chat, downloadable `.md` analysis per answer
- **Honest no-result path**: says "no data" instead of hallucinating

Full documentation: [docs/PROJECT.md](docs/PROJECT.md)

### Quickstart

Requirements: Python 3.10+, Docker, [Ollama](https://ollama.com).

```bash
# 1. Ollama models
ollama pull qwen3.5:9b     # LLM
ollama pull bge-m3         # embeddings (multilingual)

# 2. Database (Postgres + pgvector)
docker compose up -d

# 3. Python env
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # uses PGVECTOR_URL for the DB connection

# 4. Fetch some data
python -m src.update report --market us --company AAPL
python -m src.update news --company 2330 --limit 10

# 5. Chat
chainlit run src/app.py -w    # http://localhost:8000
```

### Commands

| Command | What it does |
|---|---|
| `python -m src.update report --market us --company AAPL [--form 10-K]` | Fetch latest US filing from SEC EDGAR (default 10-Q) |
| `python -m src.update report --market tw --company 2330` | Fetch latest TW report PDF from MOPS (prints manual steps if blocked) |
| `python -m src.update news --company 2330 --limit 10` | Fetch news via Yahoo Finance RSS |
| `python -m src.update prune --days 180` | Delete news chunks older than N days (reports are never pruned) |
| `python -m src.ingest --file data/x.pdf --company 2330 --doc-type financial_report --date 2026-07-15` | Import a local PDF/txt manually |
| `python -m src.cli` | Terminal chat (single-turn) |
| `chainlit run src/app.py -w` | Web chat UI at http://localhost:8000 |

---

<a id="中文"></a>
## 中文

針對個股的財報/新聞 RAG 問答助理,用 LangGraph + Ollama(本地 LLM)+ pgvector 打造。
所有推理都在本機跑,資料不會送到外部 API,適合處理財報這類敏感資料。

### 功能

- **財報/新聞問答**:回答附引用來源,結尾附投資經理人趨勢觀點(含免責聲明,非投資建議)
- **一鍵抓取更新**:SEC EDGAR(美股財報)、公開資訊觀測站 MOPS(台股財報)、Yahoo Finance RSS(新聞);重跑同一來源自動去重
- **自動抓取**:問到未匯入的公司會自動抓取其財報/新聞(僅限上市公司)
- **Chainlit 網頁介面**:ChatGPT 風格逐字串流、多輪對話、每則回答附可下載 `.md` 分析檔
- **查無資料時誠實告知**,不幻覺

完整文件:[docs/PROJECT.md](docs/PROJECT.md)

### 快速開始

環境需求:Python 3.10+、Docker、[Ollama](https://ollama.com)。

```bash
# 1. 安裝 Ollama 模型
ollama pull qwen3.5:9b     # 生成用的 LLM
ollama pull bge-m3         # embedding 模型(支援中文)

# 2. 啟動資料庫(Postgres + pgvector)
docker compose up -d

# 3. Python 環境
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # DB 連線用 PGVECTOR_URL(避免與 chainlit 的 DATABASE_URL 撞名)

# 4. 抓資料
python -m src.update report --market us --company AAPL
python -m src.update news --company 2330 --limit 10

# 5. 開始聊天
chainlit run src/app.py -w    # 開 http://localhost:8000
```

### 指令表

| 指令 | 用途 |
|---|---|
| `python -m src.update report --market us --company AAPL [--form 10-K]` | 抓美股最新財報(SEC EDGAR,預設 10-Q) |
| `python -m src.update report --market tw --company 2330` | 抓台股最新財報 PDF(MOPS,被擋時印手動下載步驟) |
| `python -m src.update news --company 2330 --limit 10` | 抓新聞(Yahoo Finance RSS) |
| `python -m src.update prune --days 180` | 刪除超過 N 天的新聞 chunk(財報一律保留) |
| `python -m src.ingest --file data/x.pdf --company 2330 --doc-type financial_report --date 2026-07-15` | 手動匯入本地 PDF/txt |
| `python -m src.cli` | 終端問答(單輪) |
| `chainlit run src/app.py -w` | 網頁聊天介面 http://localhost:8000 |

範例問題:

- 「AAPL 最新一季營收多少?」
- 「台積電最新一季的毛利率是多少?」
- 「2330 最近有沒有負面新聞?」

### 之後可以擴充的方向

- `extract_filters` 目前只抽公司代號跟文件類型,可以再加日期區間過濾
- `generate` 可以加一個 node 做「回答品質自我檢查」,形成 self-RAG
- 排程自動更新(cron 呼叫 `python -m src.update` 即可)
- 聊天歷史持久化(目前單次 session,重整即清空)
