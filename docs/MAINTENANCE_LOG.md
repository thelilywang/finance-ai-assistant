# 維護歷程

紀錄專案已知的技術債、優化候選項與決策依據。重點不只在「做了什麼」，也在「為什麼這樣取捨」與「什麼是已知但刻意延後的」。

---

## 目前待辦（依 CP 值排序）

### 檢索品質（2026-09-10 標注評估後新增）

1. **`news_since_days` 的雙重用途解耦**（`src/graph.py` 的 `extract_filters`／`route_after_tools`、`src/vectorstore.py`）
   同一個值被當三種東西用：在 `similarity_search` 是 SQL 絕對篩選（`published_at >= CURRENT_DATE - N`），在 `route_after_tools` 只是選門檻的二元開關（`<= 7` 取當天、否則取 3 天），在 `_seed_prompt` 又注入 agent 提示。窗值本身從不等於門檻，兩者的語意也不同：前者是「使用者要什麼範圍」，後者是「資料多新才算夠」。目前耦合的後果是無時效語意的問題（`None`）與 30 天、365 天窗吃到同一個 3 天門檻。

2. **平行化檢索與向量快取**（`src/graph.py` 的 `retrieve_context`）
   四次 `similarity_search` 完全循序，彼此無資料依賴（後兩次只需要前次結果的 id 集合去重，可先發後濾）。`embed_query` 每次呼叫都重算，同一問題在 agent 多輪迴圈中會重複 embedding。此項對總延遲的改善幅度需先量測——已知瓶頸是本地模型生成速度（每秒約 10 字），檢索佔比可能不足以讓優化顯著，量測後再決定是否值得做。

3. **`fb24dbc` 之前的遺留資料無偵測機制**（`src/update.py`、`doc_chunks`）
   ASML 財報只有 2,923 字元是靠人工比對各公司字數才發現的，系統本身不會察覺。目前庫內僅此一例且已重抓，但新增外國發行人時同類問題不會自動浮現。低成本做法是入庫時記錄字數並在明顯偏離同類文檔時警示，或在 `_select_exhibit` 選中的檔案顯著小於同申報其他 `.htm` 時提醒。

4. **`_select_exhibit` 的「取最大 htm」啟發式**（`src/update.py`）
   ASML 該份申報中，投影片（20KB）與法定中期報告（76KB）並存，這次選對只是因為後者較大。若某次申報的投影片檔案更大就會誤挑——原始碼的 ponytail 註解已標明此上限與升級路徑（改解析 index.html 表格的 EX-99.1 類型標籤）。尚未實際誤挑過，維持觀察。

### 其他

5. **README Demo / Screenshot 補齊**（`README.md:12-13`, `:109-110`）
   目前為 TODO，先跳過晚點再補。難度：小（0.5-1 天）。
6. **多標的查詢支援**（`src/graph.py` 的 `ExtractedFilters`/`extract_filters`）
   目前偵測到多個公司會回 `status="error"` 並降級為不過濾（`company=None`），使用者問「AAPL 和 TSLA 比較」拿不到針對兩間公司的分別檢索結果。要支援需將 `company: str | None` 擴充成 `companies: list[str]`，並同步調整 `retrieve_context`/`generate` 的 context 組裝邏輯（依公司分組）與 MCP tool 的參數定義，影響面較大，刻意留待下一階段獨立處理。
7. **`src/update.py` 依資料類型拆分模組**（`src/update.py`）
   目前 598 行、16 個函式。四個抓取器（EDGAR／台股財報兩軌／新聞／市場新聞）彼此不互相呼叫，共用的只有 `FetchResult`、`TIMEOUT` 與 `BROWSER_UA` 三樣，因此沒有「改 A 功能要先讀懂 B」的實際負擔，拆檔屬預防性整理而非解決現有痛點。真要拆時**依資料類型**切為 `report`（EDGAR + 台股雙軌）／`news`／`market_news`／`_common`（放上述三個共用項），因為這條線與實際修改動機吻合：某來源改版就只動該檔。**不建議依台股／美股切**——`fetch_news` 單一函式同時處理兩市場（只差 `.TW` 後綴）、`fetch_market_news` 兩者都掃，按市場切會迫使這兩個函式拆散或重複，市場並非此模組的變動軸線。拆檔需同步調整 `graph.py` 的延遲 import、`mcp_server.py` 的 import，以及 `tests/test_fetch.py` 的 monkeypatch——後者是打在 `src.update` 的模組屬性上，import 路徑一變會靜默失效變成真的連外而非報錯，是拆檔時最容易漏掉的一點。宜獨立成一次純搬遷 commit，不與功能改動混做。
