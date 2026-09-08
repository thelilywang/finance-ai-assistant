# 維護歷程

紀錄專案已知的技術債、優化候選項與決策依據。重點不只在「做了什麼」，也在「為什麼這樣取捨」與「什麼是已知但刻意延後的」。

---

## 目前待辦（依 CP 值排序）

1. **README Demo / Screenshot 補齊**（`README.md:12-13`, `:109-110`）
   目前為 TODO，先跳過晚點再補。難度：小（0.5-1 天）。
2. **回應延遲過長**（`src/graph.py` 的 `agent` 節點）
   改為 LLM 自主決策後，每題的 LLM 呼叫次數從 3 次增為至少 4 次（多一次 agent 決策），LLM 決定補抓時再多 1-2 輪。實測本機 `qwen3.5:9b` 單題總耗時 186 至 470 秒（視是否觸發補抓與機器負載而異），節點分佈以 186 秒的那次為例：`agent` 決策兩輪合計 93 秒（50%）、`generate` 87 秒（47%）、`extract_filters` 5 秒（3%）、實際檢索不到 1 秒。時間幾乎全落在兩處長 prompt 的生成，瓶頸是本地模型的推理速度，非架構本身。可行方向：縮短 `generate` 的 prompt 與輸出長度（直指 47% 的耗時）、資料明顯足夠時跳過 agent 迴圈（但這等於把部分決策權收回程式，與 09-07 改造的目標相衝突，需權衡）、改用推理速度更高的硬體。兩項曾列為候選的方向已排除：合併 `rewrite_question`/`extract_filters` 僅佔 3%，上限省不到 6 秒；換用較小或 MLX 版本的模型會先失去 tool calling 與結構化輸出能力，詳見 2026-09-08「推理顯示與模型替換評估」。
3. **多標的查詢支援**（`src/graph.py` 的 `ExtractedFilters`/`extract_filters`）
   目前偵測到多個公司會回 `status="error"` 並降級為不過濾（`company=None`），使用者問「AAPL 和 TSLA 比較」拿不到針對兩間公司的分別檢索結果。要支援需將 `company: str | None` 擴充成 `companies: list[str]`，並同步調整 `retrieve_context`/`generate` 的 context 組裝邏輯（依公司分組）與 MCP tool 的參數定義，影響面較大，刻意留待下一階段獨立處理。
4. **資料抓取全面爬蟲化的架構演進**（`src/update.py`、`src/mcp_server.py`）
   若未來抓取從同步 API/套件轉向動態或高併發爬蟲，可行方向：依資料特性分「即時輕量」與「重量級背景」（Task Queue，超時先回傳現有摘要）兩種管道、爬蟲層加入 rate-limit 防護與失敗降級。MCP tool 目前以 `asyncio.to_thread()` 包裝同步抓取避免卡住 event loop，改寫成原生 async 要到需服務多個併發 client 時才有實質效益。現況為同步 `requests`、單次數秒內完成，且未遇過真實的高併發或 rate-limit 問題，屬解決尚未出現的問題，先記錄方向待實際需要時再評估。
5. **MCP server 未對外開放與 healthcheck**（`docker-compose.yml`）
   `mcp-server` 目前只在 docker 內部網路提供服務，未映射 port 到 host，Claude Desktop 等外部 client 尚無法連入（Bearer 驗證已就緒，開放時即可把關）。另外 FastMCP 沒有現成的 health endpoint，`depends_on` 只能用 `service_started`，實際就緒檢查靠 app 端每次開對話時連線（失敗會顯示錯誤訊息）。等真的需要外部存取或遇到啟動競態時再處理。

## 保持現狀（已評估，判斷暫不處理）

