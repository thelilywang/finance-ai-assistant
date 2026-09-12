# 維護歷程

紀錄專案已知的技術債、優化候選項與決策依據。重點不只在「做了什麼」，也在「為什麼這樣取捨」與「什麼是已知但刻意延後的」。

---

## 目前待辦（依 CP 值排序）

1. **README Demo / Screenshot 補齊**（`README.md:12-13`, `:109-110`）
   目前為 TODO，先跳過晚點再補。難度：小（0.5-1 天）。
2. **多標的查詢支援**（`src/graph.py` 的 `ExtractedFilters`/`extract_filters`）
   目前偵測到多個公司會回 `status="error"` 並降級為不過濾（`company=None`），使用者問「AAPL 和 TSLA 比較」拿不到針對兩間公司的分別檢索結果。要支援需將 `company: str | None` 擴充成 `companies: list[str]`，並同步調整 `retrieve_context`/`generate` 的 context 組裝邏輯（依公司分組）與 MCP tool 的參數定義，影響面較大，刻意留待下一階段獨立處理。
3. **數字類查詢的直答通道**（`src/graph.py` 的 `assemble`/`generate`、`src/mcp_server.py`）
   官方 OpenAPI 取得的結構化財報數字目前與 PDF 文字一樣進 `doc_chunks`，走同一條向量檢索路徑。「台積電最新一季 EPS 多少」這類純數字問題其實不需要 embedding 相似度比對——資料庫裡就有確定的那一格，繞過檢索可同時降低延遲與消除檢索誤差。要做需新增一個直查結構化數字的 MCP tool，並調整 `assemble`/`generate` 的 context 組裝與引用編號邏輯：現行設計的前提是「所有證據都可被 `[來源N]` 引用」，直答通道的數字若不進 `retrieved` 就沒有對應來源編號，等於在決策卡的反幻覺規則上開一個沒有引用的破口，需先想清楚這類數字如何標註出處。影響面大，刻意獨立處理。
4. **雙掛牌對照表改為 API 查詢 + 落地快取**（`src/tickers.py` 的 `TW_US_DUAL_LISTED`）
   目前台美雙掛牌（台積電＝2330／TSM）的對應關係是寫死的靜態 dict，四檔手動維護。台股 ADR 檔數少且極少變動，靜態表在現階段夠用且零延遲，但新增標的要改程式。預期做法：先用 API 查詢對應關係，查到後落地存進資料表（等未來 ORM 優化一併處理），之後優先讀資料表、查不到才回頭打 API 補查。需先確認資料來源——ADR 對應關係在既有的 yfinance 與兩個官方 OpenAPI 都沒有直接欄位，靠公司名稱模糊比對不穩，須先找到可靠端點再動工。在那之前往靜態表加一行即可。
5. **MCP server 未對外開放與 healthcheck**（`docker-compose.yml`）
   `mcp-server` 目前只在 docker 內部網路提供服務，未映射 port 到 host，Claude Desktop 等外部 client 尚無法連入（Bearer 驗證已就緒，開放時即可把關）。另外 FastMCP 沒有現成的 health endpoint，`depends_on` 只能用 `service_started`，實際就緒檢查靠 app 端每次開對話時連線（失敗會顯示錯誤訊息）。等真的需要外部存取或遇到啟動競態時再處理。
6. **AI 執行時間的持續觀測與回測**（`data/logs/`、`src/logging_setup.py`）— **持續性項目，不是做完就關掉**
   logfile 已逐節點記錄耗時（`rewrite_question`／`extract_filters`／`agent`／`generate`／`retrieve`），同一題以 `qid` 串連。需累積一段時間的真實使用資料後，分析各節點耗時分佈：已知瓶頸是本地模型生成，但**佔比多少尚未用數據確認**，這是決定下一輪優化該投在哪裡的依據（例如若 `agent` 的 tool loop 輪數才是主因，優化 `generate` 就是做白工）。分析方式：`data/logs/*.log` 是 JSON Lines，可直接用 pandas 或 jq 彙總。

   **2026-09-13 首次嘗試分析：資料量不足，未能得出結論。** 當日 203 行紀錄中，八個 `log_duration` 觀測點只有 `retrieve_context` 觸發過 6 次，四個 LLM 節點（`rewrite_question`／`extract_filters`／`agent`／`generate`）**一次都沒有**——logging 落地後尚未有真人問過完整的題目，六筆全來自 smoke test。**要等實際使用累積後再分析，不要拿 smoke test 的數字當結論。** 判斷可以開始分析的門檻：`generate` 事件累積約 30 筆以上（涵蓋不同題型與是否命中快取）。
7. **其餘 `print` 遷移至 logging**（`update.py` 34 處、`charts.py` 7、`app.py` 6、`market.py` 5、`ingest.py` 4、`cli.py` 3、`i18n.py` 1）
   2026-09-13 只遷移了 AI 路徑（`graph.py`、`mcp_server.py`）。其餘屬 CLI 給人看的進度輸出，與 AI 耗時追蹤無關，優先度低。要做時注意 CLI 的即時進度顯示與 logging 的緩衝行為不同。
8. **logfile 保留策略與敏感資料**（`config.LOG_BACKUP_DAYS`）
   目前只記錄長度（`prompt_chars`／`answer_chars`）而非內容，故無個資疑慮。若未來為了回測要記錄 prompt／回應全文，需先決定保留天數與去識別化方式——專案已有 `NEWS_RETENTION_DAYS`／`THREAD_RETENTION_DAYS` 的保留期慣例可循（後者的註解明確指出「對話含提問內容，屬個資，留短一點」）。另需觀測 `LOG_BACKUP_DAYS=30` 是否合適：日檔大小取決於實際使用量，累積一段時間後回頭確認磁碟佔用與「回測要看多久以前」的實際需求是否匹配。

## 保持現狀（已評估，判斷暫不處理）

- **`_select_exhibit` 的「取最大 htm」啟發式——維持觀察**（`src/update.py`）— 尚未實際誤挑過，`ingest_text` 的入庫字數警示已是後備防線。原設想的升級路徑（優先選 EX-99.1）經實測不成立：ASML 樣本中 EX-99.1 是新聞稿、EX-99.2 才是投影片，真正財報是 EX-99.4，改用類型標籤反而更差。

- **領域微調 Embedding 與 Cross-Encoder 重排——評估後不採用**（`src/config.py` 的 `EMBEDDING_MODEL`、`src/graph.py` 的 `retrieve_context`）— 兩者皆為擋掉離題查詢而評估，2026-09-10 判斷不做。**領域專用 Embedding**：提案前提是「通用模型對時間詞權重過高，導致帶時間詞的問題與新聞的時間特徵共振」，實測不成立，真正原因是短句中文閒聊的相似度基線本就落在 0.50 附近，與時間詞無關（量測數字見 2026-09-10 章節）。換模型需重跑全庫 3,656 筆 embedding、重新量測所有門檻（分數尺度不通用），成本高而針對的病因並不存在。**Cross-Encoder 重排**：技術上確實能區分「同樣有『今天』但天氣與財報無關」，但需新增 `bge-reranker` 類模型並對每次檢索的 top-K 逐筆推論，在本專案的瓶頸下不划算——現況單題總耗時 186 至 470 秒、瓶頸是本地模型生成速度，再加一次逐筆推論只會惡化延遲。兩者要解的問題已由待辦第 3 項（LLM 意圖分類，實測 12/12、零額外延遲）以更低成本覆蓋。若未來語料跨足多領域、或改用推理速度足夠的硬體，可重新評估 Cross-Encoder 作為檢索精度（而非離題過濾）的手段。