8. **數字類查詢的直答通道**（`src/graph.py` 的 `assemble`/`generate`、`src/mcp_server.py`）
   官方 OpenAPI 取得的結構化財報數字目前與 PDF 文字一樣進 `doc_chunks`，走同一條向量檢索路徑。「台積電最新一季 EPS 多少」這類純數字問題其實不需要 embedding 相似度比對——資料庫裡就有確定的那一格，繞過檢索可同時降低延遲與消除檢索誤差。要做需新增一個直查結構化數字的 MCP tool，並調整 `assemble`/`generate` 的 context 組裝與引用編號邏輯：現行設計的前提是「所有證據都可被 `[來源N]` 引用」，直答通道的數字若不進 `retrieved` 就沒有對應來源編號，等於在決策卡的反幻覺規則上開一個沒有引用的破口，需先想清楚這類數字如何標註出處。影響面大，刻意獨立處理。
9. **資料抓取全面爬蟲化的架構演進**（`src/update.py`、`src/mcp_server.py`）
   若未來抓取從同步 API/套件轉向動態或高併發爬蟲，可行方向：依資料特性分「即時輕量」與「重量級背景」（Task Queue，超時先回傳現有摘要）兩種管道、爬蟲層加入 rate-limit 防護與失敗降級。MCP tool 目前以 `asyncio.to_thread()` 包裝同步抓取避免卡住 event loop，改寫成原生 async 要到需服務多個併發 client 時才有實質效益。現況為同步 `requests`、單次數秒內完成，且未遇過真實的高併發或 rate-limit 問題，屬解決尚未出現的問題，先記錄方向待實際需要時再評估。
10. **雙掛牌對照表改為 API 查詢 + 落地快取**（`src/tickers.py` 的 `TW_US_DUAL_LISTED`）
   目前台美雙掛牌（台積電＝2330／TSM）的對應關係是寫死的靜態 dict，四檔手動維護。台股 ADR 檔數少且極少變動，靜態表在現階段夠用且零延遲，但新增標的要改程式。預期做法：先用 API 查詢對應關係，查到後落地存進資料表（等未來 ORM 優化一併處理），之後優先讀資料表、查不到才回頭打 API 補查。需先確認資料來源——ADR 對應關係在既有的 yfinance 與兩個官方 OpenAPI 都沒有直接欄位，靠公司名稱模糊比對不穩，須先找到可靠端點再動工。在那之前往靜態表加一行即可。
11. **MCP server 未對外開放與 healthcheck**（`docker-compose.yml`）
   `mcp-server` 目前只在 docker 內部網路提供服務，未映射 port 到 host，Claude Desktop 等外部 client 尚無法連入（Bearer 驗證已就緒，開放時即可把關）。另外 FastMCP 沒有現成的 health endpoint，`depends_on` 只能用 `service_started`，實際就緒檢查靠 app 端每次開對話時連線（失敗會顯示錯誤訊息）。等真的需要外部存取或遇到啟動競態時再處理。

## 保持現狀（已評估，判斷暫不處理）

- **領域微調 Embedding 與 Cross-Encoder 重排——評估後不採用**（`src/config.py` 的 `EMBEDDING_MODEL`、`src/graph.py` 的 `retrieve_context`）— 兩者皆為擋掉離題查詢而評估，2026-09-10 判斷不做。**領域專用 Embedding**：提案前提是「通用模型對時間詞權重過高，導致帶時間詞的問題與新聞的時間特徵共振」，實測不成立——同一問題拿掉「今天」分數僅降 0.004（0.510→0.506），而無時間詞的「今天心情不好」仍有 0.52，真正原因是短句中文閒聊的相似度基線本就落在 0.50 附近，與時間詞無關。換模型需重跑全庫 3,656 筆 embedding、重新量測所有門檻（分數尺度不通用），成本高而針對的病因並不存在。**Cross-Encoder 重排**：技術上確實能區分「同樣有『今天』但天氣與財報無關」，但需新增 `bge-reranker` 類模型並對每次檢索的 top-K 逐筆推論，在本專案的瓶頸下不划算——現況單題總耗時 186 至 470 秒、瓶頸是本地模型生成速度，再加一次逐筆推論只會惡化延遲。兩者要解的問題已由待辦第 3 項（LLM 意圖分類，實測 12/12、零額外延遲）以更低成本覆蓋。若未來語料跨足多領域、或改用推理速度足夠的硬體，可重新評估 Cross-Encoder 作為檢索精度（而非離題過濾）的手段。

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