- **測試為手寫 assert script，非 pytest**（`tests/*.py`）— 目前覆蓋純函式與資料轉換層（`assemble`、`agent_route`、MCP tool 的回傳格式、`fetch_missing_data`、格式化函式等），`generate` 因直接耦合本地 LLM 未做 mock、無自動化覆蓋。轉 pytest 本身工程量小（1 天內），但要測生成節點需先做依賴注入（2-3 天+），現階段 CP 值不如上述待辦項目。
- **LLM 選用 tool 的正確性無自動化測試**（`src/mcp_server.py` 的 tool 說明、`src/graph.py` 的 `_tool_llm`）— 「資料過期時會不會主動補抓」取決於模型行為，需真實 Ollama 呼叫且結果不保證重現，不適合寫成自動化斷言。目前靠端到端手動驗證，且需連續執行多次確認一致性（09-08 有過單次成功、重複執行皆失敗的實例）。模型換版、調整 tool 說明或改動 `_tool_llm` 的參數時都需重跑。
- **MOPS 爬蟲改用 Playwright——評估後不採用**（`src/update.py`）— `t57sb01` 端點是純表單 POST，回傳可直接用 regex 解析的 HTML，不需要 JS 渲染或模擬瀏覽器互動，換工具不會提升穩定性。爬蟲本體仍依賴網站當前頁面結構，網站改版仍會失效，屬結構性限制。若未來 MOPS 移除直連表單端點，此判斷需重新評估。詳見 2026-09-04 章節。

---

## 2026-09-02　依賴版本 / 架構優化評估

對 8 項候選優化點做唯讀評估（不改動邏輯），逐一就影響情境、六維指標（效能延遲／成本／維運複雜度／生態成熟度／可擴展性／vendor lock-in）與修復難度評分排序。以下為結論與後續追蹤，未列入的項目多屬「已知但當前 CP 值不足」，見上方「目前待辦」與「保持現狀」。

### 已修復

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

## 2026-09-04　MOPS 財報選檔邏輯修正

### 背景

「MOPS 爬蟲脆弱性」在 09-02 的評估中被列為保持現狀——已有 try/except 全包、失敗降級印手動下載指引，判斷為結構性限制而非程式碼品質問題。本次重新檢視時評估了改用 Playwright 的提案，結論為不採用（理由見上方「保持現狀」）。

但評估過程中直接向 MOPS 端點送出真實請求（2330，115 年）取得原始回應，發現同一季度會同時列出 `_AI1.pdf`（IFRSs 合併財報，中文主文）與 `_AIA.pdf`（英文版）兩份檔案。原本的選檔邏輯 `sorted(files)[-1]` 依字典序排序，而 `'AIA' > 'AI1'`，導致每次都固定選到英文版——這是系統性錯誤而非偶發，且與中文財經助理的產品定位不符。

### 修復

| 項目 | 修復內容 | commit |
|---|---|---|
| MOPS 財報誤選英文版 | `src/update.py` 新增 `_select_report_file()`，取代原本的 `sorted(files)[-1]`：先篩出最新月份的檔案，該月份內優先選 `_AI1.pdf`（中文主文），沒有才退回其他檔案；選到非中文主文時印出告警訊息，不再靜默接受降級結果。新增 `tests/test_update.py`，用實測取得的真實檔名組合覆蓋：同月中英文並存、僅有英文版、單一檔案、查無資料、重複檔名。 | `36c6cdf` |

### 未變動範圍

MOPS 爬蟲本體（表單 POST + regex 解析）仍依賴網站當前的頁面結構，網站改版仍會導致失效——這次只修正了「選檔邏輯選錯語言版本」這個已發現的準確度問題，屬於已知結構性限制的其中一項修正，不是解決根本限制本身。

---

## 2026-09-04　Rewrite 追問改寫誤判修正

### 背景

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

**取捨**：換來的是判斷能涵蓋規則寫不出的情境（例如依問法語氣調整時效標準），以及外部 client 能自行決定要不要補抓；代價是每題多一次 LLM 往返、延遲增加，且判斷正確性不再有程式保證——這個代價在改造當下即被列為主要風險，實際也確實發生（見下方驗證）。

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

### 驗證