- **異質文檔重排與配額控制——量測後判斷不需處理**（`src/graph.py` 的 `retrieve_context`）— 原列為待辦，2026-09-10 實測後撤下。跨來源重排的前提（兩種文檔在同一名次空間混排）不成立：四次檢索各自 `ORDER BY` 後串接，財報與新聞從未進入同一個排序，混排問題已被現行架構迴避，再加一層重排是重解已解的問題。配額（主檢索 5／補新聞 3／補市場新聞 2）亦維持不變：原本疑慮是純財報問題固定補 3 條新聞屬浪費，但實測跑完整的 `retrieve_context` → `generate` 並比對引用編號，補進來的新聞確實被引用（「微軟營收結構」一題決策卡直接引用兩條新聞）。這與決策卡設計一致——`trend_section` 的「利多」「風險」「下一個關鍵事件」「建議追蹤指標」四欄硬性必填，「建議傾向」明文要求財報＋新聞＋行情三者齊備，砍掉新聞會讓這些欄位失去素材。結論：那 3 條新聞是必要成本，不是浪費。

- **回應延遲過長，架構層面已無可省**（`src/graph.py` 的 `generate` 節點）— 單題總耗時 186 至 470 秒。三個可行方向已於 09-09 收斂：`_trim_for_llm` 裁掉 agent 迴圈重複傳遞的 context（降低 context 膨脹，不改善延遲）、`route_after_tools` 在資料明顯足夠時跳過第二輪 agent 決策（結構性省下一次 LLM 呼叫，該節點原佔 82 至 106 秒）、決策卡字數約束經 A/B 實測反使輸出變長 35% 並遺漏免責聲明，已排除。另兩項候選亦已排除：合併 `rewrite_question`/`extract_filters` 僅佔 3%；換用較小或 MLX 版本的模型會先失去 tool calling 與結構化輸出能力。**剩餘瓶頸是本地模型的生成速度本身（穩定在每秒約 10 字，`generate` 一題需 90 至 160 秒），屬硬體限制而非架構問題**，換用推理速度更高的硬體才會改變，在此之前重新評估軟體層方向不具效益。詳見 2026-09-08、09-09 章節。
- **測試為手寫 assert script，非 pytest**（`tests/*.py`）— 目前覆蓋純函式與資料轉換層（`assemble`、`agent_route`、MCP tool 的回傳格式、`fetch_missing_data`、格式化函式等），`generate` 因直接耦合本地 LLM 未做 mock、無自動化覆蓋。轉 pytest 本身工程量小（1 天內），但要測生成節點需先做依賴注入（2-3 天+），現階段 CP 值不如上述待辦項目。
- **LLM 選用 tool 的正確性無自動化測試**（`src/mcp_server.py` 的 tool 說明、`src/graph.py` 的 `_tool_llm`）— 「資料過期時會不會主動補抓」取決於模型行為，需真實 Ollama 呼叫且結果不保證重現，不適合寫成自動化斷言。目前靠端到端手動驗證，且需連續執行多次確認一致性（09-08 有過單次成功、重複執行皆失敗的實例）。模型換版、調整 tool 說明或改動 `_tool_llm` 的參數時都需重跑。
- **MOPS 爬蟲改用 Playwright——評估後不採用**（`src/update.py`）— `t57sb01` 端點是純表單 POST，回傳可直接用 regex 解析的 HTML，不需要 JS 渲染或模擬瀏覽器互動，換工具不會提升穩定性。爬蟲本體仍依賴網站當前頁面結構，網站改版仍會失效，屬結構性限制。此判斷本身仍成立，但影響範圍已於 09-09 縮小：財報數字改由官方 OpenAPI 提供，爬蟲只剩文字敘述一項職責，掛掉不再等於該公司完全沒有台股財報資料。若未來 MOPS 移除直連表單端點，此判斷需重新評估。詳見 2026-09-04、09-09 章節。

---

## 2026-09-02　依賴版本 / 架構優化評估

評估 8 項架構優化候選，一項於本日修復，其餘落入「目前待辦」與「保持現狀」。

| 項目 | 修復內容 | commit |
|---|---|---|
| `requirements.txt` chainlit 版本落差 | `chainlit>=1.1.0` → `chainlit>=2.11.0,<3.0.0`（實際安裝版本 2.11.1，1.x→2.x 有 breaking changes，舊約束會讓新環境裝到不相容版本） | `66a5400` |

---

## 2026-09-03　LLM 穩定性、連線效能、Ticker 誤判修復

> 本節提及的 `route_after_retrieve`／`auto_fetch` 已於 2026-09-07 改造時移除，內容保留作為當時的決策紀錄。

### 已修復

| 項目 | 修復內容 | commit |
|---|---|---|
| LLM retry/backoff | `llm` 定義加上 `.with_retry(stop_after_attempt=3)`；`RunnableRetry` 仍保有 `.invoke()`，三處呼叫端不用改。Ollama 冷啟動或短暫逾時時會重試，不再直接中斷整個 graph 節點。 | `b031f5c` |
| 測試 fixture 落後於生產邏輯 | `route_after_retrieve` 已改用 `published_at` 判斷新聞是否過期，但測試 dict 沒帶該欄位，導致判斷恆為空、永遠落入補抓分支——屬測試未跟上邏輯演進，非程式本身有 bug。補上缺漏欄位、`published_at` 改用真實 `date` 物件（用字串比較日期會直接拋 `TypeError`），並補一筆「新聞過期需重抓」的案例。 | `87c989c` |
| 無連線池 | `src/vectorstore.py` 的 `get_connection()` 改用 `psycopg_pool.ConnectionPool`，從共用池借連線而非每次新開 TCP + PG 認證；所有呼叫端用法不變（`pool.connection()` 一樣是 context manager）。過程中發現其預設 `timeout=30` 秒遠慢於原本 `psycopg.connect()` 的毫秒級失敗，改成 `timeout=2` 後測試從 32 秒降到 4-5 秒——正常連線本該是毫秒級，2 秒內連不上即代表 DB 已掛，續等無益。 | `c77ff4b` |
| Ticker regex fallback 誤判 | 治本而非修 regex：`extract_filters` 從手寫 prompt + `json.loads` 改用 `with_structured_output(ExtractedFilters)`，代號由 Pydantic `field_validator` 呼叫新增的 `normalize_ticker()` 正規化（去除 `.TW`/`.PR.A` 等後綴並驗證格式）。原本的 regex fallback（純英文問題會誤抓一般單字當 ticker）直接移除；多標的問題改為回報錯誤而非硬猜一個代號。同時修正三處既有的 `isdigit() and len==4` 台股判斷——ETF 新制 6 碼、特別股與可轉債的字母尾碼會被誤判成美股，統一改用 `is_tw_ticker()`。 | `2a00991` |

