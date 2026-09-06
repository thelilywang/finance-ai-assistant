# 維護歷程

紀錄專案已知的技術債、優化候選項與決策依據，供面試或交接時說明「已知但刻意延後」的判斷。

---

## 目前待辦（依 CP 值排序）

1. **README Demo / Screenshot 補齊**（`README.md:12-13`, `:109-110`）
   目前為 TODO，先跳過晚點再補。難度：小（0.5-1 天）。
2. **多標的查詢支援**（`src/graph.py` 的 `ExtractedFilters`/`extract_filters`）
   目前偵測到多個公司會回 `status="error"` 並降級為不過濾（`company=None`），使用者問「AAPL 和 TSLA 比較」拿不到針對兩間公司的分別檢索結果。要支援需將 `company: str | None` 擴充成 `companies: list[str]`，並同步改 `retrieve`/`auto_fetch`/`route_after_retrieve`/`generate` 的 context 組裝邏輯（依公司分組），影響面較大，刻意留待下一階段獨立處理。
3. **資料抓取全面爬蟲化的架構演進**（`src/update.py`、`src/mcp_server.py`）
   若未來資料抓取從現行的同步 API/套件（`requests`/`yfinance`）全面轉向動態或高併發爬蟲，可行方向：拆出領域服務層集中管理「檢索→判斷時效→調度抓取→重新檢索」流程、依資料特性分「即時輕量」（`httpx.AsyncClient` 同步等待）與「重量級背景」（Task Queue，超時先回傳現有摘要）兩種抓取管道、爬蟲層加入 rate-limit 防護與失敗降級。目前抓取皆為同步 `requests`，單次呼叫數秒內完成，非長跑背景任務，且單人本地 app 未遇過真實的高併發或 rate-limit 問題，屬解決尚未出現問題的預先架構，先記錄方向，待真的更換抓取引擎或遇到穩定性問題時再評估。

## 保持現狀（已知，僅口頭說明，不列入近期修復）

- **測試為手寫 assert script，非 pytest**（`tests/*.py`）— 目前僅覆蓋純函式（`route_after_retrieve`、`unique_sources`、格式化函式等），核心節點 `retrieve`/`auto_fetch`/`generate` 因直接耦合 DB 與本地 LLM，未做 mock 層、無自動化覆蓋。轉 pytest 本身工程量小（1 天內），但要測核心節點需先做依賴注入（2-3 天+），現階段 CP 值不如上述待辦項目。
- **MOPS 爬蟲改用 Playwright/MCP 化——評估後不採用**（`src/update.py:112-163`）— `t57sb01` 端點是純表單 POST，回傳可直接用 regex 解析的 HTML，不需要 JS 渲染或模擬瀏覽器互動，換工具不會提升穩定性。關注點分離的目標已達成（`fetch_mops()` 是獨立函式，呼叫端已用 try/except 全包）；MCP 協定的價值在多個呼叫端共用同一工具，這裡呼叫端只有一處，改用跨進程 RPC 只會多一層失敗模式與部署成本。爬蟲本體仍依賴網站當前頁面結構，網站改版仍會導致失效，屬結構性限制。若未來 MOPS 移除直連表單端點，此判斷需重新評估。詳見 2026-09-04 章節。

---

## 2026-09-02　依賴版本 / 架構優化評估

對 8 項候選優化點做唯讀評估（不改動邏輯），逐一給出：影響情境、六維評分（效能延遲／成本／維運複雜度／生態成熟度／可擴展性／vendor lock-in）、修復難度、面試話術。完整評分表見本次 commit 前的分析討論記錄；以下為結論與後續追蹤。

### 已修復

| 項目 | 修復內容 | commit |
|---|---|---|
| `requirements.txt` chainlit 版本落差 | `chainlit>=1.1.0` → `chainlit>=2.11.0,<3.0.0`（實際安裝版本 2.11.1，1.x→2.x 有 breaking changes，舊約束會讓新環境裝到不相容版本） | `66a5400` |

---

