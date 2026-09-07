# 維護歷程

紀錄專案已知的技術債、優化候選項與決策依據，供面試或交接時說明「已知但刻意延後」的判斷。

---

## 目前待辦（依 CP 值排序）

1. **LLM 未依 tool 說明觸發補抓（功能退化，最高優先）**（`src/mcp_server.py` 的 tool docstring、`src/graph.py` 的 `agent`）
   實測「MSFT 最新財報和近況如何？」時，資料庫資料停在兩個月前，tool 說明已載明此情境應補抓，但 `qwen3.5:9b` 未照做，直接以過期資料作答（詳見 2026-09-07 驗證）。改造前的確定性規則在同情境必定補抓，屬實際功能退化。
   **已定位根因**：追蹤單輪決策發現，模型回覆「資料已足夠…最新發布日期為 2026-07-12」——它正確讀出了日期，卻判定資料夠新。關鍵在於 prompt 從未提供「今天是哪一天」，模型無從判斷 07-12 距今兩個月。優先修正方向是在 seed prompt 或 tool 回傳內容中帶入當日日期與距今天數，讓時效性判斷有可比基準，再重測是否仍需其他手段（換模型、或保留一道確定性過期檢查作保底）。
   同一次追蹤另發現：模型把 `doc_type` 填成 `"financial_report,news"`（逗號串接），但該參數只接受單一值，會使過濾條件失效。需在 docstring 明確限定可用值，或改為在 tool 內容忍並正規化這種輸入。
2. **README Demo / Screenshot 補齊**（`README.md:12-13`, `:109-110`）
   目前為 TODO，先跳過晚點再補。難度：小（0.5-1 天）。
3. **回應延遲過長**（`src/graph.py` 的 `agent` 節點）
   改為 LLM 自主決策後，每題的 LLM 呼叫次數從 3 次增為至少 4 次（多一次 agent 決策），LLM 決定補抓時再多 1-2 輪。實測本機 `qwen3.5:9b` 單題總耗時約 470 秒，各節點分佈為：`extract_filters` 157 秒、`agent` 決策兩輪合計 156 秒、`generate` 152 秒、實際檢索僅 4 秒——瓶頸全在本地模型推理，非架構本身。可行方向：換用推理更快的模型或量化版本、合併 `rewrite_question`/`extract_filters` 為單次呼叫、資料明顯足夠時跳過 agent 迴圈（等於把部分決策權收回程式，需與待辦 1 一併權衡）。
4. **多標的查詢支援**（`src/graph.py` 的 `ExtractedFilters`/`extract_filters`）
   目前偵測到多個公司會回 `status="error"` 並降級為不過濾（`company=None`），使用者問「AAPL 和 TSLA 比較」拿不到針對兩間公司的分別檢索結果。要支援需將 `company: str | None` 擴充成 `companies: list[str]`，並同步調整 `retrieve_context`/`generate` 的 context 組裝邏輯（依公司分組）與 MCP tool 的參數定義，影響面較大，刻意留待下一階段獨立處理。
5. **資料抓取全面爬蟲化的架構演進**（`src/update.py`、`src/mcp_server.py`）
   若未來資料抓取從現行的同步 API/套件（`requests`/`yfinance`）全面轉向動態或高併發爬蟲，可行方向：依資料特性分「即時輕量」（`httpx.AsyncClient` 同步等待）與「重量級背景」（Task Queue，超時先回傳現有摘要）兩種抓取管道、爬蟲層加入 rate-limit 防護與失敗降級。MCP tool 目前用 `asyncio.to_thread()` 包裝同步抓取避免卡住 event loop，改寫成原生 async 只有在需要同時服務多個併發 client（多個外部 MCP client、或支援多標的並行抓取）時才有實質效益。目前抓取皆為同步 `requests`，單次呼叫數秒內完成，非長跑背景任務，且未遇過真實的高併發或 rate-limit 問題，屬解決尚未出現問題的預先架構，先記錄方向，待真的更換抓取引擎或遇到穩定性問題時再評估。
6. **MCP server 未對外開放與 healthcheck**（`docker-compose.yml`）
   `mcp-server` 目前只在 docker 內部網路提供服務，未映射 port 到 host，Claude Desktop 等外部 client 尚無法連入（Bearer 驗證已就緒，開放時即可把關）。另外 FastMCP 沒有現成的 health endpoint，`depends_on` 只能用 `service_started`，實際就緒檢查靠 app 端每次開對話時連線（失敗會顯示錯誤訊息）。等真的需要外部存取或遇到啟動競態時再處理。