## 2026-09-09　延遲優化收斂、財報數字正確性、對話持久化

承前一章節，換模型與開推理已排除，本次收斂剩下三個延遲方向，並處理累積的技術債——其中財報抓取的數字正確性佔了大半。

### 延遲優化：三個方向收斂

**Context 權責分離**：摘要與 metadata 原本統一封裝全量送進 context，metadata 佔 57%（7177 字中的 4064 字），agent 每輪整份重送，而 tool 說明早已叫模型只讀摘要。改為送進 LLM 的複本只留 `summary_for_llm`。**未帶來可量測的延遲改善**——瓶頸是生成速度（每秒約 10 字），減少輸入 token 不影響輸出；效益是 context 膨脹速率降低一半以上，09-08 已記錄 `num_ctx` 塞滿時答案會被擠成空字串。

**資料明顯足夠時跳過 agent 第二輪**：第二輪的唯一產出是模型說一句「夠了，停」，實測要價 82 至 106 秒，改為條件路由。與 09-07「決策權交給 LLM」的衝突刻意控制在最小範圍：**只收回「資料明顯足夠 → 停止呼叫工具」**，查無資料、新聞過期、日期不明、剛補抓完一律交還 agent。誤判代價不對稱（誤判收工會拿過期資料作答，誤判回 agent 只多花一輪），判準取保守側。省下的呼叫是結構性的，但總耗時 208.5 對 204.7 秒——同批量測中 `generate` 在 88 至 163 秒間浮動，負載變異蓋過了省下的時間。

**決策卡字數約束——實測後不採用**：原假設是不犧牲 14 個欄位、改用硬性字數約束壓縮輸出。同容器、同檢索結果、`temperature=0` 實測與假設相反：

| 決策卡 prompt | 輸出字數 | 免責聲明 |
|---|---|---|
| 現行（基準，重跑兩次同值） | 924 字 | 保留 |
| 加字數約束 | 1252 字（**+35%**） | **遺漏** |
| 改為限制子條列數量 | 1062 字（+15%） | 保留 |

基準每欄本就 1-2 句、沒有廢話可壓，而「含每個子條列」的措辭反而誘導模型展開更多子條列並漏掉免責聲明，屬合規性退化——長度由欄位規格決定，不由約束決定。

### 檢索範圍與對話持久化

**新聞時效判斷改由 LLM 抽取**：原本用關鍵字 regex 判斷是否問近期新聞，命中就限縮 90 天。三個問題：只有 90 天與不過濾兩檔，「本週」與「最近一年」同列一檔；同一條 regex 在兩處各跑一次，推出兩組無關的天數；tool 說明又用散文重寫同一組字眼，三份拷貝無機制保證同步。改由 `extract_filters` 一次抽出 `news_since_days` 存進 state，兩處共用單一來源。夾取 1..365 是必要的：該值直接進 SQL 比較，模型回 0 或負數會查成「未來的新聞」而全空。**取捨**：門檻以 7 天為界而非「有值就收緊」，否則「最近三個月」也會被要求當天新聞。這是本次唯一有意的行為變更，已用測試固定。

**對話歷史持久化**：成本不在儲存層而在認證——data layer 以 user identifier 分租，沒有身分就無法區分誰的歷史。續談時從 `ThreadDict` 重建 history 仍走 `_trim_for_history()`，維持與正常對話一致的 prompt token 控制。`"createdAt"` 是 TEXT，cutoff 在 Python 端算成同格式字串比大小，不對整欄 cast 以免索引失效。`db/chainlit_schema.sql` 原本沒掛進 `docker-compose.yml`，一併補上；既有 volume 仍需手動跑一次 psql。

### 財報數字正確性