## 2026-09-03　LLM 穩定性、連線效能、Ticker 誤判修復

### 已修復

| 項目 | 修復內容 | commit |
|---|---|---|
| LLM retry/backoff | `src/graph.py:41-44` 的 `llm` 定義加上 `.with_retry(stop_after_attempt=3)`；`RunnableRetry` 仍保有 `.invoke()`，`rewrite_question`/`extract_filters`/`generate` 三處呼叫端不用改。Ollama 冷啟動/短暫逾時時會重試，不再直接中斷整個 graph 節點。 | `b031f5c` |
| `tests/test_route.py` 過期測試 fixture | 根因：`route_after_retrieve`（`src/graph.py:175-189`）已改成用 `published_at` 判斷新聞是否過期並讀 `state["question"]` 判斷是否要求「最新」，但測試 dict 沒帶這兩個欄位，導致 `d.get("published_at")` 恆為 `None` → `news_dates` 恆空 → 永遠落入 `auto_fetch` 分支。屬測試落後於生產邏輯演進，非 `route_after_retrieve` 本身有 bug。補上 `question` 欄位、`published_at` 改用真實的 `date` 物件（原本錯誤示範會用字串比較日期直接炸 `TypeError`），並新增一筆「新聞過期需重抓」的案例補齊覆蓋。 | `87c989c` |
| 無連線池 | `src/vectorstore.py` 的 `get_connection()` 改用 `psycopg_pool.ConnectionPool`（`min_size=1, max_size=5, open=False`），每次查詢從共用池借連線而非新開 TCP + PG 認證。所有呼叫端（`app.py`/`ingest.py`/`graph.py`/`update.py`）用法不變，因為 `pool.connection()` 一樣是 context manager。額外加了 `requirements.txt` 的 `psycopg[pool]>=3.1.0`。過程中發現 `ConnectionPool` 預設 `timeout=30` 秒——DB 連不上時要等滿 30 秒才降級，遠比原本 `psycopg.connect()` 的毫秒級失敗慢；改成 `timeout=2` 後測試從 32 秒降到 4-5 秒（正常連線本該是毫秒級，2 秒內連不上代表 DB 真的掛了，拖久沒意義）。 | `c77ff4b` |
| Ticker regex fallback 誤判 | 治本而非修 regex：`extract_filters`（`src/graph.py`）從手寫 prompt + `json.loads` 改成 `llm.with_structured_output(ExtractedFilters)`，Pydantic schema 含 `status`/`error_message`/`company`/`doc_type`，`company` 用 `field_validator` 呼叫新增的 `src/tickers.py::normalize_ticker()` 正規化（去除 `.TW`/`.PR.A` 等後綴、驗證台股 4-6碼數字+可選字母尾碼／美股 1-5碼大寫字母格式）。原本的 regex fallback（純英文問題會誤抓一般單字當 ticker）直接拿掉，改由 LLM 在 structured prompt 中自行判斷；多標的問題（如「AAPL 和 TSLA 比較」）現在會回報 `status="error"` 而非硬猜一個代號（多標的支援見上方「目前待辦」）。同時發現並修正 3 處既有的 `isdigit() and len==4` 台股判斷（`graph.py`/`market.py`/`update.py`）——ETF 新制 6 碼、特別股/可轉債帶字母尾碼的代號會被這個舊判斷誤判成美股，統一改用 `tickers.py::is_tw_ticker()`。新增 `tests/test_tickers.py` 覆蓋格式邊界案例。過程中發現 `with_structured_output()` 是 `ChatOllama` 專屬方法，`.with_retry()` 包裝後回傳 `RunnableRetry` 不再有這個方法，需要先在原始 `ChatOllama` 物件（`_base_llm`）上呼叫 `with_structured_output`，最後才疊 `with_retry`。 | `2a00991` |

---

## 2026-09-04　MOPS 財報選檔邏輯修正

### 背景