## 保持現狀（已知，僅口頭說明，不列入近期修復）

- **測試為手寫 assert script，非 pytest**（`tests/*.py`）— 目前覆蓋純函式與資料轉換層（`assemble`、`agent_route`、MCP tool 的回傳格式、`fetch_missing_data`、格式化函式等），`generate` 因直接耦合本地 LLM 未做 mock、無自動化覆蓋。轉 pytest 本身工程量小（1 天內），但要測生成節點需先做依賴注入（2-3 天+），現階段 CP 值不如上述待辦項目。
- **LLM 選用 tool 的正確性無自動化測試**（`src/mcp_server.py` 的 tool docstring）— 改為 LLM 自主決策後，「資料過期時會不會主動補抓」取決於模型讀 docstring 的判斷，結果不確定、需真實 Ollama 呼叫，不適合寫成自動化斷言。目前靠端到端手動驗證（見 2026-09-07 章節）。若日後模型換版或 docstring 調整，需重跑手動驗證。
- **MOPS 爬蟲改用 Playwright——評估後不採用**（`src/update.py`）— `t57sb01` 端點是純表單 POST，回傳可直接用 regex 解析的 HTML，不需要 JS 渲染或模擬瀏覽器互動，換工具不會提升穩定性。爬蟲本體仍依賴網站當前頁面結構，網站改版仍會導致失效，屬結構性限制。若未來 MOPS 移除直連表單端點，此判斷需重新評估。詳見 2026-09-04 章節。（原本一併記錄的「MCP 化不採用」判斷已不適用：當時的理由是呼叫端只有一處、跨進程 RPC 不划算，2026-09-07 改造後 LangGraph agent 與外部 client 成為兩個呼叫端，MCP 化的前提已成立。）

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

## 2026-09-07　改為 MCP tool-calling 架構，補資料決策交給 LLM

### 背景

原本補資料的決策完全寫死在程式裡：`route_after_retrieve()` 依 `needs_refetch()` 的日期門檻決定要不要抓資料。這個做法在既有情境下穩定可靠，但有兩個限制——判斷準則只認「新聞日期距今幾天」這個單一維度，無法理解「問法暗示需要多新的資料」；而且對外開放的 MCP tool 是門面式的（內部把檢索、判斷、補抓、重查整套跑完才回傳），外部 client 拿不到中間決策點，只能接受既定流程。

本次改造把決策權交給 LLM，並讓兩個呼叫端（Chainlit 內部的 LangGraph agent、外部的 Claude Desktop 等 client）走相同協定、共用同一份 tool 定義，避免同樣的判斷邏輯維護兩套。MCP server 同時從 stdio 改為 HTTP transport 並加上 Bearer token 驗證——stdio 沒有 per-request 驗證的概念，要做身分驗證必須是網路服務。

**已知代價**：每題多一次 LLM 往返（決策用），且判斷從確定性規則變成模型推理，穩定性取決於模型的指令遵從能力——實測顯示這個代價確實發生了，詳見下方驗證。延遲方面本機實測單題約 470 秒，但瓶頸在本地模型推理速度（檢索本身僅 4 秒），非架構所致。

### 架構

```
rewrite_question → extract_filters → agent ⇄ tools → assemble → (generate | no_result)
```

`agent` 綁定三個 MCP tool 交由 LLM 選用，`tools` 執行選定的 tool，兩者往返直到 LLM 不再要求呼叫工具（上限 4 輪）；`assemble` 把 tool 結果整理回既有欄位，下游 `generate`/`no_result` 與前端的來源編號、引用連結、報告輸出皆不受影響。

### 改動內容