本次最大宗，三項一線相承：先能抓到外國發行人的財報，再讓數字精準，最後處理同一家公司在兩市場各有一套數字。**共同特徵是都不報錯**，只讓 LLM 讀到看似合理的錯誤數字——比起會拋錯的問題，靜默污染檢索結果更難察覺。

**一、抓對外國發行人的申報**。這類公司不申報 10-Q/10-K，既有的 6-K fallback 卻涵蓋任何重大公告（股利、AGM、月營收），「取最新一份」偶爾會抓到非財報。原想讀 `items` 與 `primaryDocDescription` 辨識性質，取樣後推翻——兩欄位對 6-K 全為空。改採 `reportDate`：財報的報導期末與申報日不同，公告類則填當天；再加「月份需為 3/6/9/12」才排除得掉 TSM 的月營收，且不影響 ASML 的 52/53 週制期末。更嚴重的是**6-K 的主文件只是封面頁**，本文在同一份申報的 exhibit，即使選對申報也幾乎從未匯入可用文字（ASML 由 2,265 字元變 65k）。**已知限制**：「取最大的 exhibit」是啟發式，理論上可能挑到投影片，誤挑再改解析索引的類型標籤。

**二、改為「API 取數字 + 原文取文字」雙軌（台美兩市場）**。兩軌各自入庫、獨立成敗，靠檢索時重聚；兩者不可互相取代——API 只有逐欄數字，敘述只在原文，而原文抽文字後表格易錯位。台股推翻了「MOPS 無官方 API」這個沿用已久的前提，爬蟲降級為其中一軌。**已知範圍**：API 只收一般業，金融業與興櫃只剩爬蟲；兩來源欄位命名不同（證交所中文、櫃買英文），最可能在對方改版時無聲壞掉。

美股走 SEC XBRL，關鍵是每筆事實都帶 `accn`，用它比對即可鎖定申報，**不需寫任何會計期間比對邏輯**。難處在於各公司採用的概念標籤不同、外國發行人走 `ifrs-full` 並以雙幣別申報、companyfacts 會落後數期，故需優先序清單與 fallback，且每條數字須標明期間，否則舊年報會被當成最新一季。實作期間抓到三個靜默錯誤，成因各異但表現一致——都給出看似合理的數字：概念清單首位已停用（取到八年前的營收）、雙幣別 EPS 的單位鍵是 `USD/shares` 而非 `USD`（取到台幣值，量級差 30 倍）、時點數字沒有 `start` 而在本期與比較期間任意挑一期（權益取到兩年前）。最後一個是加上期間標示後才浮現，先前逐家核對輸出都沒看出來。

順帶確立「`try` 只包外部抓取、不包 `ingest`」，原本 DB 失敗會被誤報成抓取異常。依此檢視 `fetch_edgar`，發現 SEC 節流頁是 HTTP 200、`raise_for_status` 攔不住，後備路徑會把警告文字當財報入庫並回報成功，故加內容長度下限。ticker 對照表另加 `lru_cache`；只做快取不加 retry，後者會與這道防線衝突。

**三、雙掛牌標的先確認市場再查詢**。同一家公司在台美都有掛牌時（台積電＝2330／TSM），兩邊數字都對卻不能互比：幣別、期間、每股基準皆不同（EPS 實測為 49.33 元與 1.36 美元）。原本 prompt 要求「台積電→2330」，等於**替使用者做了他沒做的選擇**。改為只記錄使用者有沒有明講市場、不做推測：明講了直接查，沒講才反問並附上按鈕（打字回答仍有效）。不採「一律反問」——已經說 TSM 還問很囉嗦；也不採「兩邊都答」——只想問台股的人會拿到一堆美股數字。

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
| 意圖確認流程 | `graph.py` 的 `ExtractedFilters` 增加 `market` 欄位；新增 `resolve_market`／`ask_market` 兩個節點與對應路由 | — |
| 併陳與追問 | `both` 時指示 agent 分別檢索兩次並注入不可換算的警語；改寫 prompt 補上保留市場選擇，另從歷史撿回代號 | — |
| 反問的 UI 選項 | `app.py` 以 `cl.AskActionMessage` 給出三顆按鈕，點選後帶著 `market` 重跑。按鈕只是捷徑，打字回答仍走追問流程；逾時不中斷對話 | — |
| 文案與測試 | `i18n.py` 中英各補反問、警語與按鈕字串；新增 `tests/test_dual_market.py` | — |