---

## 2026-09-04　MOPS 選檔與 Rewrite 改寫的準確度修正

兩項各自獨立、皆屬「靜默選錯」而非報錯的準確度缺陷。

### 一、MOPS 固定選到英文版財報

「MOPS 爬蟲脆弱性」在 09-02 被列為保持現狀，本次重新檢視時評估改用 Playwright 的提案，結論為不採用（理由見上方「保持現狀」）。但評估過程中向端點送出真實請求（2330，115 年），發現同一季度會同時列出 `_AI1.pdf`（中文主文）與 `_AIA.pdf`（英文版），而原本的 `sorted(files)[-1]` 依字典序排序、`'AIA' > 'AI1'`，導致每次固定選到英文版——系統性錯誤而非偶發，且與中文財經助理的定位不符。

**未變動範圍**：爬蟲本體仍依賴網站當前頁面結構，改版仍會失效。這次只修正選檔語言，不是解決該結構性限制。

### 二、Rewrite regex bypass 誤判追問

`rewrite_question` 在有歷史時會把追問改寫成獨立問題（「那毛利率呢？」→「台積電的毛利率是多少？」），改寫前有一段 regex bypass：出現 4 位數字或 2-5 碼大寫字母就視為已指名代號、跳過改寫。它會誤判兩類仍依賴上下文的追問——「2024 年的營收呢？」被 `\d{4}` 當成台股代號，「ROE 表現如何？」被 `[A-Z]{2,5}` 當成美股 ticker。用真實 Ollama 驗證兩句都會觸發 bypass，非純理論風險。

### 修復

| 項目 | 修復內容 | commit |
|---|---|---|
| MOPS 財報誤選英文版 | `update.py` 新增 `_select_report_file()` 取代 `sorted(files)[-1]`：先篩最新月份，該月份內優先選 `_AI1.pdf`，選到非中文主文時印告警不靜默降級。新增 `tests/test_update.py`，用實測取得的真實檔名組合覆蓋五種情境。 | `36c6cdf` |
| Rewrite regex bypass 誤判追問 | 拿掉 `graph.py` 的 regex bypass，有歷史時一律呼叫 LLM 改寫；prompt 已寫明「若問題本身已獨立完整，原樣輸出即可」，完整問題不會被改壞。代價是每輪有歷史的對話固定多跑一次 LLM。 | `f2ff695` |

---

## 2026-09-07　改為 MCP tool-calling 架構，補資料決策交給 LLM

### 背景

原本補資料的決策完全寫死在程式裡：`route_after_retrieve()` 依 `needs_refetch()` 的日期門檻決定要不要抓資料。這個做法在既有情境下穩定可靠，但有兩個限制——判斷準則只認「新聞日期距今幾天」這個單一維度，無法理解「問法暗示需要多新的資料」；而且對外開放的 MCP tool 是門面式的（內部把檢索、判斷、補抓、重查整套跑完才回傳），外部 client 拿不到中間決策點，只能接受既定流程。

本次改造把決策權交給 LLM，並讓兩個呼叫端（Chainlit 內部的 LangGraph agent、外部的 Claude Desktop 等 client）走相同協定、共用同一份 tool 定義，避免同樣的判斷邏輯維護兩套。MCP server 同時從 stdio 改為 HTTP transport 並加上 Bearer token 驗證——stdio 沒有 per-request 驗證的概念，要做身分驗證必須是網路服務。

**取捨**：換來的是判斷能涵蓋規則寫不出的情境（例如依問法語氣調整時效標準），以及外部 client 能自行決定要不要補抓；代價是每題多一次 LLM 往返、延遲增加，且判斷正確性不再有程式保證——這個代價在改造當下即被列為主要風險，實際也確實發生。

### 架構

```
rewrite_question → extract_filters → agent ⇄ tools → assemble → (generate | no_result)
```

`agent` 綁定三個 MCP tool 交由 LLM 選用，`tools` 執行選定的 tool，兩者往返直到 LLM 不再要求呼叫工具（上限 4 輪）；`assemble` 把 tool 結果整理回既有欄位，下游 `generate`/`no_result` 與前端的來源編號、引用連結、報告輸出皆不受影響。

### 改動內容

| 項目 | 改動說明 | commit |
|---|---|---|
| MCP tool 拆為單一職責 | 三個各只做一件事、彼此不自動接力的 tool 取代原本兩個門面式 tool：`search_knowledge_base`（只檢索）、`fetch_company_data`（只抓指定公司財報+新聞）、`fetch_market_overview`（只抓市場總覽）。後兩者分開，是因為「要不要看大盤脈絡」屬語意判斷；台/美股來源分派則留在 tool 內部，屬格式規則不交給 LLM。原本的編排邏輯（`_get_fresh_context()`）整段移除，判斷準則改寫成 tool 說明中的自然語言指引。 | `ef76670` |
| transport 改 HTTP 並加身分驗證 | 改用 streamable-http。SDK 內建 `auth=AuthSettings` 是完整 OAuth（`issuer_url` 必填），對單一共享密鑰過重，改以最小 Starlette middleware 檢查 `Authorization: Bearer`，未帶或不符回 401；未設定 token 時不啟用並印警告（本機開發用）。 | `ef76670` |
| LangGraph 改為 tool-calling 迴圈 | 刪除 `retrieve`/`auto_fetch` 節點與 `route_after_retrieve()`/`needs_refetch()`；新增 `agent`（LLM 決策）、`tools`（`ToolNode`）、`assemble`（還原 `retrieved`/`fetch_results`）。`GraphState` 增加 `messages` 欄位，其餘欄位不動以維持下游相容。`_MAX_TOOL_ROUNDS = 4` 取代原本 `fetched` 布林的單次重試保護，避免 LLM 反覆抓取外部網站。 | `ef76670` |
| agent 改以 MCP client 連線 | 用 `langchain-mcp-adapters` 的 `MultiServerMCPClient` 連自家 MCP server，與外部 client 走相同協定。`docker-compose.yml` 新增 `mcp-server` service（同映像檔、僅內部網路）。 | `ef76670` |
| 前端啟動流程與步驟顯示 | graph 建立移到 `@cl.on_chat_start`（因需 async 取得 tool 清單），開新對話時檢查連線，失敗顯示可據以排查的訊息而非無回應介面。tool 呼叫順序由 LLM 動態決定、無法預判，因此整個迴圈只顯示單一步驟。 | `ef76670` |
| 測試調整 | 新增 `tests/test_mcp_tools.py`（tool 回傳格式與參數傳遞）、`tests/test_assemble.py`（結果還原、路由分支與輪數上限）；`tests/test_route.py` 更名 `test_fetch.py`，移除已刪函式的斷言。 | `ef76670` |