| 項目 | 內容 | commit |
|---|---|---|
| MCP tool 拆為單一職責 | 三個各只做一件事、彼此不自動接力的 tool 取代原本兩個門面式 tool：`search_knowledge_base`（只檢索）、`fetch_company_data`（只抓指定公司財報+新聞）、`fetch_market_overview`（只抓市場總覽）。後兩者分開，是因為「要不要看大盤脈絡」屬語意判斷；台/美股來源分派則留在 tool 內部，屬格式規則不交給 LLM。原本的編排邏輯（`_get_fresh_context()`）整段移除，判斷準則改寫成 tool 說明中的自然語言指引。 | `ef76670` |
| transport 改 HTTP 並加身分驗證 | 改用 streamable-http。SDK 內建 `auth=AuthSettings` 是完整 OAuth（`issuer_url` 必填），對單一共享密鑰過重，改以最小 Starlette middleware 檢查 `Authorization: Bearer`，未帶或不符回 401；未設定 token 時不啟用並印警告（本機開發用）。 | `ef76670` |
| LangGraph 改為 tool-calling 迴圈 | 刪除 `retrieve`/`auto_fetch` 節點與 `route_after_retrieve()`/`needs_refetch()`；新增 `agent`（LLM 決策）、`tools`（`ToolNode`）、`assemble`（還原 `retrieved`/`fetch_results`）。`GraphState` 增加 `messages` 欄位，其餘欄位不動以維持下游相容。`_MAX_TOOL_ROUNDS = 4` 取代原本 `fetched` 布林的單次重試保護，避免 LLM 反覆抓取外部網站。 | `ef76670` |
| agent 改以 MCP client 連線 | 用 `langchain-mcp-adapters` 的 `MultiServerMCPClient` 連自家 MCP server，與外部 client 走相同協定。`docker-compose.yml` 新增 `mcp-server` service（同映像檔、僅內部網路）。 | `ef76670` |
| 前端啟動流程與步驟顯示 | graph 建立移到 `@cl.on_chat_start`（因需 async 取得 tool 清單），開新對話時檢查連線，失敗顯示可據以排查的訊息而非無回應介面。tool 呼叫順序由 LLM 動態決定、無法預判，因此整個迴圈只顯示單一步驟。 | `ef76670` |
| 測試調整 | 新增 `tests/test_mcp_tools.py`（tool 回傳格式與參數傳遞）、`tests/test_assemble.py`（結果還原、路由分支與輪數上限）；`tests/test_route.py` 更名 `test_fetch.py`，移除已刪函式的斷言。 | `ef76670` |

### 驗證

自動化測試涵蓋確定性部分（tool 回傳格式、`assemble` 還原、`agent_route` 分支與上限），全數通過。LLM 的決策品質無法自動化斷言，以端到端手動測試檢驗：

| 情境 | 預期 | 實際 |
|---|---|---|
| 身分驗證 | 無 token／錯誤 token 應被拒 | ✅ 皆回 401；正確 token 可取得三個 tool |
| 資料足夠（AAPL，新聞更新至前一日且有財報） | 只檢索、不補抓 | ✅ 僅呼叫 `search_knowledge_base`，回 5 筆／4 來源 |
| 資料過期（MSFT，新聞停在兩個月前，提問含「最新」） | 應判斷過期並補抓後重查 | ❌ 未觸發補抓，直接以兩個月前的資料作答 |

**第三個情境是這次改造最重要的發現**：tool 說明已明確載明「問題含『最新』但新聞不是今天 → 應該補抓」，但 `qwen3.5:9b` 讀取檢索結果（最新日期 2026-07-12）後仍未觸發補抓，兩次獨立執行結果一致，非偶發。同樣情境下，改造前的確定性規則必定會觸發補抓。這驗證了架構風險評估中「判斷準確度取決於模型指令遵從能力」的疑慮確實成立，屬本次改造的實際功能退化，待處理方向見「目前待辦」第 1 項。

過程中另修正兩個實作問題：
- MCP SDK 內建的 DNS rebinding 防護預設僅允許 localhost，容器間以 service 名稱連線（`Host: mcp-server:8000`）會被擋成 421。改以 `MCP_ALLOWED_HOSTS` 設定允許清單，而非關閉防護。
- `langchain-mcp-adapters` 回傳的 `ToolMessage.content` 是 MCP content block 陣列而非純字串，直接 `json.loads` 會失敗導致檢索結果遺失。新增 `_tool_text()` 同時支援兩種格式，並補進測試固定此格式。

---

## 待補紀錄

後續每次修復或有新決策時，於本檔案新增一節（日期 + 標題），保留「做了什麼／為什麼／取捨」，不需重複貼完整程式碼片段，指向檔案路徑 + 行號即可。新完成的修復項目同時要移出「目前待辦」或「保持現狀」區塊。