---

## 2026-09-10　檢索規則的標注評估、時效歸屬與外國發行人財報缺漏

以 13 題標注問題集逐條驗證檢索規則，揭出三個獨立缺陷：兩個在檢索層修復，一個屬歷史資料，追查後與初步假設不符。

### 背景

`retrieve_context` 的四段補資料規則彼此影響，原本只有端到端手動驗證。新增 `tests/eval_data/rag_annotations.json` 與 `tests/eval_rag_retrieval.py`，依規則分類判準——放寬看非空、補充看筆數上限、時效看 header 文字，套單一 precision/recall 會蓋掉規則層級的差異。首輪 11/13，修復後 13/13。

### 排查過程：ASML 財報只有 2,923 字元

ASML 財報僅 5 個 chunk、2,923 字元，內容全是 SEC 表頭、地址與簽名，唯一的數字出現在未被抓取的 exhibit 標題裡；同期 MSFT 有 343,759 字元。

初步判斷指向 `_select_exhibit` 的 except 分支：目錄讀取失敗會退回主文（6-K 主文只是封面頁），只印警告不影響回傳值。**此判斷有誤**，三項反證：以該申報真實的 `index.json` 餵入 `_select_exhibit`，正確選出 76KB 的法定中期報告；該 `index.json` 結構完整、HTTP 200，無觸發例外的條件；實跑抓取直接下載法定中期報告、抽出 64,972 字元，未印出任何警告。

真正原因是時間差：ASML 入庫於 07-15，`_select_exhibit` 引入於 09-09（`fb24dbc`），抓取當時該邏輯尚未存在，程式必然只下載 `primaryDocument`。`fb24dbc` 已修好此 bug，但未回頭重抓先前入庫的資料。影響限 ASML 一家——TSM 同為外國發行人但在其後抓取（288,888 字元），MSFT／NVDA／AAPL 申報 10-Q/10-K，主文件本身即財報全文。

### 修復內容

| 項目 | 修復內容 | commit |
|---|---|---|
| 時效歸屬跨公司污染 | `mcp_server.py` 的 `search_knowledge_base` 計算最新新聞天數時只納入查詢公司自身的新聞；該公司無新聞時改為明講。`retrieve_context` 補進的他家與市場新聞通常更新，混入會讓 header 報出別家的新鮮度，而 tool 說明明講「時效判斷請只依據這個數字」，等同誘導模型跳過補抓。`tests/test_mcp_tools.py` 補兩條迴歸斷言 | — |
| 市場新聞補充恆為 0 至 2 筆 | `graph.py` 的 `retrieve_context` 補充段改為排除查詢公司自身、依發布日期排序、多撈候選再去重回補。原本純語意檢索常撈回同公司內容，去重後補充數歸零（MSFT 實測 0 筆）。`vectorstore.py` 的 `similarity_search` 新增 `exclude_company` 與 `order_by_recency`，前者用 `IS DISTINCT FROM`，`!=` 不匹配 NULL 會吃掉市場新聞 | — |
| 退回封面頁靜默視為成功 | `update.py` 的 `_fetch_edgar` 目錄讀取失敗時仍退回主文，但回傳 `FetchResult(ok=False)` 並在 detail 標註缺漏與 accession number。封面頁約 2,900 字元足以通過 `_MIN_FILING_CHARS`（500），靜默成功會讓只有封面頁的申報混進向量庫且看起來一切正常。非本次 ASML 的肇因，屬同區域的既有缺陷。新增 `tests/test_edgar_exhibit.py` | — |
| ASML 財報重抓 | 沿用 `ingest_text` 內建的 `delete_by_source`，同 source 重跑自動覆蓋。5 chunk／2,923 字元 → 104 chunk／73,234 字元，內容含損益表、股東權益變動表與營運說明 | — |

### 未變動範圍

ASML 仍只有單一申報期別（2026-07-15），跨期比較問題依舊答不出來——內容完整性與期別覆蓋是兩件獨立的事，重抓不會生出上一季的申報。

`fb24dbc` 之前入庫的資料無自動偵測機制，本次靠人工比對字數發現。目前庫內僅 ASML 一例，已處理。