「MOPS 爬蟲脆弱性」在 09-02 的評估中被列為保持現狀——已有 try/except 全包、失敗降級印手動下載指引，判斷為結構性限制而非程式碼品質問題。本次重新檢視時，先評估了「將 `fetch_mops` 抽成獨立 MCP Server、內部改用 Playwright」的架構提案。

### 架構提案評估：MCP + Playwright 化

**結論：不採用。** 理由與詳細討論見上方「保持現狀」區塊。

### 發現的實際問題：財報固定選到英文版

評估架構提案的過程中，直接向 MOPS 端點送出真實請求（2330，115年）取得原始回應 HTML，發現同一季度會同時列出 `_AI1.pdf`（IFRSs合併財報，中文主文）與 `_AIA.pdf`（IFRSs英文版）兩份檔案。

原本的選檔邏輯 `sorted(files)[-1]` 依字典序排序，`'AIA' > 'AI1'`，導致每次都固定選到英文版而非中文主文——這是系統性錯誤，不是偶發，且與服務中文財經助理的產品定位不符。

### 修復

| 項目 | 修復內容 | commit |
|---|---|---|
| MOPS 財報誤選英文版 | `src/update.py` 新增 `_select_report_file()`，取代原本的 `sorted(files)[-1]`：先篩出最新月份的檔案，該月份內優先選 `_AI1.pdf`（中文主文），沒有才退回其他檔案；選到非中文主文時印出告警訊息，不再靜默接受降級結果。新增 `tests/test_update.py`，用實測取得的真實檔名組合覆蓋：同月中英文並存、僅有英文版、單一檔案、查無資料、重複檔名。 | `36c6cdf` |

### 未變動範圍

MOPS 爬蟲本體（表單 POST + regex 解析）仍依賴網站當前的頁面結構，網站改版仍會導致失效——這次只修正了「選檔邏輯選錯語言版本」這個已發現的準確度問題，屬於已知結構性限制的其中一項修正，不是解決根本限制本身。

---

## 2026-09-04　Rewrite 追問改寫誤判修正

### 問題

`rewrite_question`（`src/graph.py`）在有對話歷史時，把使用者追問改寫成不依賴上下文的獨立問題（例如「那毛利率呢？」→「台積電的毛利率是多少？」），讓後續 embedding 檢索有效。改寫前有一段 regex bypass：問題中出現 4 位數字或 2-5 碼大寫字母就視為「已指名代號」，跳過改寫直接放行。

此判斷會誤判兩類問題：
- 追問中帶年份，如「2024 年的營收呢？」——`\d{4}` 誤判成台股代號。
- 追問中帶財務縮寫，如「ROE 表現如何？」——`[A-Z]{2,5}` 誤判成美股 ticker。

兩者都仍然依賴上下文（缺少「哪家公司」），被跳過改寫後語意不完整，會直接影響後續 `extract_filters`/`retrieve` 的檢索結果。

用真實 Ollama 對照驗證：`re.search(...)` 對這兩句都回傳 match（會觸發 bypass），改寫前後行為差異明確存在，非純理論風險。

### 修復

| 項目 | 修復內容 | commit |
|---|---|---|
| Rewrite regex bypass 誤判追問 | 拿掉 `graph.py` 裡的 regex bypass，`rewrite_question` 在有歷史時一律呼叫 LLM 改寫。rewrite prompt 本身已寫明「若新問題本身已經獨立完整，原樣輸出即可」，所以完整問題不會被改壞，只是多一次 LLM 呼叫確認。代價：每輪有歷史的對話都固定多跑一次 LLM（現有 `llm.with_retry()` 已處理偶發逾時，非本次新增風險）。 | `f2ff695` |

---

## 2026-09-07　抽離 GraphState 並新增 MCP server

### 背景

評估將股價/財報抓取與 RAG 檢索包裝成 MCP tool，讓 Claude Desktop 等外部 MCP client 也能使用同一套邏輯。確認架構：Chainlit UI 維持現有的 in-process 函式呼叫不變，MCP server 是新增的獨立入口，兩者共用同一份核心邏輯，而非各自維護一份。此架構的前提是核心函式不能耦合 LangGraph 的 `GraphState`，也需要有結構化的成功/失敗回傳值供程式判斷（原本只用 `print()` 給人看，呼叫端無法得知結果）。