導入 MCP 協定時另遇到兩個套件層面的問題，一併處理：

- **容器間連線被擋成 421**：MCP SDK 內建的 DNS rebinding 防護預設僅允許 localhost，容器以 service 名稱連線（`Host: mcp-server:8000`）會被拒。改以 `MCP_ALLOWED_HOSTS` 設定允許清單，而非關閉該防護。
- **檢索結果在傳遞中遺失**：`langchain-mcp-adapters` 回傳的 `ToolMessage.content` 是 MCP content block 陣列而非純字串，直接 `json.loads` 會失敗。新增 `_tool_text()` 同時支援兩種格式，並補進測試固定此格式。

端到端測試發現資料過期時未觸發補抓，是相對於改造前確定性規則的功能退化。當下判斷為「模型指令遵從能力不足」，後續盤查證實此判斷有誤，真正根因與完整修復見 2026-09-08 章節。

---

## 2026-09-08　補資料決策失效修復、推理顯示與模型替換評估

同一條調查線：先修好 `reasoning=False` 壓掉 tool calling 的退化，再回頭評估「開啟推理」與「換更快模型」兩個方向，後兩者實測後皆不採用。三節共用同一組驗證情境。

### 一、補資料決策失效（根因修復）

09-07 改造後留下一個功能退化：資料停在兩個月前仍直接作答，改造前的確定性規則必定會補抓。

初步假設為指令遵從能力不足，但模型其實已算出天數、得出「需要補抓」的結論，只是寫成文字敘述而非結構化 tool call。落差在輸出格式而非理解能力，據此轉查參數，A／B 對照確認根因為 `reasoning=False` 連帶壓掉了 tool-calling 能力。排查過程中另發現四項相關缺陷，一併處理。

**修復內容**：

| 項目 | 修復內容 | commit |
|---|---|---|
| 關閉推理模式導致 tool-calling 失效（根因） | 依用途拆成兩個模型實例：`agent` 節點改用不帶 `reasoning=False` 的 `_tool_llm`，其餘節點沿用 `_base_llm`。`agent` 的輸出不進使用者可見的串流（前端只放行 `generate` 的 token）。 | `41ac2ec` |
| 模型無從判斷資料新舊 | prompt 從未提供當日日期，模型讀得出「2026-07-12」卻不知距今多久。`_seed_prompt` 與 `search_knowledge_base` 補上今天日期並預先算好「距今 N 天」，不讓模型自行做日期運算。 | `41ac2ec` |
| 財報天數被誤當新聞時效 | 工具呼叫恢復後才顯現：摘要把財報（57 天）與新聞（3 天）混列，資料夠新時也觸發補抓。改為每筆標示「財報｜」或「新聞｜」並在開頭給出最新新聞距今天數，tool 說明同步註明財報按季發布、距今數十天屬正常。 | `41ac2ec` |
| `doc_type` 參數被填入多值 | 模型會傳 `"financial_report,news"`，該參數只接受單一值，照字面過濾會查出空結果。tool 說明限定可填值，並在內部容錯：非單一合法值一律降級為不過濾。 | `41ac2ec` |
| 容器時區為 UTC，日期偏移一天 | 容器比台北時間慢 8 小時，台灣半夜 0-8 點認定的「今天」會少一天，使「距今 N 天」全面偏移，亦影響 MOPS 民國年判斷。`docker-compose.yml` 為三個服務設定 `TZ`。 | `41ac2ec` |

### 二、顯示推理過程

**結論：功能可行但不納入，開啟推理讓單題延遲增為 6.7 倍。**

一個教訓：假設推理段以 `<think>` 標籤內嵌是錯的，據此寫的解析器單元測試全過卻永遠收不到資料。實際走 `additional_kwargs["reasoning_content"]` 獨立欄位，未指定 `reasoning` 時模型照樣推理但內容被丟棄。

延遲量測（本機 `qwen3.5:9b`，真實 MCP + pgvector）：

| 設定 | `extract_filters` | `generate` | 總耗時 | 答案 | 推理 | 首個 token |
|---|---|---|---|---|---|---|
| 關閉推理（基準） | 5.3s | 86.8s | **186.3s** | 1105 字 | — | 108.7s |
| 全節點開啟 | 422.2s | 104.0s | 660.8s | **0 字** | 3152 字 | 569.3s |
| 僅 `generate` 開啟 | 22.1s | 1052.5s | **1245.3s** | 1425 字 | 30891 字 | 237.6s |

`extract_filters` 只做代號抽取，不需判斷的事去推理代價不成比例。答案 0 字另有原因：Ollama 預設 `num_ctx` 4096，RAG prompt 加推理即塞滿；加大到 16384 可解，但模型不再受限後為一句提問寫了 30891 字推理。

壓制推理長度的兩條路徑均無效：`reasoning='low'` 的推理字數與 `True` 相同（層級控制僅 `gpt-oss` 支援）；`num_predict` 限制總輸出，而推理永遠先於答案產生，設 600 時答案再次被截為 0 字。

### 三、替換模型

**結論：`qwen3.5:9b` 是這台 M1／16GB 上唯一可用的模型，換模型救不了延遲。** 較小的模型省下的時間有限，卻先失去 tool calling 與結構化輸出這兩項核心能力；MLX 版本在此機器上更慢。限制來自硬體容量與記憶體頻寬，與架構無關。

每情境三次，沿用第一節的驗證情境（序列執行避免互搶資源）：

| 模型 | 大小 | 單題耗時 | 資料過期→應補抓 | 結構化輸出 |
|---|---|---|---|---|
| `qwen3.5:9b` | 6.6GB | 186s | 3/3 正確 | 正常 |
| `qwen3.5:4b` | 3.4GB | 140s | **0/3** | 正常 |
| `qwen3.5:4b-mlx` | 4.0GB | 278s | 1/3 | **3/3 失敗** |
| `qwen3.5:9b-mlx` | 9.1GB | 逾一小時未完成 | — | — |

`4b` 只快 25% 卻完全不發 tool call，資料停在兩個月前仍直接作答，正是第一節修好的那個退化。`4b-mlx` 把 JSON 寫成 markdown 條列，`extract_filters` 三次全數解析失敗。

「Apple 原生框架應該更快」是合理但錯誤的直覺：`9b-mlx` 失敗源於容量而非框架，加上 embedding 超出 16GB 實體記憶體，swap 一度達 23GB，量到的其實是磁碟分頁速度。排除容量因素的公平比較中（同 4GB 級距、不觸發 swap），`4b-mlx` 仍比 `4b` 慢一倍——同一份權重在 Ollama 下已落後，換框架不具效益。

### 改動內容