自動化測試涵蓋確定性部分（tool 回傳格式、`assemble` 還原、`agent_route` 分支與上限），全數通過。LLM 的決策品質無法自動化斷言，以端到端手動測試檢驗：

| 情境 | 預期 | 實際 |
|---|---|---|
| 身分驗證 | 無 token／錯誤 token 應被拒 | ✅ 皆回 401；正確 token 可取得三個 tool |
| 資料足夠（AAPL，新聞更新至前一日且有財報） | 只檢索、不補抓 | ✅ 僅呼叫 `search_knowledge_base`，回 5 筆／4 來源 |
| 資料過期（MSFT，新聞停在兩個月前，提問含「最新」） | 應判斷過期並補抓後重查 | ❌ 未觸發補抓，直接以兩個月前的資料作答 |

第三個情境是相對於改造前的功能退化（同情境下原本的確定性規則必定會補抓），當下判斷為「模型指令遵從能力不足」，後續盤查證實此判斷有誤，真正根因與完整修復見 2026-09-08 章節。

---

## 2026-09-08　補資料決策失效修復

### 背景

09-07 改造後留下一個功能退化：對資料停在兩個月前的標的提問「MSFT 最新財報和近況如何？」，tool 說明已載明此情境應補抓，模型卻直接以過期資料作答。同情境下改造前的確定性規則必定會補抓。

初步假設為模型指令遵從能力不足，但單輪決策的完整回覆顯示模型已正確算出天數、套用規則並得出「需要補抓」的結論，只是把工具呼叫寫成文字敘述而非結構化的 tool call。此落差指向輸出格式而非理解能力，據此轉查模型參數，A／B 對照確認根因為 `reasoning=False`——原意是讓模型省去推理、直接產出結果，卻連帶壓掉了 tool-calling 能力。排查與修正過程中另發現四項相關缺陷，一併處理。

### 修復

| 項目 | 修復內容 | commit |
|---|---|---|
| 關閉推理模式導致 tool-calling 失效（根因） | 依用途拆成兩個模型實例：`agent` 節點改用不帶 `reasoning=False` 的 `_tool_llm`，其餘節點沿用 `_base_llm`。`agent` 的輸出不進使用者可見的串流（前端只放行 `generate` 的 token）。 | `41ac2ec` |
| 模型無從判斷資料新舊 | prompt 從未提供當日日期，模型讀得出「2026-07-12」卻無法判斷距今多久。`_seed_prompt` 與 `search_knowledge_base` 的回傳都補上今天日期，並為每筆資料預先算好「距今 N 天」，讓模型不需自行做日期運算。 | `41ac2ec` |
| 財報天數被誤當新聞時效 | 工具呼叫恢復後才顯現：檢索摘要把財報（57 天）與新聞（3 天）混列，模型分不出該依哪個數字判斷，導致資料夠新時也觸發補抓。摘要改為每筆標示「財報｜」或「新聞｜」，開頭直接給出「目前最新的『新聞』距今 N 天」；tool 說明同步改為只依這個數字判斷，並註明財報按季發布、距今數十天屬正常。 | `41ac2ec` |
| `doc_type` 參數被填入多值 | 模型會傳 `"financial_report,news"`，但該參數只接受單一值，照字面過濾會查出空結果。tool 說明明確限定可填值並說明「想兩種都查就留空」，同時在 tool 內部容錯：非單一合法值一律降級為不過濾。 | `41ac2ec` |
| 容器時區為 UTC，日期偏移一天 | 容器未設時區，比台北時間慢 8 小時，台灣半夜 0-8 點期間整個系統認定的「今天」會少一天，使新增的「距今 N 天」全面偏移，也會影響 MOPS 民國年計算跨年時的年度判斷。`docker-compose.yml` 為三個服務設定 `TZ`（可用環境變數覆寫）。 | `41ac2ec` |

### 驗證