`query_market_context` 採單一門面 tool 設計：內部自動判斷資料時效性並在需要時補抓，一次呼叫即可拿到盡量更新過的結果，行為與 Chainlit 既有的路由邏輯一致，不依賴外部 LLM client 自行判斷、接力呼叫多個 tool 的推理品質。

### 修復 / 新增

| 項目 | 內容 | commit |
|---|---|---|
| `fetch_mops`/`fetch_edgar` 缺乏結構化回傳值 | `src/update.py` 新增 `FetchResult(ok, detail)` dataclass，兩個函式所有的成功/失敗出口都改成回傳 `FetchResult`，原本的 `print()` 訊息全部保留（CLI 行為不變），只是額外把同樣資訊包進回傳值供程式化呼叫端使用。 | `b2f796c` |
| `auto_fetch` 耦合 `GraphState` | `src/graph.py` 抽出 `fetch_missing_data(company, has_report)` 純函式，把「決定要抓什麼、執行抓取」的邏輯搬出 `auto_fetch` 節點；節點瘦身成從 `state` 取值、呼叫這個純函式、標記 `fetched=True`。行為完全不變，`fetch_missing_data` 現在可被 MCP tool handler 直接呼叫。 | `b2f796c` |
| `retrieve` 耦合 `GraphState` | `src/graph.py` 抽出 `retrieve_context(question, company, doc_type)` 純函式，把向量檢索與既有的補資料規則（doc_type 濾空放寬重查、財報問題補新聞、補全域市場新聞）搬出 `retrieve` 節點。逐行原樣搬移，行為不變。 | `aae5871` |
| `route_after_retrieve` 過期判斷邏輯無法重用 | `src/graph.py` 抽出 `needs_refetch(docs, company, question)`：有指名公司但沒新聞、或新聞已過期（依問題是否要求「最新」收緊門檻）時回傳 `True`。`route_after_retrieve` 呼叫它取代原本內聯的判斷，行為完全不變。`tests/test_route.py` 補上獨立斷言。 | `c9dd94a` |
| `src/mcp_server.py` | 新增 `FastMCP` server，開放兩個 tool：`get_stock_data(ticker)`（抓取財報/新聞並回傳即時行情快照）、`query_market_context(question, ticker=None)`（向量檢索，查無資料或新聞過期時自動補抓再重查一次），共用上述三個純函式。同步邏輯用 `asyncio.to_thread()` 包裝避免卡住 event loop。`requirements.txt` 補上 `mcp>=1.28.0`（先前只裝在 venv，未列入依賴清單）。 | `41c1e1d` |
| MCP tool 資料判斷粒度較粗 | `src/mcp_server.py` 抽出 `_get_fresh_context(question, company)`：封裝「檢索 → 判斷是否過期 → 需要就補抓 → 重新檢索」流程，`get_stock_data`/`query_market_context` 共用，取代原本 `get_stock_data` 固定一律嘗試抓取、不判斷是否已有財報的做法。`query_market_context` 的回應也依是否觸發過補抓加註提示句，區分「使用現有資料」與「已自動補抓最新資料」兩種情況。 | `18c0639` |

### 驗證

實際啟動 Ollama + pgvector（透過現有 docker-compose 服務），呼叫 `get_stock_data` 與 `query_market_context` 端到端測試：對已有完整資料的標的（AAPL）正確跳過補抓、直接回傳；對資料已過期的標的（2330）正確觸發補抓並在回應加註提示句，`source_exists` 去重也如預期跳過已入庫項目。

---

## 待補紀錄

後續每次修復或有新決策時，於本檔案新增一節（日期 + 標題），保留「做了什麼／為什麼／取捨」，不需重複貼完整程式碼片段，指向檔案路徑 + 行號即可。新完成的修復項目同時要移出「目前待辦」或「保持現狀」區塊。