| 項目 | 改動說明 | commit |
|---|---|---|
| 維持 `reasoning=False` | `src/graph.py` 的註解改為記錄實測數據與已排除的方案。此限制源於模型的推理成本而非架構。 | `ca4d857` |
| 移除失效的防護程式碼 | `src/app.py` 過濾 `<think>` 標籤的邏輯，原作為「`reasoning=False` 失效時的保險」。但它只作用於 `generate` 的串流，而該節點的 `_base_llm` 已關閉推理；唯一未指定 `reasoning` 的 `_tool_llm` 輸出不進使用者可見的串流。此分支永遠不會執行。 | `ca4d857` |
| UI 模型選單 | 設定面板新增模型下拉選單。`graph.py` 的模型實例從模組層級改為 `_llms(model)` 工廠（`lru_cache` 快取），`GraphState` 新增 `model` 欄位，各節點以 `_model_of(state)` 取值、未帶值時退回預設。不改動全域狀態，多個 session 選用不同模型不會互相干擾。 | `b1da9ea` |
| 候選模型清單 | `LLM_MODEL_CHOICES` 只列預設模型，可用環境變數擴充；實測不合格的模型已從 Ollama 移除。 | `b1da9ea` |

---

## 2026-09-09　財報數字的靜默錯誤、延遲優化收斂、對話持久化

承前一章節，換模型與開推理已排除，本次收斂剩下三個延遲方向，並處理累積的技術債——其中財報抓取的數字正確性佔了大半，三項問題的共同特徵是都不報錯。

### 延遲優化：三個方向收斂

**Context 權責分離**：摘要與 metadata 原本統一封裝全量送進 context，metadata 佔 57%（7177 字中的 4064 字），agent 每輪整份重送，而 tool 說明早已叫模型只讀摘要。改為送進 LLM 的複本只留 `summary_for_llm`。**未帶來可量測的延遲改善**——瓶頸是生成速度（每秒約 10 字），減少輸入 token 不影響輸出；效益是 context 膨脹速率降低一半以上，09-08 已記錄 `num_ctx` 塞滿時答案會被擠成空字串。

**資料明顯足夠時跳過 agent 第二輪**：第二輪的唯一產出是模型說一句「夠了，停」，實測要價 82 至 106 秒，改為條件路由。與 09-07「決策權交給 LLM」的衝突刻意控制在最小範圍：**只收回「資料明顯足夠 → 停止呼叫工具」**，查無資料、新聞過期、日期不明、剛補抓完一律交還 agent。誤判代價不對稱（誤判收工會拿過期資料作答，誤判回 agent 只多花一輪），判準取保守側。省下的呼叫是結構性的，但總耗時量不出差異——`generate` 本身的浮動就蓋過了省下的時間。

**決策卡字數約束——實測後不採用**：原假設是不犧牲 14 個欄位、改用硬性字數約束壓縮輸出。同容器、同檢索結果、`temperature=0` 實測與假設相反：

| 決策卡 prompt | 輸出字數 | 免責聲明 |
|---|---|---|
| 現行（基準，重跑兩次同值） | 924 字 | 保留 |
| 加字數約束 | 1252 字（**+35%**） | **遺漏** |
| 改為限制子條列數量 | 1062 字（+15%） | 保留 |

基準每欄本就 1-2 句、沒有廢話可壓，而「含每個子條列」的措辭反而誘導模型展開更多子條列並漏掉免責聲明，屬合規性退化——長度由欄位規格決定，不由約束決定。

### 新聞時效判斷改由 LLM 抽取

原本用關鍵字 regex 判斷是否問近期新聞，命中就限縮 90 天。三個問題：只有 90 天與不過濾兩檔，「本週」與「最近一年」同列一檔；同一條 regex 在兩處各跑一次，推出兩組無關的天數；tool 說明又用散文重寫同一組字眼，三份拷貝無機制保證同步。改由 `extract_filters` 一次抽出 `news_since_days` 存進 state，兩處共用單一來源。夾取 1..365 是必要的：該值直接進 SQL 比較，模型回 0 或負數會查成「未來的新聞」而全空。**取捨**：門檻以 7 天為界而非「有值就收緊」，否則「最近三個月」也會被要求當天新聞。這是本次唯一有意的行為變更，已用測試固定。

### 對話歷史持久化

成本不在儲存層而在認證——data layer 以 user identifier 分租，沒有身分就無法區分誰的歷史。續談時從 `ThreadDict` 重建 history 仍走 `_trim_for_history()`，維持與正常對話一致的 prompt token 控制。`"createdAt"` 是 TEXT，cutoff 在 Python 端算成同格式字串比大小，不對整欄 cast 以免索引失效。`db/chainlit_schema.sql` 原本沒掛進 `docker-compose.yml`，一併補上；既有 volume 仍需手動跑一次 psql。

### 財報數字的靜默錯誤

本次最大宗，三項一線相承：先能抓到外國發行人的財報，再讓數字精準，最後處理同一家公司在兩市場各有一套數字。**共同特徵是都不報錯**，只讓 LLM 讀到看似合理的錯誤數字——比起會拋錯的問題，靜默污染檢索結果更難察覺。

#### 一、抓對外國發行人的申報

這類公司不申報 10-Q/10-K，既有的 6-K fallback 卻涵蓋任何重大公告（股利、AGM、月營收），「取最新一份」偶爾會抓到非財報。原想讀 `items` 與 `primaryDocDescription` 辨識性質，取樣後推翻——兩欄位對 6-K 全為空。改採 `reportDate`：財報的報導期末與申報日不同，公告類則填當天；再加「月份需為 3/6/9/12」才排除得掉 TSM 的月營收，且不影響 ASML 的 52/53 週制期末。更嚴重的是**6-K 的主文件只是封面頁**，本文在同一份申報的 exhibit，即使選對申報也幾乎從未匯入可用文字（ASML 由 2,265 字元變 65k）。**已知限制**：「取最大的 exhibit」是啟發式，理論上可能挑到投影片，誤挑再改解析索引的類型標籤。

#### 二、改為「API 取數字 + 原文取文字」雙軌（台美兩市場）

兩軌各自入庫、獨立成敗，靠檢索時重聚；兩者不可互相取代——API 只有逐欄數字，敘述只在原文，而原文抽文字後表格易錯位。台股推翻了「MOPS 無官方 API」這個沿用已久的前提，爬蟲降級為其中一軌。**已知範圍**：API 只收一般業，金融業與興櫃只剩爬蟲；兩來源欄位命名不同（證交所中文、櫃買英文），最可能在對方改版時無聲壞掉。