自動化測試補上距今天數計算、摘要標示與 `doc_type` 容錯的斷言，11 個測試檔全數通過。模型是否依說明決策無法自動化斷言，另以端到端測試（真實 Ollama + MCP + pgvector）驗證，兩情境各連續執行三次確認穩定：

| 情境 | 摘要開頭 | 決策 | 結果 |
|---|---|---|---|
| 資料過期（MSFT，提問含「最新」） | 最新「新聞」距今 58 天 | 呼叫 `fetch_company_data` | ✅ 3/3 一致 |
| 資料足夠（AAPL） | 最新「新聞」距今 3 天 | 停止呼叫工具，直接作答 | ✅ 3/3 一致 |

之所以連續執行而非單次驗收：本次修復過程中曾有一版單次測試通過、重跑三次卻全數失敗，涉及模型行為的修復需以重複執行確認一致性。

---

## 2026-09-08　推理顯示與模型替換評估

### 背景

單題延遲 186 至 470 秒，`agent` 決策與 `generate` 合計佔 97%，瓶頸在本地模型推理。針對此瓶頸評估兩個方向：讓模型顯示推導過程（提升財報問答可信度，串流也能在長等待中提供進度感），以及待辦 2 列為首選的換用更快模型。兩者實測後都不採用，記錄依據以免日後重複評估。

### 一、顯示推理過程

**結論：功能可行但不納入，開啟推理讓單題延遲增為 6.7 倍。**

實作過程中的一個教訓：初始假設「推理段以 `<think>` 標籤內嵌在回覆中，需自行剝除」是錯的，且讓第一版實作失效——據此寫的標籤解析器單元測試全過，卻永遠收不到資料。實際上推理段走 `additional_kwargs["reasoning_content"]` 獨立欄位：未指定 `reasoning` 時模型照樣推理但內容被丟棄，設為 `True` 才會回傳。確認欄位後改為直接讀取，折疊區塊改用 Chainlit `cl.Step` 原生的 `default_open` / `auto_collapse`，不自行拼裝 HTML。

延遲量測（本機 `qwen3.5:9b`，真實 MCP + pgvector）：

| 設定 | `extract_filters` | `generate` | 總耗時 | 答案 | 推理 | 首個 token |
|---|---|---|---|---|---|---|
| 關閉推理（基準） | 5.3s | 86.8s | **186.3s** | 1105 字 | — | 108.7s |
| 全節點開啟 | 422.2s | 104.0s | 660.8s | **0 字** | 3152 字 | 569.3s |
| 僅 `generate` 開啟 | 22.1s | 1052.5s | **1245.3s** | 1425 字 | 30891 字 | 237.6s |

`extract_filters` 只做代號與文件類型抽取，卻在開推理後從 5.3 秒變成 422 秒——不是這個節點本身慢（關閉推理時它只佔單題耗時的 3%），而是讓模型為一件不需要判斷的事去推理，代價完全不成比例。該組答案為 0 字則是另一個問題：Ollama 預設 `num_ctx` 為 4096，RAG prompt 加上推理即塞滿，答案被擠成空字串。加大到 16384 可解，但模型不再受限後為一句營收提問寫了 30891 字推理（答案的 21 倍），`generate` 隨之慢了 12 倍。體感延遲同樣未改善——關閉推理 108.7 秒就看得到答案，開啟後首個推理字元要等 237.6 秒。

壓制推理長度的兩條路徑均無效：`reasoning='low'` 的推理字數與 `True` 完全相同（層級控制僅 `gpt-oss` 支援）；`num_predict` 限制的是總輸出，而推理永遠先於答案產生，設 600 時答案再次被截為 0 字（`done_reason=length`）。

### 二、替換模型

**結論：`qwen3.5:9b` 是這台 M1／16GB 上唯一可用的模型，換模型救不了延遲。** 較小的模型省下的時間有限，卻先失去 tool calling 與結構化輸出這兩項核心能力；MLX 版本在此機器上更慢。限制來自硬體容量與記憶體頻寬，與架構無關。