---

## 2026-09-10　離題查詢攔截與放寬告知

### 背景

檢索品質待辦的前兩項：相似度門檻與階層化放寬。兩項的前提都先量測再定奪，結果與原本的判斷不同。

### 一、離題查詢：門檻走不通，改用意圖分類

先量測分數分布（live DB 3,656 chunks／8 家公司，40 題）：離題查詢最高 0.537，財經查詢最低 0.450，兩區間重疊。任何單一門檻都無法兼顧——0.50 漏放 4 題誤殺 1 題，0.54 漏放 0 題誤殺 2 題。

過程中修正了一個錯誤的因果判斷。原以為「今天／明天」這類時間詞與新聞標題的時間特徵共振而墊高分數，實測不成立：拿掉「今天」分數僅降 0.004，而無時間詞的「今天心情不好」仍有 0.52。真正原因是短句中文閒聊對本語料的相似度基線本就落在 0.50 附近。

最終作法是在既有 `ExtractedFilters` 加 `in_scope: bool`，由 `extract_filters` 現有的 LLM 呼叫一併判定，22 題端到端實測全對，且因併進既有呼叫而非新增節點，額外延遲為零。離題時走新增的 `off_topic` 節點直接請使用者改問，形狀與既有的 `ask_market` 對稱（本輪不檢索、不補抓、直接收工）。

門檻方案的殘留一併清除。曾試過保留門檻當防呆（`in_scope` 判離題時再確認庫內確實沒資料），實測反而更差：「今天天氣如何」0.51、「今天心情不好」0.52 都越過門檻，把正確的判定推翻，準確率從 22/22 掉到 19/22。**弱訊號否決強訊號只會損失準確率**，故移除門檻與 `similarity_search` 的 `min_similarity` 參數。

### 二、階層化放寬：前提不成立，只補告知

待辦設想「時間 → 類型 → 公司」三層漸進降級。但 `news_since_days` 的 SQL 條件是 `(doc_type != 'news' OR published_at >= ...)`，時間窗只作用於新聞，財報不受影響——待辦舉的「2330 最近一週的財報查無結果」實測回 5 筆財報，永遠不會空。三層降級沒有對應的真實失敗案例，不做。

真正缺的是另一半：現行放寬完全靜默。已在 `retrieve_context` 放寬時於每筆 chunk 標 `relaxed="doc_type"`，`search_knowledge_base` 的 header 據此多印一句提示，避免模型把新聞當成它要的財報直接引用。

### 三、順帶修掉的兩個問題

- **門檻誤觸發放寬（實作過程中自己引入）**：門檻原本套在所有檢索路徑上，「MSFT 近兩季EPS趨勢」的財報最高分只有 0.497，被清空後誤觸發 `doc_type` 放寬，回一堆新聞卻宣稱「找不到指定類型」。移除門檻後消失。
- **`resolve_market` 硬取 `state["question"]`（既有脆弱點）**：該函式其他欄位一律用 `.get()`，唯獨新增的離題判斷硬取，缺 `question` 的 state 會 `KeyError`。已改用 `.get()`。

### 改動內容

- `src/graph.py`：`ExtractedFilters` 加 `in_scope`（預設 True，漏填時當正常問題）；`extract_filters` 的 prompt 加第 7 點判準；新增 `_is_off_topic`／`off_topic` 節點與 `route_after_resolve_market` 的第三個出口；`retrieve_context` 放寬時標 `relaxed`。
- `src/i18n.py`：新增 `off_topic` 文案（中英各一）。
- `src/mcp_server.py`：header 依 `relaxed` 補一句放寬提示。
- `tests/test_off_topic.py`：新增。`tests/test_dual_market.py`：`_FakeParsed` 補 `in_scope` 與真實 schema 同步。

### 驗證

單元測試 20 支全過；`eval_rag_retrieval.py` 13/13（放寬提示只出現在 JPM、SPCX 兩題庫內確實無財報的案例）；離題判斷端到端 22/22。

---

## 待補紀錄

後續每次修復或有新決策時，於本檔案新增一節（日期 + 標題），保留「做了什麼／為什麼／取捨」，不需重複貼完整程式碼片段，指向檔案路徑或函式名即可。新完成的修復項目同時要移出「目前待辦」或「保持現狀」區塊。