美股走 SEC XBRL，關鍵是每筆事實都帶 `accn`，用它比對即可鎖定申報，**不需寫任何會計期間比對邏輯**。難處在於各公司採用的概念標籤不同、外國發行人走 `ifrs-full` 並以雙幣別申報、companyfacts 會落後數期，故需優先序清單與 fallback，且每條數字須標明期間，否則舊年報會被當成最新一季。實作期間抓到三個靜默錯誤，成因各異但表現一致——都給出看似合理的數字：概念清單首位已停用（取到八年前的營收）、雙幣別 EPS 的單位鍵是 `USD/shares` 而非 `USD`（取到台幣值，量級差 30 倍）、時點數字沒有 `start` 而在本期與比較期間任意挑一期（權益取到兩年前）。最後一個是加上期間標示後才浮現，先前逐家核對輸出都沒看出來。

順帶確立「`try` 只包外部抓取、不包 `ingest`」，原本 DB 失敗會被誤報成抓取異常。依此檢視 `fetch_edgar`，發現 SEC 節流頁是 HTTP 200、`raise_for_status` 攔不住，後備路徑會把警告文字當財報入庫並回報成功，故加內容長度下限。ticker 對照表另加 `lru_cache`；只做快取不加 retry，後者會與這道防線衝突。

#### 三、雙掛牌標的先確認市場再查詢

同一家公司在台美都有掛牌時（台積電＝2330／TSM），兩邊數字都對卻不能互比：幣別、期間、每股基準皆不同（EPS 實測為 49.33 元與 1.36 美元）。原本 prompt 要求「台積電→2330」，等於**替使用者做了他沒做的選擇**。改為只記錄使用者有沒有明講市場、不做推測：明講了直接查，沒講才反問並附上按鈕（打字回答仍有效）。不採「一律反問」——已經說 TSM 還問很囉嗦；也不採「兩邊都答」——只想問台股的人會拿到一堆美股數字。

**只收美股那側查得到財報的標的**：雙掛牌 12 檔中有 6 檔是 OTC 的 Level 1 或非贊助 ADR，不須向 SEC 申報、實測連 CIK 都沒有，收進選單只會讓使用者選了美股卻拿到查無資料，故另立一張表僅供附帶告知。

追問路徑另踩三個坑，根源都是使用者只回一句「美股」、句中沒有公司名：改寫誤解語意、抽不到代號而退化成全庫檢索、按鈕選擇被重抽蓋掉。另外 LLM 記不住冷門代號（「南茂科技」填成 2306，正確 8150），故把代號表直接列進 prompt 要它照抄。

### 改動內容

| 項目 | 涉及檔案與函式 | commit |
|---|---|---|
| Context 權責分離 | `graph.py` 新增 `_trim_for_llm()`，裁切失敗原樣送出不中斷對話 | `a8a7a69` |
| 跳過重複的 agent 決策 | `graph.py` 新增 `route_after_tools()`、`_news_age_days()` | `29967c5` |
| 架構圖同步 | 六個 mermaid 區塊與節點說明停在 09-07 前的 `retrieve`/`auto_fetch`，依 `draw_mermaid()` 重畫 | `1be4f91` |
| 決策卡字數約束 | 實測後回退，`i18n.py` 維持原狀 | — |
| 新聞時效判斷 | `graph.py` 移除 `_RECENT_RE`，`ExtractedFilters` 新增 `news_since_days` 與夾取 validator；`mcp_server.py` 開放同名參數 | — |
| 對話歷史持久化 | `app.py` 新增 `oauth_callback`／`_init_session()`／`on_chat_resume`／`_rebuild_history()`；`vectorstore.py` 新增 `delete_threads_older_than()`；`config.py` 新增 `THREAD_RETENTION_DAYS`；`chainlit_schema.sql` 加兩個 threads 索引並掛進 `docker-compose.yml`；新增 `tests/test_history_rebuild.py` | — |
| EDGAR 6-K | `update.py` 新增 `_is_period_end()`／`_select_filing()`／`_select_exhibit()`，並修正查無申報的訊息；新增 `tests/test_edgar_select.py` | `fb24dbc` |
| 抓取層契約一致化 | `update.py` 的 `fetch_edgar` 拆出 `_fetch_edgar()`，網路錯誤收斂為 `FetchResult` 與其餘四支一致；`tests/test_update.py` 補契約斷言 | — |
| 台股財報改雙軌 | `update.py` 新增 `fetch_tw_financials()` 與五個解析純函式、加固 `fetch_mops()`、CLI 失敗回非零結束碼；`graph.py` 台股分支併入第三軌；`tests/test_update.py` 補至 28 條斷言、`tests/test_fetch.py` 補兩軌案例 | — |
| 美股財報改雙軌 | `update.py` 新增 `fetch_sec_financials()` 與 XBRL 解析純函式，沿用既有的申報選取與格式化；`graph.py` 美股分支併入數字軌 | `c55a125` |
| CIK 查詢加快取 | `update.py` 的 `_company_tickers()` 加 `lru_cache`。測試的 monkeypatch 區段需 `cache_clear()`，否則假資料會汙染後續測試 | `c55a125` |
| 雙掛牌對照表 | `tickers.py` 新增主板 5 檔的雙向對照與查詢函式，OTC 6 檔另立一張表 | — |
| 雙掛牌市場確認 | `graph.py` 的 `ExtractedFilters` 增加 `market`，新增 `resolve_market`／`ask_market` 節點與路由；`app.py` 以 `cl.AskActionMessage` 給按鈕（逾時不中斷對話）；`i18n.py` 中英各補反問、警語與按鈕字串；新增 `tests/test_dual_market.py` | — |

---

## 2026-09-10　RAG 檢索品質優化：標注評估、離題攔截、資料完整性

檢索品質待辦的前兩項（相似度門檻、階層化放寬）**原始前提都被實測推翻**，最後的做法與當初設想不同。

### 標注評估：規則層級的判準

`retrieve_context` 的四段補資料規則彼此影響，原本只有端到端手動驗證。新增 `tests/eval_data/rag_annotations.json` 與 `tests/eval_rag_retrieval.py`，依規則分類判準（放寬看非空、補充看筆數上限、時效看 header 文字），避免單一 precision/recall 蓋掉規則層級的差異。首輪 13 題 11/13，修復後 13/13。

### 一、離題查詢：門檻走不通，改用意圖分類

量測分數分布（live DB 3,656 chunks／8 家公司，40 題）：離題查詢最高 0.537，財經查詢最低 0.450，兩區間重疊，任何單一門檻都無法兼顧。原假設「時間詞與新聞的時間特徵共振」不成立——拿掉「今天」分數僅降 0.004；真正原因是短句中文閒聊的相似度基線本就落在 0.50 附近。

改在 `ExtractedFilters` 加 `in_scope: bool`，由 `extract_filters` 既有的 LLM 呼叫一併判定（額外延遲為零），22 題端到端實測全對。離題時走新增的 `off_topic` 節點直接請使用者改問。曾試過保留門檻當防呆，實測反而更差（準確率 22/22 掉到 19/22，弱訊號否決了強訊號），故移除門檻與 `min_similarity` 參數。

門檻移除也修掉一個既有問題：資料本就稀少時會誤觸發放寬（`MSFT` 財報最高分僅 0.497）。

### 二、階層化放寬：前提不成立，只補告知

