# 維護歷程

紀錄專案已知的技術債、優化候選項與決策依據，供面試或交接時說明「已知但刻意延後」的判斷。

---

## 2026-09-02　依賴版本 / 架構優化評估

對 8 項候選優化點做唯讀評估（不改動邏輯），逐一給出：影響情境、六維評分（效能延遲／成本／維運複雜度／生態成熟度／可擴展性／vendor lock-in）、修復難度、面試話術。完整評分表見本次 commit 前的分析討論記錄；以下為結論與後續追蹤。

### 已修復

| 項目 | 修復內容 | commit |
|---|---|---|
| `requirements.txt` chainlit 版本落差 | `chainlit>=1.1.0` → `chainlit>=2.11.0,<3.0.0`（實際安裝版本 2.11.1，1.x→2.x 有 breaking changes，舊約束會讓新環境裝到不相容版本） | `66a5400` |
| LLM retry/backoff | `src/graph.py:41-44` 的 `llm` 定義加上 `.with_retry(stop_after_attempt=3)`；`RunnableRetry` 仍保有 `.invoke()`，`rewrite_question`/`extract_filters`/`generate` 三處呼叫端不用改。Ollama 冷啟動/短暫逾時時會重試，不再直接中斷整個 graph 節點。 | `b031f5c` |
| `tests/test_route.py` 過期測試 fixture | 根因：`route_after_retrieve`（`src/graph.py:175-189`）已改成用 `published_at` 判斷新聞是否過期並讀 `state["question"]` 判斷是否要求「最新」，但測試 dict 沒帶這兩個欄位，導致 `d.get("published_at")` 恆為 `None` → `news_dates` 恆空 → 永遠落入 `auto_fetch` 分支。屬測試落後於生產邏輯演進，非 `route_after_retrieve` 本身有 bug。補上 `question` 欄位、`published_at` 改用真實的 `date` 物件（原本錯誤示範會用字串比較日期直接炸 `TypeError`），並新增一筆「新聞過期需重抓」的案例補齊覆蓋。 | 本次 |
| 無連線池 | `src/vectorstore.py` 的 `get_connection()` 改用 `psycopg_pool.ConnectionPool`（`min_size=1, max_size=5, open=False`），每次查詢從共用池借連線而非新開 TCP + PG 認證。所有呼叫端（`app.py`/`ingest.py`/`graph.py`/`update.py`）用法不變，因為 `pool.connection()` 一樣是 context manager。額外加了 `requirements.txt` 的 `psycopg[pool]>=3.1.0`。過程中發現 `ConnectionPool` 預設 `timeout=30` 秒——DB 連不上時要等滿 30 秒才降級，遠比原本 `psycopg.connect()` 的毫秒級失敗慢；改成 `timeout=2` 後測試從 32 秒降到 4-5 秒（正常連線本該是毫秒級，2 秒內連不上代表 DB 真的掛了，拖久沒意義）。 | 本次 |
| Ticker regex fallback 誤判 | 治本而非修 regex：`extract_filters`（`src/graph.py`）從手寫 prompt + `json.loads` 改成 `llm.with_structured_output(ExtractedFilters)`，Pydantic schema 含 `status`/`error_message`/`company`/`doc_type`，`company` 用 `field_validator` 呼叫新增的 `src/tickers.py::normalize_ticker()` 正規化（去除 `.TW`/`.PR.A` 等後綴、驗證台股 4-6碼數字+可選字母尾碼／美股 1-5碼大寫字母格式）。原本的 regex fallback（純英文問題會誤抓一般單字當 ticker）直接拿掉，改由 LLM 在 structured prompt 中自行判斷；多標的問題（如「AAPL 和 TSLA 比較」）現在會回報 `status="error"` 而非硬猜一個代號，而不是「本次先不支援多標的」的下一階段規劃（見待辦）。同時發現並修正 3 處既有的 `isdigit() and len==4` 台股判斷（`graph.py`/`market.py`/`update.py`）——ETF 新制 6 碼、特別股/可轉債帶字母尾碼的代號會被這個舊判斷誤判成美股，統一改用 `tickers.py::is_tw_ticker()`。新增 `tests/test_tickers.py` 覆蓋格式邊界案例。過程中發現 `with_structured_output()` 是 `ChatOllama` 專屬方法，`.with_retry()` 包裝後回傳 `RunnableRetry` 不再有這個方法，需要先在原始 `ChatOllama` 物件（`_base_llm`）上呼叫 `with_structured_output`，最後才疊 `with_retry`。 | 本次 |

### 待辦（依 CP 值排序）

1. **README Demo / Screenshot 補齊**（`README.md:12-13`, `:109-110`）
   目前為 TODO，先跳過晚點再補。難度：小（0.5-1 天）。
2. **多標的查詢支援**（`src/graph.py` 的 `ExtractedFilters`/`extract_filters`）
   目前偵測到多個公司會回 `status="error"` 並降級為不過濾（`company=None`），使用者問「AAPL 和 TSLA 比較」拿不到針對兩間公司的分別檢索結果。要支援需將 `company: str | None` 擴充成 `companies: list[str]`，並同步改 `retrieve`/`auto_fetch`/`route_after_retrieve`/`generate` 的 context 組裝邏輯（依公司分組），影響面較大，刻意留待下一階段獨立處理。

### 保持現狀（已知，僅口頭說明，不列入近期修復）

- **MOPS 爬蟲脆弱性**（`src/update.py:112-163`）— MOPS 無官方 API，兩段式表單 POST + regex 解析 HTML，網站改版即失效。已有 try/except 全包 + 失敗降級印手動下載指引（`update.py:115` docstring 已明確標註此限制），屬結構性風險而非程式碼品質問題。
- **Rewrite regex bypass 誤判追問**（`src/graph.py:60-61`）— 用一次 regex 判斷換取省一次 LLM 呼叫，代價是「追問中剛好含代號/年份」的案例會被誤判成獨立問題不做改寫。屬效能與正確性的刻意取捨。
- **測試為手寫 assert script，非 pytest**（`tests/*.py`，7 個檔案）— 目前僅覆蓋純函式（`route_after_retrieve`、`unique_sources`、格式化函式等），核心節點 `retrieve`/`auto_fetch`/`generate` 因直接耦合 DB 與本地 LLM，未做 mock 層、無自動化覆蓋。轉 pytest 本身工程量小（1 天內），但要測核心節點需先做依賴注入（2-3 天+），現階段 CP 值不如上述待辦項目。

---

## 待補紀錄

後續每次修復或有新決策時，於本檔案新增一節（日期 + 標題），保留「做了什麼／為什麼／取捨」，不需重複貼完整程式碼片段，指向檔案路徑 + 行號即可。
