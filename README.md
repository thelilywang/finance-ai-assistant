# finance-ai-assistant

財報/新聞 RAG 問答助理

用 LangGraph + Ollama（本地 LLM）+ pgvector 打造的財經文件問答助理。
所有推理都在本機跑，資料不會送到外部 API，適合處理財報這類敏感資料。

## 架構

```
使用者問題
   │
   ▼
extract_filters   ← 用 LLM 判斷問題是否指定公司代號 / 文件類型
   │
   ▼
retrieve          ← 問題 embedding 後，去 pgvector 找最相似的 chunk
   │
   ├── 有結果 → generate    ← 根據檢索到的內容生成回答，附引用來源
   └── 無結果 → no_result   ← 誠實告知查無資料，避免幻覺
```

## 環境需求

- Python 3.10+
- Docker（跑 Postgres + pgvector）
- [Ollama](https://ollama.com) 已安裝並跑在背景

## 安裝步驟

1. 安裝 Ollama 模型

   ```bash
   ollama pull qwen3.5:9b     # 生成用的 LLM
   ollama pull bge-m3         # embedding 模型（支援中文）
   ```

2. 啟動資料庫

   ```bash
   docker compose up -d
   ```

3. 安裝 Python 依賴

   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```

## 匯入資料

把財報 PDF 或新聞文字檔放到 `data/`，然後：

```bash
python -m src.ingest --file data/2330_2026Q2.pdf \
    --company 2330 --doc-type financial_report --date 2026-07-15
```

## 自動抓取更新

手動觸發抓取財報/新聞並匯入（重跑同一來源會自動去重）：

```bash
python -m src.update report --market us --company AAPL   # 美股財報（SEC EDGAR，預設 10-Q，可加 --form 10-K）
python -m src.update report --market tw --company 2330   # 台股財報（MOPS，下載 PDF 到 data/）
python -m src.update news --company 2330 --limit 10      # 新聞（Yahoo Finance RSS）
```

MOPS 介面脆弱，抓取失敗時會印出手動下載步驟。

## 開始問答

```bash
python -m src.cli
```

## 網頁介面

ChatGPT 風格的聊天介面（token 逐字串流、單次 session 多輪對話）：

```bash
chainlit run src/app.py -w    # 開 http://localhost:8000
```

範例問題：
- 「台積電最新一季的毛利率是多少？」
- 「2330 最近有沒有負面新聞？」

## 之後可以擴充的方向

- `extract_filters` 目前只抽公司代號跟文件類型，可以再加日期區間過濾
- `generate` 可以加一個 node 做「回答品質自我檢查」（answer 有沒有真的對應到 context），形成 self-RAG
- 資料來源可以接公開資訊觀測站 API，做定期自動匯入
- pgvector 的 IVFFlat index 資料量大（>10萬筆）之後效果較好，量少時可以先不建 index