每情境三次，沿用本日「補資料決策失效修復」的驗證情境（序列執行避免互搶資源）：

| 模型 | 大小 | 單題耗時 | 資料過期→應補抓 | 結構化輸出 |
|---|---|---|---|---|
| `qwen3.5:9b` | 6.6GB | 186s | 3/3 正確 | 正常 |
| `qwen3.5:4b` | 3.4GB | 140s | **0/3** | 正常 |
| `qwen3.5:4b-mlx` | 4.0GB | 278s | 1/3 | **3/3 失敗** |
| `qwen3.5:9b-mlx` | 9.1GB | 逾一小時未完成 | — | — |

`4b` 只快 25%，卻完全不發 tool call，資料停在兩個月前仍直接作答——正是本日前一節修好的那個退化（它在「資料夠新」情境全數通過是假訊號，該情境的正確行為本就是不呼叫工具）。`4b-mlx` 則連 `extract_filters` 都三次全數解析失敗，模型把 JSON 寫成 markdown 條列並附說明文字，降級機制雖正常運作但過濾條件已失效。

MLX 沒有優勢這點值得單獨說明，因為「Apple 原生框架應該更快」是個合理但錯誤的直覺。`9b-mlx` 失敗的原因是容量而非框架——nvfp4 量化需 9.1GB，加上 embedding 模型後超出 16GB 實體記憶體，swap 一度達 23GB，量到的其實是磁碟分頁速度。排除容量因素後的公平比較（同為 4GB 級距、不觸發 swap）中，`4b-mlx` 仍比 `4b` 慢一倍。既然同一份權重在 Ollama 下已落後，改用 MLX-LM 框架不具效益，而其代價包含改用 `langchain-openai`、host 額外常駐服務，以及 `reasoning` 參數在 OpenAI 介面沒有對應而需重新驗證 tool calling。

### 改動內容

| 項目 | 改動說明 | commit |
|---|---|---|
| 維持 `reasoning=False` | `src/graph.py` 的註解改為記錄實測數據與已排除的方案。此限制源於模型的推理成本而非架構。 | `ca4d857` |
| 移除失效的防護程式碼 | `src/app.py` 過濾 `<think>` 標籤的邏輯，原作為「`reasoning=False` 失效時的保險」。但它只作用於 `generate` 的串流，而該節點的 `_base_llm` 已關閉推理；唯一未指定 `reasoning` 的 `_tool_llm` 輸出不進使用者可見的串流。此分支永遠不會執行。 | `ca4d857` |
| UI 模型選單 | 設定面板新增模型下拉選單。`graph.py` 的模型實例從模組層級改為 `_llms(model)` 工廠（`lru_cache` 快取），`GraphState` 新增 `model` 欄位，各節點以 `_model_of(state)` 取值、未帶值時退回預設。不改動全域狀態，多個 session 選用不同模型不會互相干擾。 | `b1da9ea` |
| 候選模型清單 | `LLM_MODEL_CHOICES` 只列預設模型，可用環境變數擴充；實測不合格的模型已從 Ollama 移除。 | `b1da9ea` |

### 驗證

6 個測試檔與雙語字串鍵值對照全數通過，新增 `tests/test_model_select.py` 涵蓋空值退回預設、預設模型必在選單首位、重複項去重。容器重建後確認 Chainlit 正常提供服務、選單只列出預設模型。

### 對待辦 2 的影響

「換更快的模型或量化版本」原列為降低延遲的首選方向，經本次實測後排除。剩餘可行方向為縮短 `generate` 的 prompt 與輸出長度，或改用推理速度更高的硬體。

---

## 待補紀錄

後續每次修復或有新決策時，於本檔案新增一節（日期 + 標題），保留「做了什麼／為什麼／取捨」，不需重複貼完整程式碼片段，指向檔案路徑或函式名即可。新完成的修復項目同時要移出「目前待辦」或「保持現狀」區塊。