待辦設想的「時間 → 類型 → 公司」三層降級前提不成立：`news_since_days` 只作用於新聞、不影響財報，待辦舉例「2330 最近一週財報」實測回 5 筆，永遠不會空。真正缺的是告知——放寬時在 chunk 標 `relaxed="doc_type"`，`search_knowledge_base` 的 header 據此多印一句提示。

### 三、資料完整性：ASML 財報只有 2,923 字元

內容全是 SEC 表頭與簽名，同期 MSFT 有 343,759 字元。不是 `_select_exhibit` 選錯，而是時間差：ASML 入庫於 07-15，該邏輯 09-09（`fb24dbc`）才引入，當時只下載了 `primaryDocument`。影響僅限 ASML，其餘標的抓取時間在其後或主文件本身即全文。

由此補上通用防線：`_MIN_FILING_CHARS`（500 字元）只擋 EDGAR 節流頁，MOPS、PDF 等路徑毫無防護。`ingest_text()` 新增財報低於 `_MIN_FINANCIAL_REPORT_CHARS`（10,000 字元）印警告但不阻斷。警示只在入庫當下觸發，`fb24dbc` 之前入庫的資料仍無自動偵測機制。

### 改動內容

| 項目 | 涉及檔案與函式 |
|---|---|
| 標注評估 | 新增 `tests/eval_data/rag_annotations.json` 與 `tests/eval_rag_retrieval.py` |
| 離題攔截 | `graph.py` 新增 `_is_off_topic`；`i18n.py` 補 `off_topic` 文案；新增 `tests/test_off_topic.py` |
| 放寬告知 | `mcp_server.py` 的 header 補提示 |
| `resolve_market` 防禦性修補 | 對 `state["question"]` 硬取值改用 `.get()` |
| 補充新聞未排除自家公司（時效歸屬污染／市場新聞恆為 0-2 筆） | `mcp_server.py` 計算最新新聞天數時只納入查詢公司自身新聞，避免 header 報錯新鮮度、誘導模型跳過補抓；`retrieve_context` 補充段改為排除查詢公司自身、依發布日期排序，`similarity_search` 新增 `exclude_company`（`IS DISTINCT FROM`，避免 `!=` 漏掉 NULL）與 `order_by_recency` |
| 退回封面頁靜默視為成功 | `_fetch_edgar` 目錄讀取失敗退回主文時，回傳 `FetchResult(ok=False)` 而非靜默成功；封面頁字數足以通過 `_MIN_FILING_CHARS`，屬同區域既有缺陷、非本次肇因 |
| 入庫字數警示 | `ingest.py` 的 `ingest_text()` 新增 `_MIN_FINANCIAL_REPORT_CHARS`；新增 `tests/test_ingest.py` |
| ASML 財報重抓 | 沿用 `ingest_text` 的 `delete_by_source` 覆蓋重抓：5 chunk／2,923 字元 → 104 chunk／73,234 字元 |

---

## 2026-09-10　檢索平行化與 query embedding 快取

`retrieve_context()` 原本會依序執行主檢索、同公司新聞補充與市場新聞補充；agent 在同一題的 tool loop 重查時，也會對相同 question 重複呼叫 Ollama embedding。改為程序內、有界的 TTL/LRU 快取，加上候選檢索預取：有 company 時主檢索、同公司新聞與市場新聞同時送出，待主結果確定後才依原有條件採用候選。`doc_type` 放寬仍只在主檢索為空時執行，來源順序與配額維持「主結果（或放寬結果）→ 同公司新聞最多 3 筆 → 市場新聞最多 2 筆」。

快取 key 包含 embedding model、Ollama URL 與原始 question；預設 256 筆、900 秒，可由 `EMBEDDING_CACHE_MAX_ENTRIES`／`EMBEDDING_CACHE_TTL_SECONDS` 設定，設為 0 可完全關閉。只快取成功結果、不落地、重啟即清空；鎖覆蓋 cold miss，避免同時抵達的相同問題重複打 Ollama。

量測與連線池的結論見下方 2026-09-13 一節。

---

## 2026-09-13　AI 可觀測性：logging 落地與檢索效能實測

### 從 `print` 改為 logging，AI 行為每日落檔

原本全專案用 `print` 輸出，AI 路徑共 9 處（`graph.py` 8、`mcp_server.py` 1）。
`print` 沒有時間戳、沒有層級、只進 stdout，而 `docker logs` 有輪替上限、容器重啟即失去歷史，
結果是**無法回答「上週那一題為什麼跑了 400 秒」**——這對一個以本地模型生成為瓶頸的專案來說，
等於永久放棄優化的判斷依據。

新增 `src/logging_setup.py`，`app` 與 `mcp-server` 進入點各呼叫一次 `setup_logging(service)`：

- **用標準庫 `logging`，不加第三方依賴**。structlog／loguru 的賣點是結構化輸出與較好的 API，
  但需要的結構化欄位用 `extra` 加一個 JSON formatter 就能解決，不值得為此增加依賴。
- **每日一檔、JSON Lines**，寫入 `data/logs/`（`app` 與 `mcp-server` 都已掛載 `./data`，
  不需新增 volume；`.gitignore` 已含 `data/`）。選 JSONL 是因為目的是回測，
  可直接餵 pandas／jq，純文字要先寫 parser。
- **按日期輪替而非按大小**：`RotatingFileHandler` 的 `.1`／`.2` 序號無法對應到日期，
  回測「上週三那題」得逐檔翻。改用 `TimedRotatingFileHandler(when="midnight")`，
  並設 `namer` 讓檔名是 `app-2026-09-13.log` 而非預設的 `app.log.2026-09-13`（利於 glob 與排序）。
  切檔在台北午夜——`docker-compose.yml` 已設 `TZ=Asia/Taipei`，
  與專案其他「今天」的判斷（資料時效、MOPS 民國年）一致。
- **兩個服務各寫各的檔**。`TimedRotatingFileHandler` 在多程序共寫同一檔時，切檔會互相覆蓋。
- **容器外執行時檔名加 `-local` 後綴**（`_log_name()`）。`LOG_DIR` 在 bind mount 上，
  host 直接跑測試會寫進容器同一個 `app.log`。這不只是吵——host 沒有 `PGVECTOR_URL`
  （只在 `docker-compose.yml` 設定），會 fallback 到 `localhost:5432`，而 DB 未對 host 開 port，
  於是每次 host 執行都往共用檔灌一批連線失敗。以 `/.dockerenv` 是否存在判斷執行環境。
  這個問題是 2026-09-13 首次嘗試分析 logfile 時發現的：176／203 行是本機測試的雜訊，
  若不隔離，未來的回測會把它們當成正式環境的故障。
- 保留 `StreamHandler`，`docker logs` 的既有行為不變。

記錄的欄位：四個 LLM 呼叫點（`rewrite_question`／`extract_filters`／`agent`／`generate`）
與 `retrieve_context` 各記 `elapsed_ms`，同一題以 `qid`（問題文字的短 hash）串連。
`generate` 另記 `prompt_chars`／`answer_chars` 以區分「慢在輸入還是輸出」；
**只記長度不記內容**，避免把提問寫進 log（保留策略未定前不落地個資，見待辦 8）。
`GraphState` 沒有 `thread_id`，加欄位會擴散到所有呼叫端，故以 `qid` 代替。

### 檢索效能實測

新增 `RETRIEVE_PARALLEL` 開關（`src/config.py`），讓循序與並行兩條路徑並存於同一份程式碼，
量測腳本 `tests/bench_retrieve.py` 因此能在**同一個 image、同一個容器、同一批資料**上切換行為做 A/B。
六題輪替、每組 7 次取中位數，第一次（含連線池初始化與 Ollama 冷啟動）另計。

| 組合 | 中位數 | 最小 | 最大 |
|---|---|---|---|
| 循序 + 無快取 | 236.5 ms | 198.5 | 263.6 |
| 循序 + 有快取 | 24.6 ms | 17.4 | 35.5 |
| 並行 + 無快取 | 202.5 ms | 198.1 | 215.1 |
| 並行 + 有快取 | **11.5 ms** | 9.3 | 19.1 |

拆開來看兩項優化各自的貢獻：

- **query embedding 快取：省約 212 ms**（循序 236.5 → 24.6）。這是主要貢獻，
  因為每次 `embed_query` 都要打一趟 Ollama，而檢索本身只是幾條 SQL。
- **三段候選並行：無快取時省 34 ms，有快取時省 13 ms**。幅度小但穩定，
  且並行組的最大值（215.1）比循序組（263.6）更集中，離散度較低。

兩條路徑在真實資料上回傳的 chunk id 序列完全相同
（`[4596, 3222, 3200, 3781, 3216, 3854, 3809]`），等價性另有 self-check 以故障注入驗證。

### 連線池：原本擔心的 PoolTimeout 不存在

改動前單次檢索借 1 條連線，改動後三段並行各借 1 條，`vectorstore.py` 的 pool 是 `max_size=5`
的模組級單例，因此**推導**上兩個並行檢索就會超額並在 `timeout=2` 後拋 `PoolTimeout`。
實測推翻了這個推論：

| max_size | 4 個並行檢索的批次中位數 | 單筆 p95 | 失敗 |
|---|---|---|---|
| 5 | 27.1 ms | 44.0 ms | 0 |
| 8 | 27.7 ms | 39.3 ms | 0 |
| 12 | 28.8 ms | 37.9 ms | 0 |

進一步壓到 8、12、20 個並行檢索（理論上分別需要 24、36、60 條連線），在 `max_size=5`
下**全部成功、零失敗**，累計等待分別為 517 / 828 / 1154 ms。

原因是每段 `similarity_search` 持有連線的時間極短（單條 SQL 約數毫秒即歸還），
連線是快速輪轉而非同時被三段長期佔住，所以「3 × 並行數」這個推估的前提並不成立。
`max_size` 敏感度也顯示 5／8／12 之間沒有有意義的差異（中位數落在 195-197 ms，
差距在雜訊範圍內）。

**結論：`max_size` 維持 5，不做調整。** 這是本次量測最有價值的產出——
若照原本的推導直接改成 12，就是在沒有問題的地方加了一個看似合理、實則無依據的數字。

### 保留循序路徑的理由

並行的效益（13-34 ms）遠小於快取（212 ms），且端到端總延遲仍以本地模型生成為主
（單題數十秒至數百秒），這 30 ms 對使用者體感沒有可觀察的影響。
之所以仍保留並行為預設，是因為它確實不會更慢、離散度更低，且成本已經付掉了；
保留 `RETRIEVE_PARALLEL=0` 的循序路徑則是為了日後能重新量測與回退——
若未來 DB 端競爭情況改變（資料量成長、改用共享資料庫），這個開關可以直接驗證而不必改程式。

為避免兩條路徑各自腐化，採用條件與順序抽成 `_relax_doc_type()` 與 `_merge_market_news()` 共用，
`_retrieve_parallel()` 與 `_retrieve_sequential()` 只差在候選如何取得。
`tests/test_retrieve_context.py` 的等價性測試以故障注入驗證過確實有鑑別力
（破壞其中一條路徑的去重邏輯會被抓到）。

### 評估後不採用（記錄理由，避免重複評估）

- **Redis 取代程序內快取**——現在只有 `app` 與 `mcp-server` 兩個單一程序，
  而快取收益集中在同一題的 agent tool loop 內，本來就在同一程序。跨程序共享收不到額外命中，
  卻要付出一個 container、網路依賴、1024 維向量序列化（每筆約 8KB，往返可能比本機 dict 慢）
  與一組「Redis 掛了怎麼辦」的降級路徑。**觸發條件**：MCP server 要跑多 worker／多副本，
  或希望快取跨重啟存活。屆時 `_embed_query_cached()` 的介面不用改，只換內部儲存。
- **單一 SQL 用 `UNION ALL` 取回三段**——可省下兩次往返與連線佔用，但要在 SQL 裡表達
  「主結果有新聞就不要同公司新聞」這類條件邏輯，會把現在讀得懂的 Python 條件變成難維護的 SQL。
  三段各自 `ORDER BY` 也是刻意設計（見上方「異質文檔重排」一節，避免跨來源混排）。
- **改用 async DB driver 取代 ThreadPoolExecutor**——`retrieve_context` 是同步函式、
  被 `asyncio.to_thread` 包著呼叫，改 async 要一路改到 graph 節點與 MCP tool，影響面遠大於收益。

### 改動內容

| 項目 | 位置 |
|---|---|
| logging 設定與 JSONL formatter | 新增 `src/logging_setup.py`（`setup_logging`／`log_duration`） |
| AI 路徑 9 處 `print` 遷移、四個 LLM 呼叫點計時 | `src/graph.py`、`src/mcp_server.py`、`src/app.py` |
| logging 設定項 | `config.LOG_LEVEL`／`LOG_DIR`／`LOG_BACKUP_DAYS` |
| 檢索並行開關與路徑拆分 | `config.RETRIEVE_PARALLEL`；`graph.py` 的 `_retrieve_parallel`／`_retrieve_sequential`／`_relax_doc_type`／`_merge_market_news` |
| 量測腳本 | 新增 `tests/bench_retrieve.py`（需在 container 內執行，DB 未對 host 開 port） |
| 新增 self-check | `tests/test_logging_setup.py`；`tests/test_retrieve_context.py` 補等價性、快取關閉、embed 失敗不污染快取、並行分支例外傳遞 |

## 待補紀錄

後續每次修復或有新決策時，於本檔案新增一節（日期 + 標題），保留「做了什麼／為什麼／取捨」，不需重複貼完整程式碼片段，指向檔案路徑或函式名即可。新完成的修復項目同時要移出「目前待辦」或「保持現狀」區塊。
