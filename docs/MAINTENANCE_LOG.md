# 維護歷程

紀錄專案已知的技術債、優化候選項與決策依據。重點不只在「做了什麼」，也在「為什麼這樣取捨」與「什麼是已知但刻意延後的」。

---

## 專案狀態

核心問答流程（檢索＋補抓＋生成，涵蓋台股／美股雙市場、雙掛牌比較、決策卡格式驗證、AI 執行可觀測性）已完成並通過端到端驗證，功能面已足以作為 demo。目前進入收尾階段，待辦收斂為對外呈現與雙掛牌引用／換算判定的修正，其餘已知限制與評估過的優化候選見下方對應區塊。

## 待辦

1. **靜態互動式 demo 重播頁**（`README.md:12-13`、`:136-137` 目前為 TODO）
   挑 3-5 題真實問答做成可點選重播的單頁（節點進度、答案、`[來源N]`、圖表），完成後補上 README 的 Demo／Screenshot 區塊。對外門面缺漏、零前置條件、做完就結束。
2. **11k token 的 prompt 光讀就要約 130～143 秒，下一步是量化各段 prompt 的 token 數**
   先記錄 prompt 各段落的 token 數，再決定縮短哪段，不接受不量測直接動手砍；KV cache 是否有幫助也要實測驗證，另寫計畫。詳見 2026-10-07 章節第三節。
3. **雙掛牌比較題的日期對齊、共識預估誤用、換算方向說錯需查**
   eps2 回答期間台股 EPS 取檢索文件、ADR EPS 取行情快照，兩者可能不同期；曾把下一季共識預估當實際 EPS；曾把換算方向說反（講成「ADR EPS 乘以 5」，應除以 5 再乘匯率）；eps3 把 ADR 股價的台幣等值講得像 EPS。詳見 2026-10-07 章節第四節。

## 已知限制

- **回應延遲 186 至 470 秒，首字延遲（TTFT）量不到**（`generate` 節點）——本機約每秒 10 字，剩下的槓桿是輸出量；TTFT 要改節點內部才量得到。詳見 2026-09-17、09-19 章節。
- **LLM 選用 tool 的正確性沒有自動化測試**（`_tool_llm`）——模型行為不保證重現，只能靠端到端手動驗證多次。詳見 2026-09-08 章節。
- **`market IS NULL` 殘留 165 筆**——cmoney 137 筆需重抓才能修；udn／cnyes 28 筆來自未納管版面。詳見 2026-09-21 章節第五節。
- **`_select_exhibit` 取最大 htm 的啟發式**（`src/update.py`）——還沒誤挑過，有入庫字數警示當後備防線。詳見 2026-09-09 章節。
- **mcp-server 不對外開 port**——只有 `app` 經 docker 內部網路連入，Bearer token 已備，有外部 client 需求時再開。詳見 2026-09-19 章節第十節。
- **`[即時市場數據]` 自創引用標記（觀測中）**——既有行為、低優先，`check_answer_format` 已可計數。詳見 2026-09-21 章節第十二節。

## 後續方向

- **golden set（共同前置）→ chunk 策略擴充＋數字類查詢直答通道**——沒有檢索品質數字，選不出 chunk 參數，也驗不出改動成效。規格與兩項的評估詳見 2026-09-21 章節第十節。
- **按來源重跑 ingest**（不在收尾範圍）——單一標的可手動用 `python -m src.update report --market us|tw --company X` 重抓（寫入前會先 `delete_by_source`）；缺的是批次分派與本地 PDF 來源。詳見 2026-09-21 章節第九節。
- **補抓變慢的兩個假設（GIL／Ollama 排隊）**——觀測點已上線，等 log 累積後再驗證。詳見 2026-09-24 章節。

## 已評估不採用

| 項目 | 結論 | 觸發條件 | 詳見 |
|---|---|---|---|
| 跨來源標題相似度去重 | 新來源與 Yahoo RSS 覆蓋面互斥，重複率預期極低，現無樣本可量 | 庫內出現實際跨來源重複樣本，或新增第三個台股新聞來源 | 2026-09-21 |
| 新聞定時排程 | 維持查詢驅動；專案非常駐、會與前台查詢搶 Ollama | 使用形態改為常駐服務或部署正式環境持續運行 | 2026-09-21 |
| 單一公司內來源補抓改為並行 | 實得 14.2s（21%），卡在收益太小不是做法 | 使用者反映難等，或 embedding 佔比顯著下降 | 2026-09-19 |
| logfile 保留策略 | 維持 30 天，個資與磁碟量皆量測過無需校準 | 要記錄 prompt／回應全文，或日檔達 GB 等級 | 2026-09-20 |
| `answer_shape` 誤判率 | 預設 `full` 成立，26 題標註無誤判 | log 出現 news 題被誤判成 full | 2026-09-20 |
| 領域微調 Embedding／Cross-Encoder 重排 | 病因不存在／延遲代價過高，離題攔截改由 LLM 意圖分類解決 | 語料跨足多領域，或硬體推理速度足夠 | 2026-09-10 |
| 異質文檔重排與配額控制 | 跨來源重排前提不成立，配額已對應決策卡必填欄位 | — | 2026-09-10 |
| Redis 取代程序內 query embedding 快取 | 單程序架構下跨程序共享收不到額外命中 | MCP server 跑多 worker，或快取要跨重啟存活 | 2026-09-13 |
| 單一 SQL 用 `UNION ALL` 取回三段檢索 | SQL 條件邏輯難維護，連線佔用本身非問題 | — | 2026-09-13 |
| 改用 async DB driver 取代 ThreadPoolExecutor | 影響面遠大於收益，並行效益幅度小 | — | 2026-09-13 |
| `generate` 節點內部改用 `.stream()` | 逐 token 顯示早已生效，改了收益為零 | 下次要動生成延遲、需要 TTFT 時先做此項 | 2026-09-19 |
| 收緊 tool 呼叫輪數上限 | 維持 4，輪數全落在 1 或 3，上限從未被觸及 | log 出現實際達到上限的題目 | 2026-09-19 |
| `extract_filters` 換用較小模型 | 維持 9b，4b 的 `companies` 欄正確率不合格 | 候選模型須先通過 `companies` 欄 | 2026-09-19 |
| MOPS 爬蟲改用 Playwright | 端點是純表單 POST，換工具不提升穩定性 | MOPS 移除直連表單端點 | 2026-09-04、09-09 |
| 決策卡 `## 📈` 改用非 emoji 標記 | 解析不依賴 emoji，無穩定性問題 | post-check 要擴大到標題層級 | 2026-09-17、09-19 |
| `_retrieve_sequential` 無 company 早退時補強 | 實測皆回滿 5 筆、市場正確，撈空前提不成立 | 實際出現撈空案例 | 2026-09-21 |
| `CHUNK_SIZE` 單位不一致 | 機制（開關、切法出處欄位）已備，候選值分不出優劣 | golden set 到位，或正式環境出現實際截斷 | 2026-09-20、09-21 |
| 補抓軌別拆成獨立 MCP tool | 拆分早已完成，再拆每一軌省不到主成本 | log 量到不必要軌別的浪費佔比 | 2026-09-21 |
| 雙掛牌對照表改為 API 查詢＋落地快取 | 現況非四檔而是 11 檔帶業務判定，API 化只解掉一半 | 主表檔數成長到人工維護吃力，或找到完整端點 | 2026-09-21 |

---

## 2026-09-02　依賴版本 / 架構優化評估

評估 8 項架構優化候選，一項於本日修復，其餘落入「目前待辦」與「已評估不採用」。

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
| Ticker regex fallback 誤判 | 治本而非修 regex：`extract_filters` 從手寫 prompt + `json.loads` 改用 `with_structured_output(ExtractedFilters)`，代號由 Pydantic `field_validator` 呼叫新增的 `normalize_ticker()` 正規化（去除 `.TW`/`.PR.A` 等後綴並驗證格式）。原本的 regex fallback（純英文問題會誤抓一般單字當 ticker）直接移除；多標的問題當時改為回報錯誤而非硬猜一個代號（該降級已於 2026-09-16 由多標的支援取代）。同時修正三處既有的 `isdigit() and len==4` 台股判斷——ETF 新制 6 碼、特別股與可轉債的字母尾碼會被誤判成美股，統一改用 `is_tw_ticker()`。 | `2a00991` |

---

## 2026-09-04　靜默選錯修正：MOPS 財報選檔、Rewrite 追問誤判

兩項各自獨立、皆屬「靜默選錯」而非報錯的準確度缺陷。

### 一、MOPS 固定選到英文版財報

「MOPS 爬蟲脆弱性」在 09-02 被列為保持現狀，本次重新檢視時評估改用 Playwright 的提案，結論為不採用（理由見上方「已評估不採用」）。但評估過程中向端點送出真實請求（2330，115 年），發現同一季度會同時列出 `_AI1.pdf`（中文主文）與 `_AIA.pdf`（英文版），而原本的 `sorted(files)[-1]` 依字典序排序、`'AIA' > 'AI1'`，導致每次固定選到英文版——系統性錯誤而非偶發，且與中文財經助理的定位不符。

**未變動範圍**：爬蟲本體仍依賴網站當前頁面結構，改版仍會失效。這次只修正選檔語言，不是解決該結構性限制。

### 二、Rewrite regex bypass 誤判追問

`rewrite_question` 在有歷史時會把追問改寫成獨立問題（「那毛利率呢？」→「台積電的毛利率是多少？」），改寫前有一段 regex bypass：出現 4 位數字或 2-5 碼大寫字母就視為已指名代號、跳過改寫。它會誤判兩類仍依賴上下文的追問——「2024 年的營收呢？」被 `\d{4}` 當成台股代號，「ROE 表現如何？」被 `[A-Z]{2,5}` 當成美股 ticker。用真實 Ollama 驗證兩句都會觸發 bypass，非純理論風險。

### 修復

| 項目 | 修復內容 | commit |
|---|---|---|
| MOPS 財報誤選英文版 | `update.py` 新增 `_select_report_file()` 取代 `sorted(files)[-1]`：先篩最新月份，該月份內優先選 `_AI1.pdf`，選到非中文主文時印告警不靜默降級。新增 `tests/test_update.py`，用實測取得的真實檔名組合覆蓋五種情境。 | `36c6cdf` |
| Rewrite regex bypass 誤判追問 | 拿掉 `graph.py` 的 regex bypass，有歷史時一律呼叫 LLM 改寫；prompt 已寫明「若問題本身已獨立完整，原樣輸出即可」，完整問題不會被改壞。代價是每輪有歷史的對話固定多跑一次 LLM。 | `f2ff695` |

---

## 2026-09-07　MCP tool-calling 架構改造：補資料決策交給 LLM

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

## 2026-09-08　改造後的退化收斂：補資料決策修復、推理顯示與模型替換評估

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

這類公司不申報 10-Q/10-K，既有的 6-K fallback 卻涵蓋任何重大公告（股利、AGM、月營收），「取最新一份」偶爾會抓到非財報。原想讀 `items` 與 `primaryDocDescription` 辨識性質，取樣後推翻——兩欄位對 6-K 全為空。改採 `reportDate`：財報的報導期末與申報日不同，公告類則填當天；再加「月份需為 3/6/9/12」才排除得掉 TSM 的月營收，且不影響 ASML 的 52/53 週制期末。更嚴重的是**6-K 的主文件只是封面頁**，本文在同一份申報的 exhibit，即使選對申報也幾乎從未匯入可用文字（ASML 由 2,265 字元變 65k）。**已知限制**：「取最大的 exhibit」是啟發式，理論上可能挑到投影片，誤挑再改解析索引的類型標籤。**該升級路徑後續實測並不成立**：以優先選 `EX-99.1` 為例，ASML 樣本中 `EX-99.1` 其實是新聞稿、`EX-99.2` 才是投影片，真正的財報是 `EX-99.4`——改用類型標籤反而比「取最大」更差，故維持現行啟發式，尚未實際誤挑過，`ingest_text` 的入庫字數警示已是後備防線。

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

| 項目 | 涉及檔案與函式 | commit |
|---|---|---|
| 標注評估 | 新增 `tests/eval_data/rag_annotations.json` 與 `tests/eval_rag_retrieval.py` | `65b1ba9` |
| 離題攔截 | `graph.py` 新增 `_is_off_topic`；`i18n.py` 補 `off_topic` 文案；新增 `tests/test_off_topic.py` | `233a509` |
| 放寬告知 | `mcp_server.py` 的 header 補提示 | `37d5075` |
| `resolve_market` 防禦性修補 | 對 `state["question"]` 硬取值改用 `.get()` | `36c9511` |
| 補充新聞未排除自家公司（時效歸屬污染／市場新聞恆為 0-2 筆） | `mcp_server.py` 計算最新新聞天數時只納入查詢公司自身新聞，避免 header 報錯新鮮度、誘導模型跳過補抓；`retrieve_context` 補充段改為排除查詢公司自身、依發布日期排序，`similarity_search` 新增 `exclude_company`（`IS DISTINCT FROM`，避免 `!=` 漏掉 NULL）與 `order_by_recency` | `65b1ba9` |
| 退回封面頁靜默視為成功 | `_fetch_edgar` 目錄讀取失敗退回主文時，回傳 `FetchResult(ok=False)` 而非靜默成功；封面頁字數足以通過 `_MIN_FILING_CHARS`，屬同區域既有缺陷、非本次肇因 | `65b1ba9` |
| 入庫字數警示 | `ingest.py` 的 `ingest_text()` 新增 `_MIN_FINANCIAL_REPORT_CHARS`；新增 `tests/test_ingest.py` | `a1baa73` |
| 架構圖同步 | 依 `draw_mermaid()` 重新產生 `README.md`、`docs/PROJECT.md`、`docs/AI_Product_Case_Study.md` 的中英架構圖 | `fe1e915` |
| 文字版節點流程同步 | 同檔的中英純文字流程仍停在 `retrieve` 獨立節點，改為 `resolve_market → agent ⇄ tools → assemble`：檢索已是 agent 呼叫的 MCP tool，資料是否足夠改由模型判斷（詳見 2026-09-07 章節） | `5c89749` |
| ASML 財報重抓 | 沿用 `ingest_text` 的 `delete_by_source` 覆蓋重抓：5 chunk／2,923 字元 → 104 chunk／73,234 字元 | `—` |

---

## 2026-09-13　AI 可觀測性：logging 落地、檢索平行化與效能實測

同一條線：先讓 AI 行為可計時落檔，才有依據動檢索；平行化與快取則以開關讓兩條路徑並存，A/B 實測後推翻了連線池會成為瓶頸的推導。

### 從 `print` 改為 logging，AI 行為每日落檔

AI 路徑原有 9 處 `print`（`graph.py` 8、`mcp_server.py` 1），無時間戳、只進 stdout，而 `docker logs` 有輪替上限、容器重啟即失去歷史——**無法回答「上週那一題為什麼跑了 400 秒」**，對一個以本地模型生成為瓶頸的專案等於放棄優化依據。

改用標準庫 `logging` 輸出 JSON Lines 到已掛載的 `data/logs/`，四個 LLM 呼叫點與 `retrieve_context` 各記 `elapsed_ms`，同一題以 `qid` 串連（設定細節見改動內容表）。**只記長度不記內容**，避免把提問寫進 log（保留策略未定前不落地個資，見待辦的「logfile 保留策略與敏感資料」一項）。

### 檢索平行化與 query embedding 快取

`retrieve_context()` 原本依序執行主檢索、同公司新聞補充與市場新聞補充；agent 在同一題的 tool loop 重查時，又會對相同 question 重複呼叫 Ollama embedding（把文字轉成向量的服務，每次一趟網路往返）。改為程序內、有界的 TTL/LRU 快取（`EMBEDDING_CACHE_MAX_ENTRIES`／`EMBEDDING_CACHE_TTL_SECONDS`，設 0 關閉），加上候選檢索預取：有 company 時三段同時送出，待主結果確定後才依原有條件採用候選。行為維持不變——`doc_type` 放寬仍只在主檢索為空時執行，來源順序與配額照舊。

**取捨**：快取讓同一題的重複檢索幾乎免費，代價是答案在 TTL 內對同一字面問題不反映新入庫的資料——以本專案的入庫頻率（每日批次）判斷可接受。

### 檢索效能實測

`RETRIEVE_PARALLEL` 開關（`src/config.py`）讓 `tests/bench_retrieve.py` 能在**同一個 image、同一個容器、同一批資料**上切換行為做 A/B。六題輪替、每組 7 次取中位數。

| 組合 | 中位數 | 最小 | 最大 |
|---|---|---|---|
| 循序 + 無快取 | 236.5 ms | 198.5 | 263.6 |
| 循序 + 有快取 | 24.6 ms | 17.4 | 35.5 |
| 並行 + 無快取 | 202.5 ms | 198.1 | 215.1 |
| 並行 + 有快取 | **11.5 ms** | 9.3 | 19.1 |

每次 `embed_query` 都要打一趟 Ollama，而檢索本身只是幾條 SQL，故貢獻幾乎全來自快取；並行的幅度小但離散度較低。兩條路徑回傳的 chunk id 序列完全相同。

**連線池 `max_size` 維持 5。** 三段並行各借 1 條連線、pool 又是模組級單例，**推導**上兩個並行檢索就會超額並在 `timeout=2` 後拋 `PoolTimeout`。實測相反：壓到 8、12、20 個並行（理論上需 24、36、60 條連線）在 `max_size=5` 下仍零失敗。前提錯在每段 `similarity_search` 只持有連線數毫秒即歸還，連線快速輪轉而非被三段長期佔住，「3 × 並行數」的推估不適用。

端到端延遲仍以生成為主，這數十毫秒對體感沒有可觀察的影響。保留 `RETRIEVE_PARALLEL=0` 是為了 DB 端競爭情況改變時能直接重測與回退而不必改程式；為避免兩條路徑各自腐化，採用條件與順序抽成 `_relax_doc_type()` 與 `_merge_market_news()` 共用。

### 改動內容

| 項目 | 涉及檔案與函式 | commit |
|---|---|---|
| logging 設定與 JSONL formatter | 新增 `src/logging_setup.py`（`setup_logging`／`log_duration`）。用標準庫而非 structlog／loguru：`extra` 加一個 JSON formatter 就夠。保留 `StreamHandler` 使 `docker logs` 行為不變；輪替用 `TimedRotatingFileHandler(when="midnight")`，`RotatingFileHandler` 的 `.1`／`.2` 序號對不回日期。兩服務各寫各的檔，避免切檔互相覆蓋 | `f6f5de8` |
| AI 路徑 9 處 `print` 遷移、四個 LLM 呼叫點計時 | `src/graph.py`（`rewrite_question`／`extract_filters`／`agent`／`generate`）、`src/mcp_server.py`、`src/app.py`。以 `qid`（問題文字短 hash）串連，因 `GraphState` 沒有 `thread_id`；`generate` 另記 `prompt_chars`／`answer_chars` 以區分「慢在輸入還是輸出」 | `f6f5de8` |
| logging 設定項 | `config.LOG_LEVEL`／`LOG_DIR`／`LOG_BACKUP_DAYS` | `f6f5de8` |
| query embedding 快取 | `graph.py` 的 `_embed_query_cached`；`config.EMBEDDING_CACHE_MAX_ENTRIES`／`EMBEDDING_CACHE_TTL_SECONDS` | `f6f5de8` |
| 容器外執行改寫 `-local` 檔名 | `logging_setup.py` 的 `_log_name()`，以 `/.dockerenv` 判斷執行環境 | `bb64c4f` |
| 檢索並行開關與路徑拆分 | `config.RETRIEVE_PARALLEL`；`graph.py` 的 `_retrieve_parallel`／`_retrieve_sequential`／`_relax_doc_type`／`_merge_market_news` | `f4d398c` |
| 量測腳本 | 新增 `tests/bench_retrieve.py`（需在 container 內執行，DB 未對 host 開 port） | `74789e9` |
| 新增 self-check | `tests/test_logging_setup.py`；`tests/test_retrieve_context.py` 補等價性、快取關閉、embed 失敗不污染快取、並行分支例外傳遞。等價性測試以故障注入驗證過有鑑別力（破壞去重邏輯會被抓到） | `f6f5de8`／`f4d398c` |

---

## 2026-09-14　AI 可觀測性延伸：抓取路徑紀錄修正與自架 Langfuse 追蹤

同一條可觀測性線的兩段：先把剩下的抓取路徑儀器化並修掉一個讓紀錄失真的判準錯誤，再接上 Langfuse 補足 logfile 答不出的 prompt／token 層級。

### 抓取路徑可觀測性修正

剩餘的 `print` 原被歸類為 CLI 進度輸出，但依呼叫端重新分類後，50 處中約 39 處其實會在服務請求中執行——這不是低優先的 CLI 清理，而是 09-13 儀器化未完成的另一半。

同時修掉一個更根本的缺陷：**`fetch_missing_data` 以「沒拋例外」為成功判準，但 fetcher 的失敗多半不拋例外。** 查無 CIK、官方 OpenAPI 查無公司、MOPS 版面改版都是正常返回 `FetchResult(False, msg)`，因此 logfile 裡「補抓成功」從未為真過，回測時分不出補抓究竟成功幾次。

`reason` 一律用短代碼（`no_cik`／`api_miss`／`mops_blocked` 等）而非自由文字，否則 `jq` 彙總不動——回測要問的是「哪一類失敗最多」。另有兩處是**降級**而非失敗：`cover_only`（6-K 退回封面頁）與 `no_chinese_doc`（MOPS 改抓替代檔）；後者仍回 `ok=True` 而內容是替代檔，logfile 是唯一能保留這個區別的地方。

**已知限制**：只改紀錄的正確性，未改變任何抓取行為；補抓成功率要等實際使用累積後才答得出來（門檻見待辦的「AI 執行時間的持續觀測與回測」一項）。

### 接上自架 Langfuse 與節點層級追蹤

logfile 已能回答「哪個節點花了多久」，但答不出「送進模型的 prompt 長什麼樣、模型回了什麼、花了多少 token」。Langfuse 是自架的 LLM 追蹤平台，這層內容留在自己機器上，不必把提問送進第三方服務。掛載點只有一處：`app.py` 的 `_stream_answer` 呼叫 `graph.astream` 時把官方 SDK 的 LangChain callback handler 放進 `config`。

**追蹤失敗不得影響問答**：`tracing.py` 的進入點全部吞例外，初始化失敗只記一次 warning 後靜默跳過，`callbacks()` 退化成回傳 `{}`。未設 `LANGFUSE_PUBLIC_KEY` 即視為關閉，CI 與剛 clone 的專案不必有金鑰也能跑。

**兩個容器限制**：Langfuse 只綁 `127.0.0.1:18300`，容器內的 `localhost` 指向容器自己（實測 `Connection refused`），改用 `host.docker.internal` 則回 200；映像檔裡沒有 `.git`，`_release()` 取不到版本會讓所有 trace 的 `release` 成為 `unknown`，改由 compose 以 `LANGFUSE_RELEASE` 帶入。

**原假設被實測推翻**：原以為 handler 會跟著 graph 往下傳、四個 LLM 呼叫點自動成為同一 trace 的 observation。實際上 handler 記錄的是 LangChain runnable（模型呼叫）而非 LangGraph 節點——UI 上只看得到底層 ChatOllama 呼叫，而 `resolve_market`／`assemble`／`no_result` 這類不呼叫 LLM 的節點根本不會出現。SDK 的 `@observe` 亦不可用：span 在函式回傳當下就結束，之後的寫入落到父層，成為「每個節點 output 都一樣」的成因。最後由 `build_graph()` 改用 `node_span()` 逐一包住九個節點，LLM generation 靠 OTel context 掛在所屬節點底下，形成「一次問答一個 trace、每節點一個 span」。

**取捨**：節點 input/output 送 `_brief()` 摘要而非完整 `GraphState`——長字串截至 500 字，`retrieved`／`messages` 只留筆數。代價是 UI 看不到 chunk 全文（要看全文回 logfile），換得單一節點 span 從 22,485 bytes 降到 605 bytes（七筆 chunk、1,200 字回答實測）。

**驗收**：實跑一次 `qwen3.5:9b` 問答，trace 記錄到 input、output、`user_id`／`session_id`／`tags`／`environment`，延遲 23,871 ms，token input 21／output 33。**已知限制**：span 樹結構以 OTel in-memory exporter 驗證，未經 Langfuse UI 目視確認。

### 改動內容

| 項目 | 涉及檔案與函式 | commit |
|---|---|---|
| `auto_fetch` 成敗判準修正 | `graph.py` 的 `fetch_missing_data`：接住 `FetchResult` 再取 `.ok`，取代「沒拋例外即成功」 | `ddd40f5` |
| 六個 fetcher 的失敗訊息遷移 | `update.py` 的 `fetch_edgar`／`fetch_sec_financials`／`fetch_tw_financials`／`fetch_mops`／`fetch_news`／`fetch_market_news`，共 15 處 | `6b194b3` |
| 降級路徑改為具名警示 | `update.py`：6-K 退回封面頁記 `cover_only`、MOPS 替代檔記 `no_chinese_doc`。後者回傳 `ok=True`，不記則無從得知內容是替代檔 | `6b194b3` |
| 決策卡圖表與行情快照 | `charts.py`（5 處，`price_chart`／`eps_chart`／`report_pdf`）、`market.py`（4 處，`format_consensus`／`get_market_snapshot`）。`market.py` 帶 `symbol` 而非 `company`，因 `format_consensus` 收到的是 yfinance ticker 物件 | `6b194b3` |
| 入庫警示與進度 | `ingest.py` 的 `ingest_text`：空內容與財報字數偏低改 `log.warning`，chunk 數與寫入筆數改 `log.info` | `6b194b3` |
| self-check 改收 log record | `tests/test_ingest.py` 原以 `redirect_stdout` 攔截財報字數警示，改走 logging 後攔不到，改為掛 handler 收 `LogRecord` | `6b194b3` |
| 追蹤模組 | 新增 `src/tracing.py`（`callbacks`／`flush`／`_release`／`_get_client`）。用官方 SDK 的 `langfuse.langchain.CallbackHandler` 而非手刻 HTTP | `9911e3f` |
| handler 掛載與 metadata | `src/app.py` 的 `_stream_answer`：`session_id` 取 chainlit 的 `thread_id`（同一串對話在 UI 才收得在一起）、`user_id` 取 OAuth `identifier`，未登入或拿不到仍能追蹤 | `9911e3f` |
| CLI 的 flush | `src/cli.py`：短生命週期程序結束前須 `flush()`，否則最後幾輪 trace 隨程序消失。長駐的 chainlit 靠 SDK 背景批次，不呼叫 | `9911e3f` |
| 設定項 | `config.LANGFUSE_ENABLED`（總開關）／`LANGFUSE_RELEASE`；金鑰只進 `.env`（已在 `.gitignore`），`.env.example` 留空欄位與容器內外兩種 base_url 的說明 | `9911e3f` |
| 容器版本歸因 | `docker-compose.yml` 的 `app` 服務加 `LANGFUSE_RELEASE`，補上映像檔內無 `.git` 導致的 `unknown` | `9911e3f` |
| 相依套件 | `requirements.txt` 加 `langfuse>=4,<5` | `9911e3f` |
| 節點包裝 | `src/tracing.py` 新增 `node_span()`／`_brief()`／`_MAX_IO_CHARS`。不用 SDK 的 `@observe`（span 提早關閉，見上），改用 `client.start_as_current_observation()` 自行開關 | `822834f` |
| 九個節點掛上 span | `src/graph.py` 的 `build_graph()`：包在 `add_node()` 而非裝飾函式，避免 `route_after_tools()` 內部呼叫 `assemble()` 時產生多餘 span | `822834f` |
| self-check | 新增 `tests/test_tracing.py`：驗關閉時回空 config、初始化失敗時不拋例外、metadata 帶齊 session／user／release／tags 且 None 欄位被濾掉；並補驗截斷上限、`retrieved`／`messages` 只留筆數、關閉時原樣回傳、`functools.wraps` 保留節點名（名稱錯誤會讓 span 名變成 `wrapper`） | `9911e3f`／`822834f` |
| CLI 無法啟動修復 | `src/cli.py`：`build_graph()` 於 `ef76670` 改為 async 後未同步更新，`python -m src.cli` 啟動即 `AttributeError`。僅 await 不足——`agent` 節點本身也是 async，同步 `.invoke()` 會拋 `No synchronous function provided`，故 `main()` 改 async 並改用 `ainvoke()` | `135c674` |

---

## 2026-09-16　多標的查詢支援：抽取改為多值、分次檢索結果覆蓋修復

原本問「AAPL 和 TSLA 比較」時，抽取器偵測到多間公司會回 `status="error"` 並降級為「不指定公司」檢索。實際追查發現情況比原紀錄更糟：`status` 全專案只有一行 `log.info` 消費，沒有任何分支、也沒有任何使用者可見訊息——降級後跨全庫檢索會拿別家公司的片段拼出一個看似合理的比較答案，使用者無從得知過濾已經失效。

**做法是把既有機制推廣，而非新增一條路徑。** `market="both"`（台美雙掛牌「兩邊都要」）早就會引導 agent「分別以 X 與 Y 各檢索一次」，這正是多標的需要的行為。因此 `ExtractedFilters.company: str | None` 改為 `companies: list[str]`（附正規化與去重的 validator，認不得的代號直接丟掉），prompt 刪掉「多公司視為錯誤」那條規則，`status`／`error_message` 兩個欄位連同死碼一併移除；引導語則從雙掛牌專用改為通用的「同時指名多個標的時逐一各檢索一次」。

**原紀錄設想的做法沒有採用。** 待辦原文預期要改 `retrieve_context` 依公司分組、並擴充 MCP tool 的參數定義，但多次檢索由 agent 在 tool loop 裡完成即可——SQL、三段檢索配額（主 5／補公司新聞 3／補市場新聞 2）與 `search_knowledge_base` 的對外簽名全部不動。對外 MCP 契約有外部 client 在用，不為內部需求改動；引用編號邏輯本來就是依出現順序去重，多家公司的來源自然接在後面編號，同樣不必改。

**順帶修掉一個既有 bug**：`assemble` 原本是最後寫入覆蓋，分次檢索的前幾批 chunks 會被靜默丟掉——也就是雙掛牌「兩邊都要」的情境**在此之前一直只拿到一半資料**。改為累積並依 chunk `id` 去重（補抓後重查會拿到相同 id，不去重會讓同一段內容重複進 context）。

**取捨**：多標的時直接略過雙掛牌的市場反問——兩家公司做比較還要先回答「要台股還美股」體感很差，而「雙掛牌 ∩ 多標的」是罕見交集。走勢圖與 ADR 提醒同理，都是單一公司概念，其範圍與重新評估條件見「已評估不採用」對應一條。

> 原文一併把「市場快照留空」列為同性質的取捨。**2026-09-18 推翻**：快照留空會連鎖使決策卡少掉四個欄位且無使用者可見訊息，屬正確性缺陷而非取捨。當時只看到「少一段行情文字」，沒追到 `allowed_fields` 那條依賴鏈。修復詳見 2026-09-18 章節。

**驗收**（容器內 `qwen3.5:9b`，問「AAPL 和 MSFT 最近的營收表現比較」；TSLA 不在庫中，改用兩家都有新鮮資料的標的以免混入外部補抓）：

| 項目 | 多標的 | 單一公司（對照） |
|---|---|---|
| `search_knowledge_base` 呼叫 | 2 次（同一輪並發） | 1 次 |
| 累積 chunks | 13（AAPL 5／MSFT 6／全域市場新聞 2） | 7 |
| 重複 id | 0 | 0 |
| 超出範圍而被砍的引用編號 | 0 | 0 |

13 筆大於單次檢索的 7 筆，是覆蓋 bug 已修好的直接證據；連跑兩次結構數字完全一致。回歸確認「台積電 EPS」仍走雙掛牌反問（`ask_market=True`、`peer_company=TSM`）。

**已知限制**：多標的時本地模型不輸出 `[來源N]` 引用標記（連跑兩次皆為空，單一公司則正常引用 5 個編號）。已排除程式面成因——`generate` 的 prompt 在兩種情境下結構相同、無多標的分支，超出範圍的過濾也一個都沒砍；差別在 context 規模（11 個來源／7,523 字元 vs 7 個來源／4,175 字元），屬本地 9B 模型的能力上限而非本次改動引入。另一個限制是**延遲隨標的數線性增加**：每多一家就多一次檢索（本次實測每次 `retrieve_context` 約 2.7 秒），可由 logfile 的 `qid` + `elapsed_ms` 觀察。未預先調整 `_MAX_TOOL_ROUNDS` 或配額——效能參數要有實測數據才動。

### 改動內容

| 項目 | 涉及檔案與函式 | commit |
|---|---|---|
| 抽取結果改為多值 | `graph.py` 的 `ExtractedFilters`：`company` 改 `companies: list[str]`，新增正規化／去重 validator；移除 `status`／`error_message` 與其唯一消費點（只有一行 log，無任何分支） | `—` |
| 抽取 prompt | `graph.py` 的 `extract_filters`：規則 1 改為輸出代號陣列，刪除「多公司回 error」一條，規則重新編號 | `—` |
| 狀態欄位 | `graph.py` 的 `GraphState.company` 改 `companies`；新增 `_primary()` 供沿用單一公司語意的節點取第一家（`resolve_market`／`ask_market`／`no_result`／`generate` 的快照與 ADR 提醒） | `—` |
| 多標的引導語 | `graph.py` 的 `_seed_prompt`：從雙掛牌專用推廣為通用。`_MAX_TOOL_ROUNDS` 是 agent 輪數上限而非 tool 呼叫數上限，LLM 可在同一輪發多個 `tool_calls`，故未調整（實測 2 家公司即為單輪並發兩次） | `—` |
| 分次檢索結果累積 | `graph.py` 的 `assemble`：改為累積並依 `id` 去重，修正最後寫入覆蓋的既有 bug。JSON 解析失敗記 warning 後視為查無資料，不中斷 | `—` |
| 多標的不卡市場反問 | `graph.py` 的 `resolve_market`：`len(companies) > 1` 時直接跳過雙掛牌流程 | `—` |
| 追蹤欄位白名單 | `tracing.py` 的 `_brief`：`company` 改 `companies` | `—` |
| UI 與 CLI 接線 | `app.py` 四處（初始 state、市場按鈕重跑、`_pick_market`、圖表只畫第一家）、`cli.py` 初始 state | `—` |
| self-check | `tests/test_assemble.py` 增兩條（分次檢索須累積、重複 id 只留一份）、`tests/test_dual_market.py` 增一條（多標的不觸發市場反問）；另五個測試檔隨介面更名同步調整 | `—` |

---

## 2026-09-17　生成延遲優化：決策卡欄位依意圖與證據裁剪

「回應延遲過長」在 09-09 被收斂為硬體限制：生成速度穩定在每秒約 10 字，`generate` 單題 90 至 160 秒，輸入側的架構手段（裁 context、跳過第二輪 agent、並行檢索、embedding 快取）已用盡。這次換角度處理——既然每秒能寫的字數是固定的，剩下的槓桿就是**要寫的字數**本身。

**病因是 schema，不是模型。** 決策卡原本無條件要求 13 個欄位，而 prompt 自己的規則還明文允許其中四欄寫「資料不足」。也就是說問「這則新聞對股價的影響」時，系統正在把最稀缺的資源（輸出 token）花在使用者沒問、語料也支撐不了的欄位裡寫佔位文字。09-09 的字數約束 A/B 失敗（輸出反而變長 35%）正是這個結構的症狀：模型同時被要求「講簡短」和「填滿 13 欄」，兩個指令衝突時 schema 贏。因此把欄位取捨從「請模型自律」搬到**應用層決定**——由純函式 `allowed_fields()` 依使用者意圖與實際檢索結果挑選，未入選的欄位**根本不放進 prompt**——保留欄位描述再加一句「請略過 X、Y」，等於先展示再叫模型忽略，跟失敗的字數約束是同一類指令。

**`answer_shape` 沒有沿用 `doc_type`。** 最省的實作是直接看檢索過濾條件，但 `doc_type` 是資料事實（DB 欄位、檢索過濾、保留策略、MCP 協定四個消費端都吃它），`answer_shape` 是使用者意圖，兩者常相關但不等價——「這則新聞對股價的影響」`doc_type=news` 卻需要估值欄位才答得了。疊在一起會讓 prompt 塑形耦合到儲存 schema，故新增獨立欄位。預設 `"full"`（例外路徑也 fallback 到 `"full"`）依據是代價不對稱：誤判成 `full` 只多幾欄，誤判成 `news` 會砍掉投資題的素材且使用者無從察覺——無聲的品質退化比延遲退化更糟。沿用專案既有慣例 `in_scope: bool = True`。

**行情抓取的循環依賴用三態解。** 吃行情的三欄要不要納入取決於快照抓沒抓到，但值不值得抓又取決於有沒有欄位要用它——而 `get_market_snapshot` 是 blocking 未快取網路呼叫（實測冷啟 2.50 至 3.55 秒），就擋在 first token 前面。`has_market: bool | None` 的 `None` 意為「還沒抓」，樂觀視同可能有：**用 boolean 會自我實現否定**——`False` 抑制那些欄位、`needs_market` 因此為假、行情永遠不會被抓。第二段求值同時關掉另一個失敗模式：抓失敗時那些欄位自動剔除，不會留一個沒素材的空欄逼模型寫「資料不足」。

**「不得整段棄權」改為測試斷言。** `conclusion`／`facts`／`inference`／`upside`／`risk` 五欄在任何形式、任何證據狀態下無條件輸出。寫在註解裡，下一個調 gating 邏輯的人隨時會破壞它，故 `tests/test_allowed_fields.py` 對「形式 × 證據集 × 行情狀態」的完整交叉組合逐一斷言這五欄必然存在。

**取捨**：計時起點前移先獨立 commit（`34cfd5c`）——舊計時器緊貼 LLM 呼叫之前，而行情抓取就發生在那之前、同一節點之內，用它量兩段式的節省會完全看不見。拆開是因為這個修正獨立於 gating 正確，方案若因 A/B 數字不佳被 revert 也該留著。另有一項結構調整刻意未併入，以免把欄位邊界的風險混進效能改動（待辦「決策卡的 `## 📈` 結構邊界改用非 emoji 標記」一項）。`answer_shape` 是對整個問句判定一次的回答形式，與標的數無關——多標的比較題同樣共用一個形式，`allowed_fields` 不讀 `companies`，故不在 09-16 那批「多標的時取第一家」的降級範圍內。

**驗收**（同容器同模型 `qwen3.5:9b`，5 題 × 2 次 × 開關兩組共 20 次，0 失敗；`market` 預先指定以繞過雙掛牌反問，否則 2330 題會停在市場詢問而到不了 `generate`）：

| 題型 | 欄位數 開→關 | 輸出字數 開→關 | 節點總時長 開→關 |
|---|---|---|---|
| news（2 題） | 8 → 13 | 805 → 1,267（**−36.5%**） | 121.4s → 158.8s（**−23.6%**） |
| full（2 題） | 13 → 13 | 691 → 769（−10.1%） | 114.3s → 104.1s（+9.9%） |
| 邊界（1 題） | 11 → 13 | 1,313 → 1,332（−1.4%） | 165.7s → 168.1s（−1.4%） |

**news 題的假設成立：字數降 36.5%，時間同向降 23.6%。** 逐題目視確認被剔除的五欄（估值觀察／市場共識與門檻／情境解讀／法說會關注清單／建議傾向）在輸出中**連欄名都沒出現**，且無「資料不足」佔位；關閉開關時同題同模型則五欄全數出現——這是「不放進 prompt」與「請模型省略」的差別被實際驗證。

**`temperature=0` 下輸出字數完全可重現**：同題同設定連跑兩次字數一模一樣（772／772、1109／1109、837／837、1424／1424）。

**full 與邊界題的差異是雜訊，不是效果。** full 題兩組設定允許的欄位集合完全相同（13 欄，只有排列順序不同），所以字數那 10.1% 的差來自 prompt 欄位順序造成的模型自由度，與 gating 無關；且該題型實際上兩組都沒輸出決策卡、直接回散文。這與計畫預期的「full 題兩組無差異」一致。

**已知限制——時間軸的雜訊底線高達 ±16 至 37%**：同題同設定、**輸出字數完全相同**的兩次執行，節點總時長可以差 91.6s 對 118.9s，單次比較毫無意義。結論之所以仍站得住有三點：字數是確定性的；news 的時間效果在 rep0（−20.0%）與 rep1（−27.8%）**各自獨立成立**；執行順序上 gating=1 固定先跑而 rep0 整體慢約 19s，這個暖機梯度**對 gating=1 不利**，效果仍然存活。要更精確的數字需隨機化順序並加大樣本。**這個節省沒有改變體感的量級**，降低的是總量而非等待感受。

**已知限制**：20 次執行中 `answer_shape` 分類全部正確（邊界題如預期判為 `full`），但 5 題不構成誤判率估計（後續以 28 題標註集驗證，結論見「已評估不採用」的 `answer_shape` 同名項目）。本次以腳本直接驅動 graph、未經 Chainlit，故不寫進 `app-*.log`，待辦「AI 執行時間的持續觀測與回測」的門檻不因本次而推進。

### 改動內容

| 項目 | 涉及檔案與函式 | commit |
|---|---|---|
| 計時起點前移 | `graph.py` 的 `generate`：`time.monotonic()` 從 LLM 呼叫前移到節點開頭，使 `elapsed_ms` 涵蓋 `get_market_snapshot` 這個 blocking 網路呼叫 | `34cfd5c` |
| 回答形式抽取 | `graph.py` 的 `ExtractedFilters` 新增 `answer_shape: Literal["news", "full"] = "full"`；`extract_filters` prompt 新增規則 7（`doc_type` 的規則 2 不動），例外路徑 fallback `"full"` | `afc4981` |
| 欄位決定邏輯 | `graph.py` 新增純函式 `allowed_fields(state, has_market)` 與三個模組常數（`_UNCONDITIONAL_FIELDS` 5 欄／`_FULL_ONLY_FIELDS` 5 欄／`_ALL_FIELDS` 13 欄）；`has_market: bool \| None` 三態，`None` 代表尚未抓取 | `afc4981` |
| 兩段式行情抓取 | `graph.py` 的 `generate`：先算候選集求 `needs_market`，僅在有欄位要用時才抓；抓完以實際結果第二次求值定案 | `afc4981` |
| prompt 逐欄組裝 | `i18n.py`：`trend_section` 單一字串拆為 13 個 `trend_field_<id>` + `trend_header` + `trend_rules_common`（zh／en 各一組，靠 `i18n.py:220` 的 key 對稱斷言把關）；移除「資料不足」佔位字樣與「哪四欄可寫資料不足」的規則。`graph.py` 的 `generate` 改為 `join` 選中欄位 | `afc4981` |
| A/B 開關 | `config.py` 新增 `ANSWER_SHAPE_GATING`（預設開，`=0` 回傳全 13 欄），沿用 `RETRIEVE_PARALLEL` 的慣例 | `afc4981` |
| 追蹤欄位白名單 | `tracing.py` 的 `_brief`：新增 `answer_shape` 與 `allowed_fields`，用於區分「本來就不輸出」與「證據不足被剔除」——否則 gating bug 在 trace 上與檢索 bug 無法區分 | `afc4981` |
| self-check | 新增 `tests/test_allowed_fields.py`（11 條斷言，含 `ANSWER_SHAPE_GATING=False` 的回退路徑，以及對形式 × 證據 × 行情完整交叉組合斷言五個無條件欄位必存在） | `afc4981` |

## 2026-09-18　多標的比較題的行情逐家併陳、比較欄位與補抓決策修復

當日兩件獨立的工作，都由多標的比較題引出：前者補齊行情與比較欄位，後者修掉一條讓補抓決策從未發生的捷徑。後者是在用前者的成果實測三道真實問題時才浮現的，並一路修到底：從「補抓為何從未觸發」往下追出新鮮度判準、財報時效與補抓對象三層問題。

### 一、行情逐家併陳與比較欄位

**病因是誤用既有機制，不是缺功能。** `generate` 原本只抓 `companies[0]` 一家的行情，其餘標的沒有快照，`allowed_fields(has_market=False)` 因而剔除估值觀察／市場共識／情境解讀，連帶建議傾向也一起消失（實測齊備下單一公司 13 欄、多標的只剩 9 欄）。那條剔除路徑是為「yfinance 抓取失敗」設計的降級，多標的根本沒去抓卻走進同一條路徑——**用「資料不足」實作了「我沒拿」**。修法：`market.py` 新增 `get_market_snapshots(companies)`，沿用 `_retrieve_parallel` 既有的 `ThreadPoolExecutor` 形狀，`has_market` 改判為「至少一家成功」，部分失敗沿用 `market_partial_note` 明講哪些標的沒有即時行情。

**單張決策卡、欄內逐家列，而非每家一張卡**——每家一張會讓 13 個欄名重複 N 次、字數翻倍，直接吃掉 09-17 的裁剪效益，且沒有欄位負責「對比」。改 `trend_field_valuation`／`consensus`／`scenario` 三欄文案為逐家分列語氣，新增只在多標的時出現的 `comparison` 欄位承接對比職責。公司名沿用 `ticker.get_info()` 既有的 `longName`／`shortName`，不新造對照表。

**幣別的根因在資料層，不在文案。** 跨市場題把美元數字標成「元」，第一直覺是加文案要求標明幣別，但那等於要求模型從代號推斷計價幣別、是在請求幻覺。`format_snapshot` 從未輸出幣別，而 `info.currency` 兩個市場都有值（實測 NVDA→USD、台股→TWD）。改法是在快照的價格數字前加一行 `currency:`，讓模型讀到數字時單位已知，同時修好單一公司題且對未來港股日股自動正確。

**推翻的假設：`trend_header`「必須單行條列」鬆綁無害，但實測不支持。** 全庫只有 `app.py:130` 依賴決策卡格式且只用到區段標題，故假設鬆綁措辭無害、能讓 `comparison` 表格自然合法；A/B 後回退，鬆綁組欄位邊界確實變糊，改為只在 `trend_field_comparison` 文案末尾聲明該欄不套單行條列。另一項回退方向一致：為 `trend_field_valuation`／`trend_field_consensus` 各加一句幣別標示要求後，模型改為整欄輸出「無法提供估值觀察」，即使快照裡 PE 與目標價都齊備，直接違反「不得整段棄權」。這是繼 09-09 字數約束（輸出反變長 35%、遺漏免責聲明）之後第二次踩到同一個坑：**單一欄位的指令密度有上限，超過後模型優先滿足新約束、犧牲該欄本職**。結論有二：新約束只加在最需要的那一欄（幣別最後只留在 `trend_field_comparison`），以及格式契約要靠程式檢查而非文案（即 2026-09-19 的決策卡 post-check）。

**驗證**（同容器同模型 `qwen3.5:9b`、`temperature=0`、固定 `retrieved` 素材排除檢索浮動）：

| 情境 | 欄位數 | 決策卡字數 | 免責聲明 | 比較表 | 幣別誤標 |
|---|---|---|---|---|---|
| 跨市場（NVDA + 2454） | 14 | 1,751 | 有 | 4 列，其中 3 列定性 | 無 |
| 同市場（2330 + 2454） | 14 | 1,794 | 有 | 4 列，其中 3 列定性 | 無（單一幣別） |

四個消失的欄位回來，表格內容非行情數字搬運（每格附 `[來源N]`，推不出來誠實寫「檢索資料不足」），跨市場那份小結明寫兩家幣別不同故無法直接比較股價絕對值。

**已知限制**：同一份 prompt 結構不穩定，兩次跨市場執行幣別一次寫進表格一次寫進小結，格式規則只靠文案**沒有下限保證**（待辦「決策卡缺乏輸出驗證層」的直接依據）；耗時未量測，本次以腳本直接驅動 graph，未經 Chainlit。

### 二、多標的題的補抓決策從未發生

實測三道真實問題時，「台積電與ASML」答得空泛、完全沒有 9 月的 ASML 消息。查庫發現 ASML 新聞距今 65 天（台積電 1 天），先前判斷「這是 ingest 覆蓋缺口」是錯的——Yahoo RSS 當下就有 ASML 當日新聞，真正問題是補抓從未被觸發。

**病因：捷徑的判準對多標的不成立。** `route_after_tools`（09-16 加的效能捷徑，資料夠新就跳過 agent 第二輪決策，省下約 106 秒）取 `min(ages)` 判斷新鮮度，而 `ages` 來自**多標的與全域市場新聞合併去重後的結果**：實測該題 `min` 取到 0 天，來源不是 ASML 或台積電，是順帶補進來的全域市場新聞，路由因而直接收工。`mcp_server.py` 的 `search_knowledge_base` docstring 早已明寫要排除這類稀釋、實作也是 per-company 算的（ASML 老實報 65 天），但捷徑的合併算法與 docstring 的判準漂移了。

修法是縮小捷徑適用範圍（多標的一律回 agent，四行），而非在捷徑裡疊第二套規則——按公司分組取 min 一樣會被 `company` 為 NULL 的全域新聞污染；新增 LangGraph 節點則判斷邏輯仍得寫在 conditional edge，決策點反而散在兩處。**先補觀測再修**：`search_knowledge_base` 記下實收參數與 `news_ages` 全清單、`fetch_company_data` 記補抓對象，用於區分「稀釋」「模型不照做」「決策未發生」三種成因（此前僅從呼叫次數反推，已推錯過一次）。

**驗證**（原始問題經完整 graph）：

| | 修復前 | 修復後 |
|---|---|---|
| 路由 | 跳過 agent（`news_age_days: 0`） | 回 agent |
| `fetch_company_data` | 未呼叫 | 呼叫，`company: ASML`、`has_report: True` |
| ASML 新聞距今 | 65 天 | 1 天（補抓寫入 67 筆 chunk） |
| `fetched` | `false` | `true` |
| `retrieved` | 12 | 18 |
| 總耗時 | 約 199 秒 | 約 370 秒 |

補抓後模型依 tool 說明自行重查（ASML `news_age_min` 由 65 變 1），證明 09-07「補抓決策交給 LLM」的設計有效，先前只是從未讓它做過這個判斷。

**取捨**：多標的題多一輪 agent 加一次補抓（實測約 170 秒，其中補抓與重查約 105 秒為真實外部請求），換回過期標的會被補上——先前的省時，省掉的正是唯一能發現「其中一家資料過期」的機會。捷徑對單標的維持不變。

**已知限制——錯過的視窗補不回來**：使用者指名的 2026-09-08 台積電與 ASML 合作新聞，補抓後仍不在庫裡，因 Yahoo RSS 只回傳最近數篇、該則已被擠出視窗，修復保證的是「以後不會再漏」不是「補回當時漏掉的」；此限制與單一新聞來源脆弱性合併記為待辦。本次僅驗證一題，多標的補抓為序列執行。

**修好第一關才浮現的兩個缺陷**，接著在以下兩節修：其一，補抓後重查白跑一輪 agent（實測最後一輪 `tool_calls: 0`，各花 96.1 秒與 277.1 秒，09-16 曾當離群值撤回、現已在此路徑穩定重現）；其二，`fetch_company_data` 的 `has_report` 只判存在不判時效（實測 2454 財報距今 229 天、NVDA 121 天，一份舊財報會永遠擋住重抓）。

### 三、新鮮度逐家判斷，取代「多標的一律回 agent」

**結論：改為逐家各自取自己那次檢索的新聞天數，全都夠新才收工。** 上一節的「多標的一律回 agent」要價 96 至 277 秒，而補抓重查後模型常只回一句「夠了，停」，真正該擋的不是「多標的」是「稀釋」。新增 `_news_ages_by_company`，掃訊息串裡每次 `search_knowledge_base` 的 `chunks` 按 `company` 分組算距今天數（不讀已合併過的 `assemble(state)["retrieved"]`），取各家最新新聞裡最舊的一家比門檻，任何一家過期或未被檢索到就回 agent。

**實作時一度重現原本的 bug**：先把各家 `min` 放回 `ages`，但下游 `min(ages)` 一樣是「最新的那家代表全部」——與上一節要修的缺陷同型，只換了位置。self-check 的 ASML 65 天案例當場擋下，改成 `max(per_company)` 後通過，實測 2454 距今 18 天、NVDA 1 天，守衛正確判定回 agent。

### 四、`has_report` 改判時效

改判最新財報發布日期是否在 `_REPORT_FRESH_DAYS = 120` 天內，查不到日期一律視為過期：

| 標的 | 財報日期 | 距今 | `has_report` |
|---|---|---|---|
| TSLA | 2026-07-23 | 58 天 | `True` |
| GOOGL | 2026-07-23 | 58 天 | `True` |
| NVDA | 2026-05-20 | 121 天 | `False` |
| 2454 | 2026-02-01 | 229 天 | `False` |

舊的存在與否邏輯下這四筆全是 `True`。端到端證據：`{"company": "NVDA", "has_report": false, "report_age_days": 122}`，該輪確實重抓並寫入 NVDA 的 10-Q。**排查陷阱**：TSLA／GOOGL 首次實測記到 `report_age_days: null`，看似 bug，實為兩家當時根本不在語料庫裡（同輪 `chunks: 0`），`null` 是正確結果——只看 `fetch_company_data` 一行不夠，要連前一次檢索的 `chunks` 一起看。

### 五、補抓指令的遵循：從「模型自己比門檻」到「程式指名過期標的」

**結論：把門檻結論寫進 header 能讓模型去補抓，但它會補錯家；要它補對，得由程式指名。**

守衛叫模型回 agent 後，模型讀到 `N=17`（docstring 明寫「N 大於 3 → 補抓」）仍以 `tool_calls: 0` 收工——不是路由問題，是模型沒執行工具說明裡的比較。第一步沿用「不要自己推算日期」的手法：把門檻算式直接算成結論寫進 header。

行為確實改變（`fetched` 由 `false` 轉 `true`，round 2 原本空轉 137.7s 改為實際發出補抓），但目標錯誤：兩輪工具呼叫全打在 header 寫「不需補抓」的 NVDA 上，真正過期的 2454 從未被補抓——**模型收到「要補抓」指令，卻沒綁回發出指令的那家公司**（header 逐次回傳，模型得自己記對應）。既然程式端早就知道是哪一家，改由程式指名。

**第一次實測完全沒生效**，而元件重放卻是正確的。根因是 `_news_ages_by_company` 對 `m.content` 直接 `json.loads`，但 MCP tool 回來的是 content block 陣列，`TypeError` 被 `except` 吞掉——**重放測不出來，是因為手寫案例是字串，繞過了真實線上格式**，測試檔裡每一處 `ToolMessage` 同樣是字串，所以整套 self-check 也沒攔下。修好後指名生效，但同一家被指名到輪數上限：原本假設「補抓後該家天數下降就不再列入 stale」，實測不成立——掃的是整條訊息串，補抓前的舊天數留在裡面。

**實測**（MSFT 距今 10 天過期／GOOGL 0 天新鮮）：兩次都指名正確、補抓正確，差別在重複指名由 4 次降為 1 次，最終一輪不再是撞上限被截斷而是模型自行收工。DB 佐證：2454 的新聞從 16 天降為 0 天。

### 改動內容

| 項目 | 涉及檔案與函式 | commit |
|---|---|---|
| 快照加公司名與幣別 | `market.py` 的 `format_snapshot`：`info` 既有的 `longName`／`shortName` 與 `currency` 沿用檔案「有才加」的寫法輸出；`currency` 排在價格數字之前，使模型讀到數字時單位已知 | `9280265` |
| 並行取多家快照 | `market.py` 新增 `get_market_snapshots(companies)`，`ThreadPoolExecutor` 且 `max_workers=min(len(companies), 3)`，只回傳成功的 key；單家版 `get_market_snapshot` 保留不動（`no_result` 仍在用） | `9280265` |
| 行情逐家併陳 | `graph.py` 的 `generate`：刪除 `companies[0]` 單家路徑，`has_market` 改判為 `bool(snapshots)`；部分失敗沿用 `market_partial_note` 列出成功家數 | `9280265` |
| 新增比較欄位 | `graph.py` 的 `_ALL_FIELDS` 加入 `comparison`（排在 `risk` 後、`valuation` 前），閘門為 `shape == "full"` 且多標的且 `retrieved` 非空；`ANSWER_SHAPE_GATING=0` 的回退路徑一併過濾家數，否則單一公司題會拿到一張無對象的比較表 | `9280265` |
| 欄位文案 | `i18n.py`：新增 `trend_field_comparison`（zh／en），要求表格比較項目至少半數為定性、每格附 `[來源N]`、金額須標幣別且不同幣別不得換算比較、明文禁止資金配置比例與「若只能選一檔」；`trend_field_valuation`／`consensus`／`scenario` 改逐家分列語氣 | `9280265` |
| 圖表逐家 | `app.py`：`companies[0]` 改為逐家迴圈，figure 的 `name` 帶上代號以便互動版面區分；`report_pdf` 不動（本來就吃扁平串列） | `9280265` |
| self-check | 新增 `tests/test_market_snapshots.py`（全成功／部分失敗／全失敗／空 list 四種形狀）；`tests/test_market.py` 補公司名與幣別的斷言（幣別須早於價格）；`tests/test_allowed_fields.py` 補 `comparison` 的閘門 case 與回退路徑 | `9280265` |
| 多標的不走捷徑 | `graph.py` 的 `route_after_tools`：`companies` 超過一家時直接回 `agent`，置於 `ages` 計算之前。不改判準本身，只縮小適用範圍 | `4713951` |
| 補抓決策的觀測 | `mcp_server.py` 新增 `mcp_tools` logger 兩處：`search_knowledge_base` 記實收的 `company`／`doc_type`／`news_since_days` 與算出的 `news_age_min`、`news_ages` 全清單（只記 min 分不出「被稀釋」與「模型不照說明做」）；`fetch_company_data` 記補抓對象與 `has_report` | `4713951` |
| self-check | `tests/test_route_after_tools.py` 補多標的 case（同一組資料單標的收工、多標的回 agent）與實測情境（全域 0 天／台積電 1 天／ASML 65 天）；`tests/test_mcp_tools.py` 補「記下的 N 與 header 報的 N 一致」與查無資料時記 `None` | `4713951` |
| 新鮮度逐家判斷 | `graph.py` 新增 `_news_ages_by_company`（掃訊息串的 `search_knowledge_base` chunks，按 `company` 分組）；`route_after_tools` 多標的改取各家最新新聞裡最舊的一家比門檻，有公司未被檢索到則回 `agent`。單標的維持合併取 `min` 的原行為 | `b447d02` |
| 財報時效門檻 | `mcp_server.py` 的 `fetch_company_data`：`has_report` 由「是否存在」改為「最新發布日期是否在 `_REPORT_FRESH_DAYS`（120 天）內」，無日期視為過期；log 增記 `report_age_days`。門檻取一季 91 天加發布延遲空檔，值為推估，靠新增的 log 累積實測後再調 | `56b8021` |
| header 直接給結論 | `mcp_server.py` 的 `search_knowledge_base`：新鮮度那行後面接上補抓與否的結論，門檻算式與 docstring 判準一致（時效窗 <= 7 天時收緊到當天，其餘 3 天） | `9154132` |
| 程式指名過期標的 | `graph.py` 的 `agent`：`_stale_companies` 非空時產生一則 `HumanMessage` 指名代號與天數，一併寫回 `state["messages"]`（只塞給當次呼叫的話，下一輪歷史裡沒有它，模型又會補錯家）；新增 `_fresh_limit`／`_stale_companies` 供條件邊與節點共用 | `864e7ad` |
| 讀 ToolMessage 的格式 | `graph.py` 的 `_news_ages_by_company` 改走同檔既有的 `_tool_text`。原本直接 `json.loads(m.content)`，但 MCP tool 回來的是 content block 陣列，`TypeError` 被 `except` 吞掉，靜默退化成「沒有新聞」，指名從未發出 | `864e7ad` |
| 重複指名 | `graph.py` 的 `_news_ages_by_company` 只計最後一次 `fetch_company_data` 之後的檢索。補抓前的舊天數留著會讓 `min` 卡住，同一家被指名到輪數上限 | `864e7ad` |
| self-check（補抓路徑） | `tests/test_route_after_tools.py` 的 `_doc` 加 `company` 參數，多標的六個 case（一家過期／兩家都新／有家沒檢索到／時效窗收緊／補抓後重查／單標的不受影響）；新增 `_search_blocks`（content block 陣列的真實形狀）與三個指名 case，既有兩個「補抓後重查」case 的 fixture 一併修正——原本只回補抓那一家的 chunk，真實重查是對整題重跑、兩家都會回來；`tests/test_mcp_tools.py` 新增 header 結論的六條斷言（含實測的 N=17）與財報時效表（89／120／121／229／`None`） | `b447d02`／`56b8021`／`9154132`／`864e7ad` |

---

## 2026-09-19　補抓路徑收斂、財報檢索期間維度、embedding 分批、市場與輸出驗證、待辦收尾

各自獨立的多件工作，共通脈絡是**補抓與檢索這條路徑上累積的待辦一次清掉**。其中兩件是查別的問題時連帶追出來的：查財報期間維度時發現 JPM 的財報全文從未入庫，追出 embedding 整批失敗（第五節）；三輪雙掛牌驗收則暴露了財報日標記自始沒成功過（第九節）。
### 一、tool 輪數上限 A/B：維持 4，待辦撤下

判斷、觸發條件與收斂脈絡見「已評估不採用」同名項目，不重複。此處只留這次 A/B 的量測陷阱（同一份程式碼、同容器，上限由環境變數切換，兩臂各跑五題）：

**十個樣本的輪數全落在 1 或 3，上限 4 一次都沒被觸及**，兩臂其實跑的是同一條路徑。**耗時差也不能算作參數效果**——每次補抓都把新聞寫回同一個資料庫，A 臂先跑已把過期新聞刷新成 0 天，B 臂無事可做：JPM／SPCX 那題 A 臂補抓走 3 輪（487.0s）、B 臂 1 輪收工（174.0s），把那 313 秒算成節省會是假數據。

### 二、`extract_filters` 換小模型：實測後不採用，維持 9b

判斷、真因與再評估門檻見「已評估不採用」同名項目。28 題逐欄計分（同容器、`temperature=0`，各跑一次）中，決定結論的是這兩列——4b 快一倍，但關鍵欄輸掉：

| | qwen3.5:9b | qwen3.5:4b |
|---|---|---|
| companies | **27/28** | 25/28 |
| 單題中位數 | 12.7s | **6.6s** |

其餘四欄不影響判斷：`in_scope`、`answer_shape` 兩臂皆全對，`news_since_days` 分母只有 3，`market` 未進入取捨。**已知限制**：兩臂各跑一次，僅對判定關鍵的失敗項補做三次重跑確認非雜訊，其餘欄位離散度未測。

### 三、補抓期間的進度回饋

**待辦的前半早已完成，項目本身沒更新**：逐 token 串流與三段進度顯示早已在 `app.py` 運作，待辦原文把實作手段寫成「改 `.stream()`」是錯的（理由見「已評估不採用」同名項目），一併更正。實際缺的是補抓那段：中位 67.6s（見本章第十一節）期間，進度顯示停在「檢索資料庫」不動，使用者既不知道系統在做什麼、也不知道要等多久。

**掛勾點只有一個可選**：`updates` 事件在節點跑完才送，等 `tools` 的 update 到手補抓已結束、提示沒有意義；只有 `agent` 完成的瞬間 tool 已選定而尚未執行。判斷依據是 tool 名稱，`search_knowledge_base`（中位 0.5s）不提示，否則每輪純檢索都會閃一下誤導人。

**取捨：只分「有沒有在補抓」，不做逐來源進度。** 逐來源完成事件在 MCP server 那個 process 裡，要送回 `app.py` 得新增 progress notification 或另一條 channel，牴觸既有決策「對外 MCP 契約有外部 client 在用，不為內部需求改動」（詳見 2026-09-13 章節）；且「補抓改為並行」一旦動工，序列顯示邏輯得重寫，粗粒度提示則並行與否都成立。代價是使用者只看得到「正在抓取，約 1-3 分鐘」——沒有取消機制時兩者行為相同，都是等。**成本也低於待辦原文估計的 1-2 天**：`i18n.py` 的 `step_fetch` 字串早已寫好、只是沒被引用，這次是接上備好的零件。

**已知限制**：只改「什麼時候給回饋」，總耗時未變動；粒度是每輪 agent 決策一次，同一題補抓多家不會逐家更新；tool 名稱以字串比對，`mcp_server.py` 改名要跟著改，比對不中只會少一句提示。

### 四、財報檢索的期間維度

原待辦把台股側與美股側寫成「同一個病、兩個根因」，並提出「同一 company 內先取最新 `published_at` 的批次」作為共同解。**實測後前半成立、後半只對一半**：那個做法對台股側有效，對美股側是空操作，兩側最後用了兩種不同層級的修法。

#### 台股側：保留席位，而非改動排序

病因確認為**顆粒度不對稱**。「2330 最新財報重點？」的純相似度排序裡，正確的 2026 Q2（`TWSE-API:2330:115Q2`，2026-08-01）那兩塊排在**第 242 名（0.3322）與第 248 名（0.3273）**，`TOP_K=5` 撈到的五塊全來自 2026-01 的舊 PDF（0.4905～0.4560）。結構化來源整季壓成 2 塊密集數字、PDF 散成上百塊自然語言，舊資料靠塊數多穩定勝出。

修法是給最新一期**固定席位**併到結果最前面，**刻意不動全局 `ORDER BY`**——那會傷到「比較去年同期」這類本來就需要舊資料的問法，舊 chunk 一塊都不移除，只是排在席位之後。三個設計細節：席位放最前面因為引用編號與 context 都依出現順序；子查詢比對「最新日期」而非單一 source，因為同一天可能有多個來源（2454 實測同日兩份 PDF）；`_wants_latest_report` 刻意**不看「最新」這類字眼**，問「2330 財報如何」同樣不該拿到半年前的 PDF。

驗證：席位在位置 1-2 且內容正確（EPS 49.33），舊 PDF 五塊全部保留在 3-7；回歸題「2330 今年營收和去年同期比較如何？」仍拿到舊 chunk，**原待辦擔心的風險沒有發生**。

#### 美股側：期間維度是空操作，病灶在入庫端

`SEC-XBRL:TSM:...541` 那塊寫的是 2024 年報數字，而**檢索端的期間維度對它完全無效**——它與正確的 371 塊 EDGAR 全文來自同一次申報、**共用同一個 `published_at`**，「最新一批」等於全部，席位不會啟動（實測確認那塊仍排第 1）。根本原因是 `published_at` 記的是**申報日期**，stale 的卻是**內容的會計期間**，同一份申報裡兩者必然不同步；同理，全域重排、相似度門檻、提高 `TOP_K` 全都無效，只能改在入庫端。

**逐條而非整份丟，是評估後推翻第一版實作的結果。** 第一版判斷「整份落後就不入庫」，理由是「正確內容由 `fetch_edgar` 那軌提供」，但這個前提不成立：全庫 12 家 XBRL 公司裡 **JPM 與 SPCX 的 EDGAR 全文塊數是 0**，整份丟等於這兩家完全沒有財報數字。**那兩個 0 的成因事後查明，與當時假設不同，在此更正**（結論不變，因果不可沿用）：兩家都不是 SEC 沒資料——SPCX 從未抓過，JPM 是 embedding 整批失敗（見第五節）。**看到「某家 EDGAR 塊數為 0」不能直接推論成外部沒有資料**。JPM 同時推翻「混合期不會發生」的假設：13 條裡 11 條是當期，只有營業收入落後一年、現金及約當現金落後**八年**（`_pick_fact` docstring 早警告過的停用概念型失分），全份旗標會把「2/13 錯」和 TSM 的「13/13 錯」當同一件事，一個過當、一個剛好。

第一版還靠比對中文警語文案決定入不入庫，一併改用 `_pick_fact` 逐概念回傳的 `exact`，不把控制流程綁在顯示文字上。**為什麼不是加文案**：chunk 開頭原本就寫了「並非本次申報當期」，LLM 仍照引 2024——它是全庫唯一「長得像財報摘要」的乾淨數字清單，其餘 371 塊是會計附註碎片。本專案第三次確認「格式與正確性契約要靠程式而非文案」（前兩次見「已評估不採用」同名項目）。

#### 既有資料的清理

三塊帶落後期數字的 chunk 分開處置，判準是「有沒有另一軌接得住」：TSM（2024 全份）與 ASML（2025 EUR 全份）各有 371 與 104 塊 EDGAR 全文頂上，直接刪除；JPM 的 EDGAR 塊數是 0，刪了就沒有任何財報數字，故改為重抓。重抓後留下 8 條當期數字，檢索驗證由這塊排第 1，TSM 改以 EDGAR 全文佔滿前五。SPCX 一併補跑 `fetch_edgar` 入庫 434 塊。

**未一併處理**：`_MIN_FINANCIAL_REPORT_CHARS = 10000` 對每塊 XBRL 都會觸發「財報字數偏低」警告（全庫 479～721 字元），該門檻是為 PDF 全文設的，對整季壓成一塊的結構化數字本就不適用，屬既有行為。

### 五、大型 filing 的 embedding 整批失敗：分批送出與批次值實測

上一節那個 0 的成因。抓取、選檔、抽文字全部正常，**只死在 embedding**：`ingest_text` 把一份文件切完的 chunk 一次性全數丟進單一 `embed_documents()`，JPM 的 10-Q 切成 1533 塊，這一批在 Ollama 端穩定失敗（`Post ".../tokenize": EOF`）。看起來卻像「SEC 沒有這家的財報全文」。

依「效能優化須有實測數據」慣例，批次值不取推導值。同一份輸入（JPM 10-Q 的 1533 塊）、同一份程式碼、由 `EMBED_BATCH_SIZE` 切換，每個值跑 2 次：

| 批次 | 結果 | 耗時 |
|---|---|---|
| 100 | ok／ok | 198s／194s |
| 200 | ok／ok | 192s／194s |
| 400 | ok／ok | 192s／193s |
| 600 | **FAIL**／ok | 230s（失敗）／267s |
| 不分批（1533） | **FAIL／FAIL** | 335s／344s |

**400 是上界，而取小沒有代價。** 600 已開始抖，真正的穩定邊界比先前記錄的「900 塊時好時壞」低得多；而 100、200、400 耗時全落在 192-198 秒，呼叫次數從 4 增到 16 總時間不動——成本在 token 總量、不在 per-call 開銷，選 400 的唯一理由是讓重試粒度不要太細。**失敗時耗時反而更長**（230／335／344 秒 vs 正常 192 秒），符合資源／超時型失敗特徵而非乾淨的門檻拒絕，這也是為什麼「查表訂一個上限」從一開始就不對。每批失敗重試一次即止：同一批重送常會過，但連兩次不過就不是暫時性問題，繼續重試只是把等待拉長。**重試不是形式上的保險**——JPM 真實入庫那次，第 1 批就失敗了一次、重試成功，即使批次已是定案的 400。

**修在 `ingest_text` 而非四支 `fetch_*`，原待辦寫錯了位置。** 待辦原文要「把 `ollama.ResponseError` 納入 `fetch_*` 的錯誤收斂」，**沒有照做**——與 `fetch_edgar:208`／`fetch_tw_financials:598`／`fetch_mops:722` 三處既有原則牴觸（「只收抓取／寫檔的失敗，embedding 失敗不是 MOPS 的錯」），照做等於把「SEC 沒資料」的誤導換成「SEC 抓不到」，真正原因依然看不見，且同一判斷要複製四份。寫待辦時漏查了那四處註解，是當時的疏漏。改在 `ingest_text`（全部來源唯一的寫入端）達成同一目的，修一次四條路徑都對。**原待辦另把「靜默」的嚴重度記高了一階**：`auto_fetch` 已有 `except Exception`，正式環境不會炸掉對話，實際損失只有錯誤訊息像網路錯誤、以及 `FetchResult.ok` 少一筆統計。

**驗收**：JPM 入庫 **1533 塊**，從只有 1 塊 XBRL 變成有財報全文；檢索未退化，XBRL 塊仍排第 1，第四節的保留席位機制在新增競爭者之下仍成立。self-check 其中「向量數與塊數一致」釘的是錯位風險——切批錯位會讓 content 配到別人的向量且不會報錯。**`CHUNK_SIZE` 的 A/B 刻意不做**：塊變大則總塊數下降，JPM 成功就分不清是分批修好的還是剛好避開失敗區，它屬待辦「`CHUNK_SIZE` 單位不一致」一項（2026-09-20 自原「chunk 策略」拆出，parent-child 與表格切分另立一項）。

### 六、雙掛牌反問被繞過：市場判斷移出 LLM

**根因不在抽取品質，在消費端的信任假設**：`resolve_market` 只在 `market is None` 時反問，等於把「使用者有沒有講市場」託付給模型的一個欄位，而該欄位實測會違反 prompt 第 5 點自行填值——與 09-18 的補抓問題同型。修法是不再信任它，改只認問句裡明白寫出的市場字樣，三條既有分支的邏輯不動。不改 prompt 文案，理由見「已評估不採用」區塊的第二次前例。

**實作中被使用者推翻的一個假設**：原設計把「直接打 `2330` 或 `TSM`」視同表態，實際驗收判定為錯——**打代號不代表選邊**，使用者可能只是記得代號，而雙掛牌兩邊的幣別、報告期間、每股基準都不同，猜錯的代價大於多問一句。該分支已移除。**已知不一致，刻意留著**：prompt 第 5 點與題組標注 M5 仍寫「代號 → tw/us」，因為 eval 量的是抽取端、流程走的是消費端——抽取欄位的語意是「模型從問句看到什麼」，反問與否是「該不該替使用者決定」，兩邊不必一致。

**同一家公司的兩個掛牌被抽成兩個標的**，是查上一項時連帶發現的缺陷。M3「聯電台股美股兩邊比較一下」穩定抽出 `['2303','UMC']`（4/4 次），抽取本身沒錯——prompt 要的就是「所有指名的代號」——但這語意是同一家公司的併陳，留兩個元素會踩到三處 `len(companies) > 1` 的分支，其中「決策卡把同一家當兩家比」**正是雙掛牌機制存在的目的所要防止的誤讀**。**修在抽取源頭而非 `resolve_market`**，因為那三處共用同一個 `companies`，改源頭一次三處都對。**先前歸因錯誤在此更正**：原把 M3 記為「`market` 欄錯」，實測 4/4 次都正確抽出 `market='both'`，FAIL 一直在 `companies` 欄。

**市場已確認時不重複走流程**：按鈕重跑原本從 graph 起點整條重來，而問句沒變、市場已定、公司已知，兩次 LLM 呼叫白跑。**實測省下 15.4 秒**（按鈕重跑那輪的 15404ms 降為未執行；第一輪的 21432ms／26464ms 屬採樣抖動，本次不碰該路徑，不計入）。這個旗標同時擋住一個自傷風險——按鈕重跑時問句本來就沒有市場字樣，若讓 `_market_in_question` 覆寫會打回 `None` 造成無限反問。

**反問 UI 收斂為只給按鈕**，`_pick_market` 的 `timeout` 放寬至 3600 秒——**這個值等的是人類點按鈕，與 LLM 無關**，逾時會落回本次要避免的文字路徑。逾時回 `None` 的舊行為保留，**這條後路不可移除**，否則使用者關掉視窗就卡死沒得救。

**驗證**：28 題題組回歸，`companies` 由 27/28 升至 **28/28**，全欄皆對 25/28 升至 **26/28**，無其他欄位回歸（剩下 S2、N8 兩題不經過受害路徑，無下游後果）。端到端三輪手動驗收全過：含市場字樣不反問並併陳兩市場（`retrieved=15`，單一市場為 10），裸代號 `2330` 仍反問，選市場後 `extract_filters` 只跑一次（舊碼兩次）。這三輪另暴露兩件既有問題，非本次引入：ADR 側取到 2024 年報數字（見第四節），以及財報日標記失敗（見第九節）。

### 七、`dual_market_warning` 措辭與觸發條件修復

**結論：措辭不再寫死幣別，觸發條件從「雙掛牌併陳」放寬為「並排代號橫跨台美兩市場」。**

原措辭把 `peer_company` 一律當 ADR、寫死「新台幣」「美元 ADR」，牴觸 `trend_field_comparison` 早訂下的「幣別須取自 `currency` 欄、不得由代號推測」；放寬觸發條件後 `{us}` 可能是任何美股標的，並非 ADR，故 ADR 的股數換算比例降為括號補充。

觸發條件盲點：原判斷只認雙掛牌併陳，多標的比較題（如 2330 vs NVDA）沒有 `peer_company`、不會觸發，但那正是最需要幣別提醒的場合。改為看最後要並排的那組代號是否橫跨兩市場，雙掛牌併陳成為其中一個特例。抽成獨立純函式而非留在 `generate` 節點內——`generate` 直接耦合本地 LLM，邏輯留在節點內測不到。

### 八、決策卡的輸出驗證層（post-check）

待辦「決策卡缺乏輸出驗證層」與「`[即時市場數據]` 被當成引用標記」在此一併結束。

**只寫 log、不擋輸出也不改寫輸出**——品質問題不該讓使用者拿不到答案，驗證層自己有 bug 也不會連累正常回答。四條規則查欄位集合、免責聲明、引用編號越界、非法引用標記。

**全形括號是實測發現**：prompt 寫半形 `[來源N]`，模型在中文語境實測輸出全形【來源N】，只認半形等於對真實輸出全盲。

**連帶修掉的既有 bug，是本次實際收穫**：`src/app.py` 的 `_link_citations` 同樣只認半形，模型輸出全形時**整份決策卡一個連結都轉不出來**（實測轉換數 0、殘留 3 個【來源1】）。正式環境發生過但一直沒被發現——表現為「那條引用就是點不開」，使用者以為是 bug，其實是格式匹配失敗。已修為半形全形都認。驗證層才上線就找出一個沒人發現的顯示層 bug，正是原待辦說的「只能靠人逐份目視才發現，且每次都是在踩到之後」。

`[即時市場數據]` 現在會被 `unknown_citation_marker` 抓到並記 log——這是**讓它可被觀測，不是讓模型不再輸出它**，故該待辦降為低優先而非關閉。**已知限制**：格式違規仍會送到使用者眼前；`unknown_citation_marker` 可能誤報內文正常使用的中括號，需等 log 累積後看誤報率；欄位比對依賴 `- **欄名**：` 字面格式，i18n 改排版需同步（已有測試釘住）。

### 九、兩個順手修掉的獨立缺陷：plotly 鎖版與財報日標記

兩個都難查，原因相同——**後端完全正常，故障只在別處可見**。

**圖表在瀏覽器端顯示 An error occurred**：`plotly` 未鎖版本，重建映像時解析成 7.0.0，而 chainlit 前端內嵌的 plotly.js 讀不懂它的 figure JSON schema。後端 log 無 traceback，只有瀏覽器看得到。

**財報日標記從來沒成功過**：log 長期出現 `財報日標記略過` 的型別錯誤，圖表照樣產出、只是少了「下次財報」虛線，屬靜默降級。最初記成「`both` 情境炸開」，**本次三輪實測推翻**——單一市場與 `both` 三次同一則錯誤、與市場別無關，自始就沒成功過。根因是 `add_vline(annotation_text=...)` 要對線的兩個 x 端點做 `sum()` 求平均，而本圖 x 軸是 ISO 日期字串（為了 kaleido 的 orjson 不吃 pandas Timestamp 才轉的），`0 + "2026-10-15"` 直接 TypeError——**兩個各自合理的決定撞在一起**。

**連帶暴露本機 venv 與鎖版漂移**：`tests/test_chart_earnings_marker.py` 本機失敗、容器通過——`./venv` 是 plotly 6.9.0，而那條反向斷言釘的是鎖定版 plotly 5 的行為。照失敗訊息字面去改 `charts.py` 會在正式環境把圖表弄壞，**真正該修的是 venv 與鎖版不一致**。

**一項既有行為未處理**：容器內 `report_pdf` 一律退回 `.md`，因 `src/charts.py` 找的是 macOS host 的 Chrome 路徑。

### 十、mcp-server healthcheck

**結論：原待辦記載的限制（FastMCP 無 health endpoint、`depends_on` 只能用 `service_started`）不成立，不需要專用 endpoint。** 直接探 `/mcp`：不帶 token 會被既有 Bearer middleware 擋成 401，而 401 正是要的存活訊號（uvicorn 有在聽、middleware 有在跑）；不帶 token 是刻意的——healthcheck 不該碰密鑰。連不上時 `urlopen` 拋的是 `URLError` 而非 `HTTPError`，據此 exit 1。用 python 而非 curl/wget，因映像未裝這兩個工具。

實測起容器約 20 秒由 `starting` 轉 `healthy`，容器內實探回應為 `HTTP 401 {"error":"unauthorized"}`。

**已知限制**：port 未映射到 host、外部 client（如 Claude Desktop）目前無法連入，維持現狀不變——不是卡在驗證，Bearer token（`MCP_AUTH_TOKEN`）已就緒；目前只有 `app` 需要連 `mcp-server`，走 docker 內部網路即可，開 port 只會憑空多一個對外攻擊面。觸發條件：真的需要外部 client 連入時再評估開放。

### 十一、單一公司內的來源補抓改為並行：實測後判斷收益太小

`fetch_missing_data`（`src/graph.py`）的 `for call in calls` 是序列呼叫沒錯，但實測顯示並行省不到多少。n=5 樣本測得補抓耗時中位 **69%** 花在 embedding（`ingest_text` 打本地 Ollama，範圍 59-80%），而並行四個來源不會讓 embedding 並行，只會在同一個 Ollama 前排隊——序列中位 67.6s，把排隊算進去的並行是 53.4s，**實得 14.2s（21%）**。`EMBED_BATCH_SIZE` 同日定案為 400 時另測到分批不會讓 embedding 變快（100／200／400 耗時相同，成本在 token 數不在呼叫次數），故 embedding 是主因這點預期不變。

**卡在收益太小，不是卡在做法。** 做法很清楚：改用 `ThreadPoolExecutor`（前例 `src/market.py` 的 `get_market_snapshots`），同時把 `has_report` 的 `calls[-1:]` 改成顯式條件——並行後 `calls` 沒有順序語意。另外補抓期間已有「約 1-3 分鐘」的預期提示（見第三節），乾等的難受解掉大半，14.2s 更不值得換順序語意的改動風險。

**原標題的「多標的」是假問題**：跨公司早已並行（`fetch_company_data` 以單公司為單位呼叫；`ToolNode` 以 `asyncio.gather` 併發同輪 tool call）。舊文依據的「09-18 約 45 秒」是單一樣本且未分辨層級。

結論移入「已評估不採用」，觸發條件為使用者實際反映補抓仍然難等，或 embedding 佔比顯著下降（屆時要拿新的 n=5 數據，不能靠推導）。2026-09-21 補充：logfile 新增 `source` 欄位後，「哪一軌最慢」已可由 log 直接彙總查出，不必再人工比對，詳見該日章節第四節。

### 改動內容

| 項目 | 涉及檔案與函式 | commit |
|---|---|---|
| 決策卡 post-check | `graph.py` 新增 `check_answer_format` 與 `_FIELD_LINE_RE`，`generate` 於 `log_duration` 後呼叫；回傳結構化 dict 列表以供 log 彙總分析。欄名來自 `t()` 以自動跟著 i18n，抽不到格式時記 `log.error`。引用標記支援半形與全形括號、markdown 連結排除、集中在單條規則不做會 raise 的操作 | `374c02d` |
| self-check（post-check） | `tests/test_answer_format.py`：10 組案例涵蓋全合格、缺免責聲明（09-17 迴歸）、缺欄、多欄、引用編號越界、`[即時市場數據]`（原待辦第二項的迴歸）、markdown 連結不誤報、英文 label、縮排子條列不被當成欄位。另一條跑遍 `_ALL_FIELDS` × 中英，釘住每個 `trend_field_*` 都抽得出欄名——欄名解析失準會讓驗證層自己發假警報，這條先爆掉 | `374c02d` |
| 引用連結全形修正 | `app.py` 的 `_link_citations` 半形全形括號都認，替換後產生的連結一律用半形；越界編號移除也同步改成兩種都認。修掉一個無聲 bug：2026-09-19 實測模型輸出全形時轉換數為 0、整份決策卡沒有一個連結能點開 | `—` |
| 引用連結 self-check | `tests/test_link_citations.py` 改寫：5 組斷言涵蓋半形、全形、越界刪除、`None` 來源保留純文字（不轉連結也不被當越界刪掉）、英文 label 容錯 | `—` |
| 輪數上限 A/B 與 self-check | `config.py` 新增 `MAX_TOOL_ROUNDS`（環境變數，供同程式碼切換臂）、`graph.py` 的 `_MAX_TOOL_ROUNDS` 改讀它；`tests/test_route_after_tools.py` 補上輪數上限的四條斷言。實測後維持預設 4，參數保留是為了下次要動它時不必再改一次程式碼 | `2d20897` |
| 抽取模型 A/B 與題組 | `config.py` 新增 `FILTERS_MODEL`（空字串沿用該輪主模型，供同程式碼同容器切換臂）、`graph.py` 的 `extract_filters` 改用它選模型；成功路徑的 `log_duration` 原本仍記主模型名，兩臂在 log 中無法分辨，一併改記實際模型。新增 `tests/eval_extract_filters.py` 逐欄計分與 `tests/eval_data/extract_filters_annotations.json` 題組；`tests/test_extracted_filters.py` 固定住「空值沿用主模型、有值才覆蓋」，避免開關寫錯時兩臂其實跑同一個模型而量出假的「沒有差異」。實測後維持 9b | `7d53347`／`c7ab5e9` |
| 市場判斷移出 LLM | `graph.py` 新增 `_market_in_question` 與 `_TW_WORDS`／`_US_WORDS`／`_BOTH_WORDS`；`resolve_market` 在判斷反問前先覆寫 `market`，並把校正結果寫回 state——三條分支都回 `{**state, ...}` 帶著舊值，只改區域變數的話 `both` 會在這裡判對、到下游 `assemble`／`generate` 卻仍讀到舊的單邊值。同函式移除「company 出現在問句即依代號型別回 tw/us」的分支，連同已無用的 `company` 參數 | `f773e25` |
| 雙掛牌收斂 | `graph.py` 新增 `_collapse_dual_listing`，接在 `extract_filters` 的 `companies` 後處理。只處理「剛好兩個元素且互為 peer」，`['2330','TSM','AAPL']` 這種一組雙掛牌加第三家語意真的模糊，不猜 | `f773e25` |
| 已確認市場不重跑 | `graph.py` 的 `GraphState` 新增 `market_confirmed`；`rewrite_question`／`extract_filters` 各加早退；`app.py` 的重跑 state 補齊上一輪的 `doc_type`／`news_since_days`／`answer_shape`／`in_scope`。另新增 `answering_reask`：從歷史撿回公司代號的那條路沒有 `market_confirmed`，若被校正打回 `None` 會無限反問；`state.get("question", "")` 的預設值取空字串＝倒向反問這個保守側 | `f773e25` |
| 反問 UI | `app.py` 的 `_pick_market` `timeout` 300 → 3600 並改寫 docstring；`i18n.py` 的 `ask_market` 中英文案改為只提按鈕 | `f773e25` |
| self-check（雙掛牌） | 新增 `tests/test_resolve_market.py`（14 條斷言：收斂的正反例、代號仍反問的 `2330`／`TSM` 對稱兩題、`market_confirmed` 不被覆寫、多標的與非雙掛牌不受影響、兩個節點的早退）。`tests/test_dual_market.py` 的 `_FakeParsed` 補上 `answer_shape`，並為 6 個呼叫點補上含市場字樣的 `question`——市場判斷改以問句為準後，呼叫端給的 `market` 不再被無條件採信 | `f773e25` |
| 圖表相依鎖版 | `requirements.txt`：`plotly` → `plotly<6`（跟著 chainlit 前端內嵌的 plotly.js v2.30.1），`kaleido` → `kaleido==0.2.1`（1.x 要求 plotly >= 6.1.1，與前者互斥） | `8b0c0e1` |
| 財報日標記 | `charts.py` 的 `price_chart` 改用 `add_shape`＋`add_annotation` 取代 `add_vline(annotation_text=...)`，繞過 plotly 對字串 x 軸的平均計算；新增 `tests/test_chart_earnings_marker.py`（3 條斷言，含一條釘住 plotly 現行行為的反向斷言） | `f1c73ae` |
| 題組標注 | `extract_filters_annotations.json` 的 D3 由 `null` 改為 `"tw"`：與 N3「比較一下 2330 和 2303 的表現」同為裸台股代號，prompt 第 5 點對兩者說的是同一句話，標注不該分歧。此欄量的是抽取端，與本次流程端的「代號不算表態」不衝突 | `f773e25` |
| 期間維度 | `vectorstore.py` 的 `similarity_search` 新增 `latest_source_only`；連線池 `max_size` 5 → 6（並行檢索多出一條） | `fdc6972` |
| 保留席位 | `graph.py` 新增 `_LATEST_REPORT_K`、`_merge_latest_report`、`_wants_latest_report`、`_latest_report_docs`；循序與並行兩路徑各插入同一條件，並行的 `max_workers` 3 → 4 | `fdc6972` |
| XBRL 逐條濾期 | `update.py` 的 `_format_xbrl` 落後期數字不寫出、開頭明列略去項目、全落後回 `None`；`_fetch_sec_financials` 移除 `_XBRL_STALE_MARKER in text` 字串判斷與該常數 | `fdc6972` |
| 資料清理（XBRL） | 刪 `SEC-XBRL:TSM:...541`、`SEC-XBRL:ASML:...235`；`SEC-XBRL:JPM:...343` 重抓 | `fdc6972` |
| self-check（期間維度） | `tests/test_retrieve_context.py` 補席位的邊界（新聞題／`doc_type=None`／無 company 不觸發、重疊去重、席位上限），循序與並行各跑一輪；`tests/test_update.py` 補混合期（JPM 形狀）與全落後兩例 | `fdc6972` |
| venv 對齊 | `./venv` 的 `plotly` 6.9.0 → 5.24.1、`kaleido` 1.3.0 → 0.2.1，與 `requirements.txt` 的鎖版一致 | `f1c73ae` |
| 分批 embedding | `ingest.py` 新增 `_embed_in_batches()`，取代 `ingest_text` 裡直接呼叫 `embeddings.embed_documents(chunks)` 那一行；逐批記耗時、重試記 `reason=embed_batch_failed` | `72ac871` |
| 批次參數 | `config.py` 新增 `EMBED_BATCH_SIZE`（預設 400，實測值）。`0` 代表不分批，供 A/B 用同一份程式碼切換，沿用 `EMBEDDING_CACHE_MAX_ENTRIES` 既有慣例 | `72ac871` |
| self-check（分批） | `tests/test_ingest.py` 新增 `_RecordingEmbeddings` 與分批／重試四組斷言 | `72ac871` |
| 資料補上（JPM） | JPM 的 EDGAR 全文 1533 塊 | — |
| 補抓提示 | `graph.py` 新增 `is_fetching()` 與 `_FETCH_TOOLS`，讀 `agent` 節點 update 裡最後一則訊息的 `tool_calls`；`app.py` 的 `_stream_answer` 在 `updates` 分支新增 `agent` 一支，命中即切到 `step_fetch`。掛在 `agent` 而非 `tools`，因為 `updates` 是節點完成才送 | `f45173a` |
| 原有註解更正 | `_stream_answer` 裡「無法預判下一步是檢索還是補抓」一句已不成立（`agent` 的 update 帶著 tool 選擇），改寫為掛勾點的理由 | `f45173a` |
| CLI 漸進回饋 | `cli.py` 新增 `_ask()`，以與 `app.py` 相同的三種 stream_mode 取代原本的 `app.ainvoke()`；逐 token 用 `print` 避開 `rich` 把 token 裡的 `[]` 當標記，最後再用 `Markdown` 重印補排版 | `f45173a` |
| 判斷放在 graph 層 | `is_fetching` 未留在顯示層：`app.py` 模組層級 import chainlit，CLI 從那邊拿會把整個 Chainlit 拖進一支命令列工具；判斷讀的是 agent 節點的 state，本就屬 graph 語意（`unique_sources` 為同樣先例） | `f45173a` |
| self-check（進度回饋） | `tests/test_is_fetching.py`：補抓／純檢索／混合呼叫／無 tool_calls／directive 在前／空值與缺 key 共九組斷言，import 改指 `graph.is_fetching` | `f45173a` |
| 幣別提醒措辭與觸發條件 | `i18n.py` 的 `dual_market_warning`（中英）改為指向 `currency` 欄，不寫死幣別；`graph.py` 新增 `cross_market_split`，`generate` 改依此函式產生 `dual_block` | `1357883` |
| self-check（幣別提醒） | `tests/test_dual_market.py` 補 6 條 `cross_market_split` 斷言 | `1357883` |
| mcp-server healthcheck | `docker-compose.yml`：`mcp-server` 新增 `healthcheck`（探 `/mcp`，401 視為存活）；`app` 的 `depends_on.mcp-server` 由 `service_started` 改 `service_healthy` | `1320669` |

---

## 2026-09-20　`_relax_doc_type` 改回傳複本、chunk 單位量測與切法出處、eval 標注除役

三件各自獨立的工作，同日並列非同一條線：先修好 `_relax_doc_type` 的就地寫入隱患；再處理待辦「`CHUNK_SIZE` 單位不一致」——實測釐清字元／token 的真實落差、加上切法出處欄位供未來重灌時分辨新舊塊，但**只改切法與量測，不改預設值、不重灌全庫**；最後修掉 `tests/eval_rag_retrieval.py` 裡會隨補抓寫入新資料而定期假警報的標注。

### 一、`_relax_doc_type` 改回傳複本

`_relax_doc_type`（`src/graph.py`）改為回傳複本，從就地寫入改為 `return [{**d, "relaxed": "doc_type"} for d in docs]`。原條目在 2026-09-19 曾列入「已評估不採用」維持觀察，現觸發條件之一成立——2026-09-19 新增的保留席位機制（`_merge_latest_report`／`_latest_report_docs`）讓同一次請求開始出現多條路徑處理同一批 chunk，屬於原判斷的第二個觸發條件。正式環境無可觀察行為改變（每次查詢仍拿到新 row），但 fixture 被前面案例永久標記後會讓後續案例靜默失效，導致席位消失而無錯誤訊息——此前誤判成 `ThreadPoolExecutor` race。與其等真踩到再修，不如趁改法只有一行時先做。測試端的共用 fixture 隔離結構刻意保留，與產品端的改動各自成立。

### 二、待辦「`CHUNK_SIZE` 單位不一致」：釐清落差、加切法出處，預設未動

**因果鏈**：`config.CHUNK_SIZE=800` 的單位是字元；`chunk_text`（`src/ingest.py`）呼叫 `RecursiveCharacterTextSplitter` 時原本沒傳 `length_function`，該 splitter 因此用 `len()` 計字元；但下游 embedding 模型消耗的是 token，中英文字元／token 換算比不同，同一個 `800` 對中文與英文代表的實際 token 量並不相等——本專案同時吃台股中文 PDF 與 SEC 英文 filing。

**換算比已用實測數字釘住。** 用 bge-m3 自帶的 tokenizer 對真實語料抽樣 400 塊實測：中文平均 1.60、英文平均 3.84 字元／token，**實際相差 2.4 倍**。同樣切 800 字元一塊，中文吃掉約 499 token、英文只有約 208 token，英文塊實際乘載的資訊量只有中文塊的四成左右。tokenizer 本身也不能借用：bge-m3 是 t5/sentencepiece 系列（Ollama `/api/show` 可得 `tokenizer.ggml.model = t5`），不是常見的 `tiktoken` BPE；`requirements.txt` 雖有 `tiktoken` 但全專案無程式碼引用，誤用它算中文會得到 0.68 字元/token，方向相反、差約 2 倍。驗證方式：本地 `tokenizers` 與 Ollama `/api/embed` 的 `prompt_eval_count` 對同一段文字計數，中英文皆完全相符。

**本次只改切法與建量測，不重灌全庫、不改預設值**：新舊塊混在同一張表裡相似度不可比，改預設必須連帶重灌。候選值（384／600／900 配 overlap 50／75／100）本次只產生量測數字，選值留待後續；量測顯示換 token 計數後中英文分佈立刻對齊（600/75 臂：中文中位 427、英文 475，原本按字元計是 398 對 178）。

**先不重灌是可行的決定**：真正該優先建置的共用前置能力是「按來源重跑 ingest」而非一次全庫重灌——財報來源實測僅 43 個，新聞雖來源數量多但 90 天內佔 98%、會自然汰換；`inventory` 盤點也驗證全庫 `chunk_unit` 目前全為 NULL，確認「只改切法、不改預設、不重灌」的決定確實生效。後續順序與 CP 值判斷詳見「目前待辦」第 2 項與「待建能力：按來源重跑 ingest」區塊。

**切塊出處三欄（`chunk_unit`／`chunk_size`／`embed_model`）是本次最關鍵的長期維護考量。** `doc_chunks` 原本無法回答「這塊是用什麼參數切的」，而語料持續增長——作業期間實測就從 9,333 → 9,445 → 9,739 塊，自動補抓每天都在寫入。這代表「先不重灌」期間，只要有人用 `CHUNK_UNIT=token` 跑過任何一次補抓，庫裡就會永久混入兩種切法的塊且事後分不出來。環境變數切臂的慣例用在 `FILTERS_MODEL`／`RETRIEVE_PARALLEL` 上是安全的，因為只影響當下查詢、不留下狀態；`CHUNK_UNIT` 不一樣，它會把結果寫進共用資料表，同一個慣例套在有持久化副作用的參數上並不成立。作法是 `doc_chunks` 加三欄，由 `insert_chunks`（`src/vectorstore.py`）統一補上當下設定值，呼叫端不必傳也不會忘記傳；既有 9,739 塊為 NULL，語意即「本欄上線前的舊塊」，不需 backfill。

`EMBEDDING_MODEL` 是環境變數，若計數函式寫死 `BAAI/bge-m3`，換模型時計數會靜默沿用舊 tokenizer。故加 `config.CHUNK_TOKENIZERS` 對照表，查不到對應模型一律退回字元計數並記 log。`_token_counter`（`src/ingest.py`）用 `functools.lru_cache` 當 lazy singleton，tokenizer 載入失敗同樣 log warning 並退回 `len()`（與 `_embed_in_batches` 的既有取捨一致），退回時留 log 才能事後用 `doc_chunks.chunk_unit` 交叉驗證，避免 A/B 數字無聲失真。`Dockerfile` 於 pip install 後預先把 vocab 烘進 image（約 17MB），避免執行期打 HuggingFace。

**刻意不做**：不抽 splitter 抽象層、不做 per-doc_type 參數、不建 chunk 策略註冊表——待辦「chunk 策略功能擴充」要換 parser 並改 schema，屆時形狀現在猜不準。`tiktoken` 雖無人引用但本次不刪，它是常見的 transitive 依賴且無 lock 檔佐證，順手刪是另一個變更。

**驗證結果**：char 路徑回歸（55 塊真實語料，改動前後逐塊 sha256 byte-identical）；`tests/test_ingest.py` 有／無 tokenizer 兩條路徑皆過；`tests/eval_rag_retrieval.py` 與基準逐字相同；新庫／舊庫 schema 一致（全新 pg 容器實跑 init.sql 驗證）；斷網（`--network none`）無 tokenizer 時不炸、退回字元計數並留 log；斷網＋預烘 vocab 時 token 計數可用，每塊 token ≤ 800（max 647）而字元數達 1064，證明限制的是 token 而非字元。

### 三、`rag_annotations.json` 標注過期與 checker 改為現算

`check_freshness`（`tests/eval_rag_retrieval.py`）原本用 `re.search(r"距今 (\d+) 天", item["expect"])` 從標注字串挖數字當斷言，要求完全相等，這讓 E1／E2／E3 三題隨補抓寫入新新聞就必然失效：實測 E1 期望 57 天、實際已是 2 天，E2 期望 59 天、實際 2 天，E3 期望 5 天、實際 0 天，且同一天內就在惡化（ASML 稍早是 3 天、稍後變 2 天）。B1／B2 是另一種病因：題目要測「該公司沒有該 doc_type 時的放寬重查」，但庫內 21 家公司已全部都有財報，情境根本觸發不了，checker 自己回「前提不成立」。

修法：`check_freshness` 改為從實際回傳的 chunks 現算標準答案，不寫在標注裡；標準答案是實際回傳的該公司新聞中最新那則，不是庫內最新那則——兩者常不同且差異合理（實測 ASML 庫內最新是 2 天前一則掛在 ASML 名下的大盤新聞，檢索挑的是 3 天前真正講 ASML 的那則；header 要忠實反映的是這次給 LLM 的素材有多新，拿庫內最新值去比會製造假警報，這點是修正過程中先寫錯、再由實測推翻的）。`check_relax` 加 `_company_missing(doc_type)`，題目指定的標的已不符情境時自動改找一家「有資料但缺該 doc_type」的公司重查，真的找不到就明確回報「此情境目前無法測」而非假裝失敗。標注檔移除所有寫死天數。

`tests/eval_rag_retrieval.py` 從 8/13 升至 **11/13**：E 系列三題全數通過且不再會過期；B1／B2 維持 FAIL，但訊息已是誠實的「此情境目前無法測」而非假警報。此兩項與 chunk 單位量測無關，是既有問題（`rag_annotations.json` 上次變動為 `65b1ba9`，早於本次）；本次改動前後跑同一支 eval 結果逐字相同，確認非本次引入。

### 四、logfile 保留策略與敏感資料：量測後維持 30 天

待辦原列「`LOG_BACKUP_DAYS=30`（`config.LOG_BACKUP_DAYS`）是接手來的額定值、從未校準過，與已撤下的 `_MAX_TOOL_ROUNDS=4` 同一個毛病」，本次查證後判斷該類比只對了一半：`_MAX_TOOL_ROUNDS` 的值會**改變系統行為**（截斷補抓循環），這個值只決定磁碟佔用，調錯的代價不對等。

**兩個疑慮都已落地查證**。個資：`src/graph.py` 的 `log_duration` 呼叫點確認只記 `prompt_chars`／`answer_chars` 長度，`qid` 是提問的雜湊而非原文，log 裡沒有任何提問或回應內容，故無去識別化需求。磁碟：`data/logs/` 累積 **1.3 MB／約 8 天**（含 09-13 至 09-20 的密集開發與 A/B 期間，屬高於日常的使用量），依此外推 30 天約 5 MB——距離任何值得校準的量級都還很遠，訂 30 或 90 在實務上沒有差別，**校準這個值不會改變任何決策**。

**結論：撤下待辦，移入「已評估不採用」，維持 30 天。** 觸發條件有二，缺一不可：若日後為了回測要記錄 prompt／回應全文，需先決定保留天數與去識別化方式（專案已有 `NEWS_RETENTION_DAYS`／`THREAD_RETENTION_DAYS` 的慣例可循，後者註解明確指出「對話含提問內容，屬個資，留短一點」）；或日檔量級成長到 GB 等級。在那之前這個值不需要依據，只需要夠大。

### 改動內容

| 項目 | 涉及檔案與函式 | commit |
|---|---|---|
| `_relax_doc_type` 改回傳複本 | `src/graph.py` 的 `_relax_doc_type`：`d["relaxed"] = "doc_type"` 就地寫入改為 `return [{**d, "relaxed": "doc_type"} for d in docs]` | `76fbde1` |
| 測試註解更正 | `tests/test_retrieve_context.py` 的 `recording_search` 與 `_fresh`：原註解描述「`_relax_doc_type` 會就地寫入」這個已不存在的行為，改為說明回新 dict 是模擬正式環境每次查詢拿到新 row，作為防呆隔離 | `76fbde1` |
| 待辦編號改指名 | `tests/test_answer_format.py`：「待辦第 2 項」改為指名項目名稱，避免待辦編號浮動導致失準 | `76fbde1` |
| `CHUNK_UNIT` 開關與 `CHUNK_TOKENIZERS` 對照表 | `src/config.py`：`CHUNK_UNIT`／`CHUNK_SIZE`／`CHUNK_OVERLAP` 補環境變數覆寫，新增 `CHUNK_TOKENIZERS` | `ca92880` |
| `_token_counter` 與 `chunk_text` 的 `length_function` | `src/ingest.py` | `ca92880` |
| 切塊出處三欄統一寫入 | `src/vectorstore.py` 的 `insert_chunks` | `ca92880` |
| `doc_chunks` 加三欄（CREATE 與 ALTER 兩路徑） | `db/init.sql` | `ca92880` |
| `tokenizers>=0.20` 依賴與 vocab 預烘 | `requirements.txt`、`Dockerfile` | `ca92880` |
| `chunk_text` 單位的 self-check（兩條路徑） | `tests/test_ingest.py` | `ca92880` |
| token 分佈量測腳本（新增） | `tests/bench_chunk_tokens.py` | `ca92880` |
| `check_freshness` 改為從回傳 chunks 現算天數 | `tests/eval_rag_retrieval.py` | `6e9594b` |
| `check_relax` 加 `_company_missing` 自動換標的 | `tests/eval_rag_retrieval.py` | `6e9594b` |
| 標注移除寫死天數 | `tests/eval_data/rag_annotations.json` | `6e9594b` |

---

## 2026-09-21　META 財報全文缺失的查證修復、來源盤點查詢與多輪對話市場不一致修復

六件獨立工作，同日並列非同一條線：先查證並修復 META 財報全文缺失；再從「待建能力：按來源重跑 ingest」六項裡挑出第 1 項（來源盤點查詢）單獨實作——純讀、不改資料，價值不依賴重跑功能存不存在，且是 META 那類問題唯一的系統性防線；接著修復正式環境實際發生的多輪對話市場不一致問題；接著回頭重數 AI 執行時間分佈，回答「目前待辦」第 6 項懸而未決的瓶頸佔比問題；接著查證待辦第 3 項（數字類查詢直答通道，原第 5 項）原寫的前置問題是否成立；最後處理待辦第 5 項（新聞來源的視窗限制與本地留存）——查證原文預期做法的前兩步是否成立、找出真正的新聞缺口、修復其中一項路由 bug、並補上台股中小型股的新聞來源。

### 一、META 財報全文缺失的查證與修復

查證「目前待辦」原第 11 項（META 財報全文缺失）並實跑驗證，確認根因與修復皆已完成，故不再列入待辦。

**現象**：META 在 `doc_chunks` 只有 1 塊財報（`SEC-XBRL:META:0001628280-26-050705`，621 字元的 XBRL 數字塊），EDGAR 全文塊數為 0。全庫 14 家美股標的中只有 META 的全文軌掛零（對照 NVDA 586、MSFT 527、JPM 1,533 塊；ASML 與 TSM 走另一軌故無 XBRL，全文分別有 104、371 塊）。

**已排除來源問題**：直接下載該申報的 10-Q 得 428,960 字元的完整內容，文件存在且完整，抓取路徑與選檔邏輯都沒問題。

**根因是入庫階段的 embedding 失敗**：`data/logs/` 留有兩筆證據。`ingest` 記過 WARNING「財報字數偏低，可能選錯檔案或內容不完整」（`source=SEC-XBRL:META:...`、`chars=621`、`min_chars=10000`）——即 09-14 建立的低字數防線有攔到，但只攔到 XBRL 那塊，全文軌整個沒進來這件事它看不到。`graph` 記過 INFO「auto_fetch 單一來源失敗」（`company=META`、`elapsed_ms=62150`、`error=Post "http://127.0.0.1:.../tokenize": EOF (status code: 400)`）。即 EDGAR 全文抓到了，但送 Ollama 做 embedding 時失敗，該軌整份沒入庫，只剩 XBRL 那塊留下。這與 2026-09-19 章節 `EMBED_BATCH_SIZE` 定案時處理的是同一類資源型失敗（該次 JPM 1,533 塊正是靠分批與重試才過關），META 這份 428,960 字元屬同量級的長申報。

**修復與驗證**：執行 `python -m src.update report --market us --company META --form 10-Q`，重跑前後對照如下。

| | 重跑前 | 重跑後 |
|---|---|---|
| EDGAR 全文 | 0 塊 | 740 塊（469,231 字元）|
| XBRL 數字 | 1 塊 | 1 塊 |
| 全庫總塊數 | 10,134 | 10,874 |

**關鍵觀察是失敗確實重現、但被重試接住**：重跑過程中 log 仍印出「embedding 批次失敗，重試一次」，740 塊全部入庫。這證實兩件事——根因判斷正確（是 embedding 資源型失敗，非來源或選檔問題），且 `EMBED_BATCH_SIZE=400` 的分批與重試確實能解掉它。

這筆失敗發生在 2026-09-20 23:57，晚於 `EMBED_BATCH_SIZE=400` 於 09-19 上線，照上線日期推斷會誤判「不會再發生」，但它當下仍然發生了——能確認是否解掉的只有實跑。

**已知限制**：這筆之所以拖到 09-21 才發現，是因為低字數警示只在入庫當下觸發，沒有機制回頭問「某標的的全文軌是不是整個沒進來」。「已評估不採用」`CHUNK_SIZE` 單位一項所指的「按來源重跑 ingest」能力可順帶覆蓋這個場景——重跑前先比對各標的的軌別塊數即可發現同類缺口。這個缺口偵測需求正是下一節的起點。

### 二、來源盤點查詢（`inventory` 子命令）

「待建能力：按來源重跑 ingest」六項裡的第 1 項，刻意先單獨做：它純讀、不改資料，價值不依賴重跑功能存不存在，光是缺口偵測這一點就值得，而且是上一節 META 那類問題唯一的系統性防線。

**為什麼需要**：`src/vectorstore.py` 原本只有 `source_exists(source)`（單一來源在不在，回布林），沒有任何函式列得出來源。要問「庫裡有哪些來源」「哪一軌整個沒進來」，在此之前只能臨時手打 SQL，沒有可重複執行的東西。

**改動**：`src/vectorstore.py` 新增 `list_sources(doc_type, company)`，一支 SQL 依 source 聚合，回 source／prefix／doc_type／company／published_at／chunks／chunk_unit／chunk_size／embed_model；後三欄取 `min()`，因為同一次 ingest 寫入的塊設定相同。`src/update.py` 新增 `inventory()` 與 `inventory` 子命令（唯讀），落在 `update.py` 而非 `ingest.py`，與未來的重跑函式同一支 CLI。執行方式：`docker exec finance_ai_assistant_app python -m src.update inventory`，可加 `--doc-type`／`--company` 篩選。

**實跑結果（2026-09-21）**：來源前綴分佈為 `EDGAR` 16 源 6,718 塊、`https`（新聞）525 源 2,690 塊、`data/*.pdf` 9 源 1,445 塊、`SEC-XBRL` 12 源 12 塊、`TWSE-API` 6 源 9 塊，合計 568 源 10,874 塊。切法出處三欄顯示全庫都還是舊切法（`chunk_unit` 全為 NULL），與 chunk 單位那條線的重估一併記在 2026-09-20 章節第二節。

**缺口判定不能無腦報警，初版只判美股，範圍隨後擴及台股。** 美股雙軌（2026-09-09 建立）正常應有 `EDGAR` 全文與 `SEC-XBRL` 數字兩軌，但 ASML 與 TSM 是 F 股、不報 XBRL，`SEC-XBRL` 欄本來就是 0，那是正常的。初版規則因此訂為「只有 `EDGAR` 全文軌掛零才算缺口，只缺 XBRL 一律視為正常」，但完全沒碰過 SEC 兩軌的台股標的（`TWSE-API`／本地 PDF）當時整個不進軌別表，等於台股整軌掛零也查不出來——這條規則只顧到已知的兩個 F 股例外，卻沒發現自己把另一個市場整個漏掉了。

**擴充為兩個市場對稱判定，並立刻抓到一筆真缺口。** 改版後台股與美股各有「全文軌」與「數字軌」：台股是 MOPS PDF（`data/*.pdf`）全文＋`TWSE-API` 數字，美股是 `EDGAR` 全文＋`SEC-XBRL` 數字；本地 PDF 的 source 是檔案路徑、沒有共同前綴，故以「非其他三種前綴」歸入台股全文軌。市場歸屬刻意走 `is_tw_ticker(co)` 判斷，不看「碰巧有哪幾軌」——若照後者判，某標的兩軌全掛零時會被判成「不屬於任何市場」而靜默跳過，那正是最該被抓出來的情況，是這次改動裡唯一不明顯但關鍵的設計選擇。擴充後立刻抓到一筆真缺口：**2380（華新科）的數字軌掛零**，7 家台股標的中只有它沒有任何 `TWSE-API` 來源，其餘 6 家都有 `TWSE-API:<代號>:115Q2`。補跑 `fetch_tw_financials('2380')` 一次就回 `ok=True`（detail 為「已匯入 2380 115Q2 財報數字（證交所 OpenAPI）」），全表回到正常。（該筆入庫時跳出「財報字數偏低」警示屬預期，`TWSE-API` 軌本來就只有數字、僅 1 塊。）

**補抓機制本身正確、也涵蓋 2380，只是它在查詢當下才評估。** `src/mcp_server.py:125` 與 `src/graph.py:766` 在資料超過門檻時會自動注入「請呼叫 `fetch_company_data` 補抓」的指示，`has_report` 以 `_REPORT_FRESH_DAYS = 120` 天為界（`src/mcp_server.py:186`），不涉及任何人為判斷。2380 的本地 PDF 是 2026-02-01、距今 232 天，遠超過 120 天門檻，`has_report` 會是 `False`，財報兩軌都會被排進 `calls`——只要有任何一次查詢碰到 2380，補抓就會自動觸發，補跑實測 `ok=True` 正是佐證。全專案 `fetch_missing_data`／`fetch_company_data` 的呼叫端只有 `retrieve_context` 與 tool loop，沒有任何排程會走過標的清單做過期檢查。2380 的 232 天缺口留著，不是檢查判錯或補抓失敗，而是那個檢查從來沒有機會執行——沒有被評估過的資料，不會變成「過期」。覆蓋範圍因此跟隨查詢流量、而非標的清單，冷門標的的缺口會無聲累積；盤點查詢補的正是這個洞，它一次走完全部標的，不管有沒有人查過。

**這與上一節的 META 是完全不同的兩種病，正是本次查證最有價值的結論。** META 是檢查執行了、補抓也觸發了，但 embedding 失敗導致整軌沒入庫——有失敗、警示也響了，只是響錯地方（只看到 XBRL 那塊字數低，看不到全文軌掛零）。2380 是檢查從未被執行，因此沒有任何失敗、也沒有任何警示有機會響。兩種缺口在事中都看不見，只有事後全庫盤點問得出「誰的某一軌是空的」——這正是盤點查詢的價值所在。

**美股單軌的判定原本有漏洞，一併修掉。** 初版規則「只缺 XBRL 就當正常」的理由是 ASML／TSM 是 F 股、SEC 不收其 XBRL，但這條規則等於任何美股標的缺數字軌都會被放行——META 修復前只剩 1 塊 XBRL 的反例照樣溜過去，只是當時沒被拿來檢驗。改為白名單 `_NO_NUM_TRACK = {"ASML", "TSM"}`：只有這兩家缺數字軌算正常，其餘一律報「缺口：數字軌（SEC-XBRL）掛零」。

**self-check 擴到 8 組**：初版 4 組只驗美股，新增台股缺數字軌（2380 實況）、台股兩軌俱全、台股全文軌掛零、AAPL 缺 XBRL 必須報缺口（驗白名單沒有過度放行）。過程中發現「不可誤報」的斷言（`"缺口" not in out`）因表頭文字含「缺口」二字而永遠為真、其實沒在驗，改掉表頭後斷言才真正有效。

**已知限制**：app container 沒有 bind mount，程式碼是烘進 image 的，驗證期間累計用 `docker cp` 送進 container 的檔案已有四個（`update.py`／`vectorstore.py`／`config.py`／`ingest.py`）——中途曾踩到 container 內的 `config.py` 仍是舊版、缺 `CHUNK_UNIT` 而報 `AttributeError`。image 隨後已重建，驗證方式與結果見下一節。

**刻意不做**：不做 Web UI、不做定時掃描告警，等真的每天在看再說，現在手動跑一次就夠。

**回歸**：`tests/test_ingest.py` 通過。

**順帶查證 6514：資料面沒有問題，是 log 標註問題。** `auto_fetch` 名單裡出現、但 `doc_chunks` 完全沒有資料的 6514，三個來源其實都查無此公司，各自留有明確且不同的失敗原因：`update` WARNING「官方 OpenAPI 查無 6514（可能為興櫃、金融業或已下市）。」（`source=twse_api`、`reason=api_miss`）、`update` WARNING「MOPS 查無 6514 的財報檔案。」（`source=mops`、`reason=mops_blocked`）、`update` WARNING「6514.TW 的 RSS 沒有新聞。」（`source=yahoo_rss`、`reason=no_content`）。三筆對應的「auto_fetch 單一來源完成」皆為 `ok=false`，行為正確、降級如預期。

但第四筆是 `ok=true`，而庫內 6514 一塊資料都沒有。比對時間戳，該筆（`2026-09-20T22:53:30.585`、`elapsed_ms=22047`）實際對應的是同一時刻完成的市場總覽新聞抓取（`update` INFO「市場新聞更新完成，共寫入 3 筆 chunk，跳過 16 篇已入庫。」，寫入的 chunk `company` 皆為 null）。成因在 `src/graph.py` 的 `fetch_missing_data`：`calls.append(lambda: fetch_market_news(3))` 把市場總覽新聞併進同一個 `calls` 迴圈，迴圈內的 `log_duration(...)` 一律帶 `company=company`（該次查詢的標的），市場新聞與特定公司無關，於是被標成觸發該次查詢的公司。

**這是紀錄標註問題，不是抓取或入庫的錯誤**：資料本身寫對了（`company=null` 的全域新聞），錯的是 log 把它歸給了某家公司。實際後果是回測時 `auto_fetch` 的 company 統計會灌水——每次查詢都會多一筆掛在該公司名下的 `ok=true`，讓「某公司抓取成功率」失真，也會讓人誤以為 6514 有成功抓到東西。這與 2026-09-13 章節建立的可觀測性目標直接相關（logfile 要答得出「哪個節點花了多久、成功與否」）。**已於本次修掉，詳見第四節。**

### 三、重建 image 並驗證

**結論：image 已重建並換上，`docker cp` 送進去的四個檔案已隨舊容器消失，本節驗證跑的都是 commit 裡的程式碼。**

`docker compose build app` 成功，含預先烘 bge-m3 tokenizer vocab 的那層；`up -d app` 換上新容器後以 `docker inspect` 確認映像為本次 build 產出。

**`inventory` 驗證**：從烘進 image 的程式碼執行成功，21 檔標的全部「正常」，ASML／TSM 正確標為「僅全文軌（F 股不報 SEC-XBRL，正常）」，無任何缺口警示。來源數 567／塊數 10,865，與「### 二」記錄的 568／10,874 略有差異，原因是期間新聞持續被掃入與汰換（新聞來源 524→523），非重建造成。

**測試**：`tests/test_inventory.py` 通過；`tests/test_ingest.py` 通過，且沒有印出「tokenizer 不可用，已退回字元計數」那行 log——代表 `CHUNK_UNIT=token` 那條路徑真的走到了 tokenizer，不是無聲退回字元計數，這是烘進 image 的 vocab 第一次在乾淨 image 上得到驗證。`tests/eval_rag_retrieval.py` 13 題中 11 題通過，兩題 FAIL 是 B1、B2（`doc_type` 濾空放寬重查），checker 自己回報「前提不成立」：該情境需要「庫內有資料但完全沒有 financial_report」的公司，而目前 21 家標的全部都有財報（本次 2380 補抓也有貢獻），故該規則暫時無標的可測。這不是回歸，放寬重查的程式碼根本沒被執行到——這正是 2026-09-20 章節把 checker 從寫死天數改為現算、並讓它誠實回報前提不成立所要達成的效果，它主動說出自己測不到，而非假裝通過。

**已知限制**：B1／B2 目前無法測，需等出現新的「有資料但缺財報」標的，或改用構造資料補測，與 `tests/test_inventory.py` 不打實庫是同一個理由。本次未處理。

### 四、auto_fetch 的 log 標籤修正與來源追蹤

承第二節 6514 查證發現的標籤灌水問題，本次修掉，並順帶補上 `source` 欄位。

**改動**：`src/graph.py` 的 `fetch_missing_data` 把 `calls` 從單純的 lambda 改成 `(company, source, fn)` 三元組，`fetch_market_news` 那筆帶 `company=None`；每筆新增 `source=` 欄位取函式名，成功與失敗兩處 `log_duration` 都帶。`has_report` 的 `calls[-1:]` 與「新聞排最後」的順序契約未動。

**不拆獨立節點**（曾考慮 `node="auto_fetch_market"`）：`node` 在本專案是節點歸屬，一個節點可有多個計時點——這正是 2026-09-19 章節記取的教訓（`market_snapshots` 誤用 `node="generate"`，因為它真的是另一個節點才改成 `node="market"`）。`fetch_market_news` 與其他來源在同一個 `auto_fetch` 節點的同一個迴圈裡，拆節點會重蹈覆轍，且既有 log 檔不會回填，留下新舊標籤混雜的分析陷阱。`company=None` + `source=` 是以既有維度描述事實，不新增標籤空間。

**「單一公司內的來源補抓改為並行」一項自此可由 log 直接查**：原本「最慢的一律是 `fetch_mops`／`fetch_edgar` 那一筆，5/5」是人工比對得出的，現在 `source` 欄位讓它變成一行彙總查詢。該項結論（收益太小、有觸發條件才動）不變，但觸發條件所需的新數據不必再靠人工重數。

**回歸**：`tests/test_fetch.py` 補上 log 欄位斷言（攔 `graph.log_duration` 收欄位，驗正常與例外兩條路徑的 company／source，以及市場新聞那筆為 `company=None`），並做過變異驗證——故意把市場新聞那筆改回帶 `company`，斷言確實失敗。全部 31 個 test script 通過。

### 五、多輪對話市場不一致的查證與修復

**現象**：正式環境使用者第一輪問禮來（LLY，美股醫藥），第二輪追問「美股醫藥有無其他建議投資標的？建議操作如何？」，回覆卻整篇是台股內容（台股大盤 46,164.72、40~50% 現金水位、台股債殖利率），來源為 cmoney.tw／money.udn.com。

**根因是檢索層，不是 prompt 層，四個成因疊加**：`rewrite_question` 把語法完整但語意依賴上下文的追問原樣放行；`_retrieve_sequential` 抽不到 company 時早退，只做一次未補強的檢索；`market` 從未參與檢索過濾；決策卡「不得整段棄權」規則逼模型用撈到的素材填版面。關鍵驗證：即使直接餵原問句，`extract_filters` 本來就正確抽出 `market=us`，檢索仍回傳 4 筆台股／不明文件——證明缺陷在檢索層，改 prompt 救不了。

**一次失敗的嘗試**：先單獨改 `rewrite_question` 的 prompt，結果讓問題更嚴重——改寫後變成「請同時提供台股與美股兩邊的醫藥股」，`market` 從 `us` 被改成 `both`，檢索由 `{unknown:4, us:1}` 惡化為 `{unknown:5}`，唯一對題的文件反而被擠掉。原因是 prompt 裡既有的「『都要』→ 請同時提供台股與美股兩邊」模板與新規則衝突，該次修改已 revert。

**新建題組先確認紅燈**：`tests/eval_multiturn_market.py` + `tests/eval_data/multiturn_annotations.json`，9 題涵蓋多輪承接（市場延續／主體延續）、多輪換題、反問回答、單輪對照五類，判準是檢索回傳文件的市場分佈，不跑 `generate`。與既有兩支 eval 的差異：`eval_extract_filters.py` 單句進、`history` 寫死為空；`eval_rag_retrieval.py` 直接把 company 當輸入餵檢索，不經改寫與抽取；兩支都測不到第二輪追問這條路徑。「單輪對照」類同一問句有無 `history` 各跑一次，用來分辨失分來自改寫層還是檢索層。紅燈基線 **2/9**。

**修復分四處**：

1. **qid 計算改用改寫後問句**（`src/graph.py` 的 `rewrite_question`）。原本 qid 用改寫「前」的問句算，但下游節點看到的都是改寫後的問句，同一題的耗時記錄因此串不起來。
2. **`both` 過度指派**（`src/graph.py` 的 `rewrite_question`）。市場消歧模板原本無條件寫進 prompt，模型把「請同時提供台股與美股兩邊」當通用句型往外套，「美股半導體最近如何？」也會被改成兩邊都要。改為只有偵測到「這輪是市場反問的回答」（`_last_turn_is_market_reask()`：判斷依據為 `i18n` 的 `ask_market` 文案結尾固定句、加上該輪確實提及雙掛牌代號，兩者皆成立才算）才把該段規則附進 prompt，並加一條「只補回缺少的資訊，不得增加使用者沒問的東西」。
3. **新增 `market` 欄位**（`db/init.sql`、`src/ingest.py`、`src/update.py`、`src/vectorstore.py`）。`doc_chunks` 新增 `market VARCHAR(2)`（`tw`／`us`／`NULL`＝不明）與索引。寫入端決定市場歸屬：有 company 的塊由 `is_tw_ticker()` 推定；市場新聞（無 company）改由來源 key 的 `_tw`／`_us` 尾碼判斷，無法判斷的（如 cmoney 的 tag 頁）回 `None` 不猜。**已排除的做法**：曾評估直接用代號字面推導（`^\d` 判台股），但港股 0700、日股 7203 會誤判，且推導會散落到每個檢索呼叫點、沒有單一維護位置，故未採用。
4. **檢索層過濾**（`src/vectorstore.py`、`src/graph.py`、`src/mcp_server.py`）。`similarity_search` 新增 `market` 參數，指定市場時 `market IS NULL` 的塊一併排除——放行等於讓認不出市場的市場新聞繼續填版面，正是原本的病灶。`retrieve_context` 入口把 `"both"` 收斂為 `None`（不限制）。MCP server 是獨立行程讀不到 graph state，`market` 只能當 tool 參數傳遞；為避免模型自行從問句臆測，`_seed_prompt` 直接寫明「本次檢索的市場：美股（us），請把 us 填進 market 參數」，tool 說明同步註明「沒指明就留空，不要自己從問題推測」。

**回填**：有 company 的 10,442 塊由代號格式一次性 UPDATE 標記（21 家標的，tw 7／us 14，TSM 與 2330 正確分屬 us／tw）；市場新聞靠標題結構化尾碼回填 258 塊。**最終覆蓋率 10,700／10,865＝98.5%**，剩 165 塊為 `NULL`，分兩種成因：137 塊來自 cmoney（URL 形狀與標題皆無市場線索，無法回填），28 塊來自未納管版面的 udn／cnyes（可回填，待決定是否納管）。寧可留白不摻假，詳見「目前待辦」的已知限制。

**兩處誤報，修的是題組而非程式**：一是題組的 `market_of()` 原本從 company 推市場，市場新聞的 company 恆為 `NULL`，把已標好 `market` 欄位的塊誤判成 unknown，改為優先讀 `market` 欄；二是 `company=2330` 配 `market=us` 屬矛盾條件，但 `resolve_market` 本來就會把 2330 對齊為 TSM，是題組跳過了該節點，補進後恢復正常。

**結果**：題組 **2/9 → 9/9**（五類全綠）。正式環境那題 `{unknown:4, us:1} → {us:5}`；「美股半導體最近如何？」的檢索結果由台股文件混入 3 筆降到 0 筆，現為 7/7 美股。`docker compose build` 重建 image 後複驗：全套測試 35/35、題組 9/9；`eval_rag_retrieval.py` 11/13，兩筆 FAIL 為既有的「前提不成立」情境（詳見本章第三節），非本次造成。

**原規劃第四步（`_retrieve_sequential` 無 company 早退時補強）評估後不採用**，詳見「已評估不採用」區塊。

**新增測試**：`tests/test_market_reask_detect.py`（守住 `both` 錯掛與漏掛）、`tests/test_market_column.py`、`tests/test_market_filter.py`；`tests/test_mcp_tools.py` 的既有 lambda stub 補上 `market` 參數並增補傳遞案例。

### 六、AI 執行時間的重數：瓶頸結論成立、離群未複現

承「目前待辦」第 6 項：`generate` 累積筆數已過門檻，本次重數並回答該項留下的兩個問題——瓶頸佔比多少、09-19 記錄的 12 輪離群題是否複現。

**量測範圍**：`data/logs/app*.log` 全部檔案（含 `app-2026-09-13` 至 `app-2026-09-20` 六個歸檔、`app.log`、`app-local*.log`），過濾條件沿用 09-19 定案的 `select(.message=="generate")`，不變。

**第二個計數陷阱，與 09-19 那個方向相反**：`cat data/logs/app*.log | jq -c 'select(.message=="generate")' | wc -l` 只數到 16 筆，與逐檔加總的 51 筆不符。原因是串流中某一檔有一行格式異常的 JSON 讓 `jq` 直接中斷，後續檔案完全沒被讀到——這是 `jq` 串流中斷的問題，跟 09-19 記的「`node=="generate"` 誤把行情抓取那 12 筆算進去」是不同性質的陷阱：09-19 那個是標籤語義錯誤（會高估），這次是串流中斷（會低估）。正確做法是逐檔各自過濾再相加：`for f in data/logs/app*.log; do jq -c 'select(.message=="generate")' "$f" 2>/dev/null; done | wc -l`。

**全域節點耗時（依總耗時佔比排序）**：

| 節點 | 事件數 | 中位數 | 總耗時佔比 |
|---|---|---|---|
| `generate` | 51 | 176.2s | 52.6% |
| `agent` | 104 | 45.1s | 38.0% |
| `extract_filters` | 52 | 18.0s | 6.3% |
| `rewrite_question` | 25 | 12.8s | 2.1% |
| `market_snapshots` | 37 | 4.0s | 1.1% |
| `retrieve_context` | 6 | 0.5s | 0.0% |

**「瓶頸是 generate」現在成立，09-19 留下的矛盾已消失**。09-19 記的是「總佔比與每題內佔比兩種算法排序相反，代表樣本不足」；限定同時具備 `generate` 與 `agent` 事件的 43 個完整題（`retrieve_context`／`market_snapshots`／`extract_filters`／`rewrite_question` 未必每題都有事件，只算兩者皆有的完整題才有意義）重算每題內佔比：`generate` 平均 59.1%／中位 63.1%，`agent` 平均 32.9%／中位 29.1%，`extract_filters` 平均 7.9%／中位 6.0%，三項與全域總佔比排序一致，`generate` 兩種算法都是第一。每題總耗時中位 275.4s、最大 2168.9s。

**per-question 佔比同樣有計算陷阱，記在此處避免下次重踩**：若不篩「完整題」，直接對全部 67 個 qid 算每題內佔比，會得到 `retrieve_context` 100%、`rewrite_question` 87.9% 這種失真數字——因為部分 qid 只記到單一節點的事件，該節點自然佔該題 100%。必須先篩出同時有 `generate` 與 `agent` 事件的題目，篩完剩 43 題才有意義。

**09-19 留下的離群待查已關閉，未複現**。當時記「那題 12 輪、總耗時 2168.9 秒的離群若能複現，比 `generate` 更該先查」。本輪 agent 輪數中位數為 2，最大值仍是同一題（qid `86bcf494`，明細 `agent` 1231s／`generate` 846s／`extract_filters` 84s／`rewrite_question` 8s），沒有出現第二個同量級樣本，故此分岔關閉、不轉為獨立待辦。次高兩題為 746.5s 與 657.4s，結構同樣是 `agent` 略高於 `generate`，但未達離群量級。

**連帶影響「數字類查詢的直答通道」一項的論證**：`retrieve_context` 中位 0.5s、總佔比 0.0%，繞過檢索省下的延遲實質為零，「降低延遲」這半個理由不成立，該項改動說明已同步調整，詳見「目前待辦」第 3 項。

### 七、待辦 3（原待辦 5）的前置問題查證：出處標註不是問題，缺的是錯誤率

待辦「數字類查詢的直答通道」原寫的前置問題是「直答的數字若不進 `retrieved` 就沒有 `[來源N]` 編號……需先決定這類數字如何標註出處」。本次純讀查證程式碼，**結論：這個前置問題不成立，出處本來就在，不需要另外決定標註方式。**

**查證依據（純讀，無程式改動）**：

- `src/graph.py:1220` 的 `unique_sources(retrieved)`——引用編號的唯一輸入，只依 `doc["source"]` 這個字串欄位依出現順序去重，不綁向量檢索、不綁相似度分數。
- `src/graph.py:1250` 附近的 `generate()`——context block 組成 `[{src_label}{idx}] {src}（{date}）`，編號完全由 source 字串的排序決定，與該筆資料是否來自向量檢索無關。
- `src/update.py:500` 的 `source=f"SEC-XBRL:{ticker.upper()}:{accession}"`、`src/update.py:643` 的 `source=f"TWSE-API:{co_id}:{label}"`——結構化數字本來就帶完整的出處字串。
- `src/ingest.py:118` 的 `ingest_text()`——XBRL／TWSE 數字走的是與新聞塊完全相同的入庫路徑，寫進 `doc_chunks` 時 `source`／`content`／`published_at` 齊全，無結構差異。

直答的數字只要照常 append 進 `retrieved`，`[來源N]` 編號、來源列表、反幻覺規則（`src/i18n.py` 的 `trend_rules_common`）全部沿用現有機制自動成立，不需另立標註方式。

**真正的前置改為缺少數字題答錯率的量測**。2026-09-19 的結論是 XBRL 塊已排第 1，代表數字題的檢索現在就常常是對的；在沒有量到數字題答錯率之前動工，會重蹈 `CHUNK_SIZE` 那一項的覆轍——機制做得出來，但選不出值、也證明不了改善，不符合專案「效能參數須有實測數據、不接受推導」的慣例。量這個錯誤率需要的正是待辦 2 卡住的 golden set（其八類中就有「單一數值」「表格問答」）。

**待辦 3、待辦 2、已撤下的 `CHUNK_SIZE` 三項因此卡在同一個決策前置——golden set。**

### 八、新聞來源的視窗限制與本地留存——前兩步已成立、真缺口在台股中小型股、修掉一個路由 bug

待辦原文的預期做法依序為：(a) 落地保存 (b) 新增來源並行 (c) 時間分層 (d) 跨來源去重 (e) 熱門標的定時抓取。

**(a) 與 (c) 已經成立，不必做**：`doc_chunks` 新聞 523 篇／2,680 塊，`published_at` 範圍 2026-04-30 至 2026-09-20（約 5 個月），`published_at IS NULL` 為 0 筆。`retrieve_context`（`src/graph.py:511`）本來就直接打 `similarity_search`，補抓只在 `route_after_tools` 判定過期或漏查時才走——「落地保存＋查詢優先走自己的庫」與「時間分層」在現行架構上已等價成立，原文把它列為第一步是寫待辦時的誤判。

**另一項併入待辦後隨本輪結案：跨市場比較題的檢索素材落差**。原本另立一項「跨市場比較題的檢索素材落差」，前提是「語料以台股為主，美股標的往往沒有敘事文件」，2026-09-21 實測推翻此前提——直接查 `doc_chunks` 得到財報／新聞塊數如下。

| 標的 | 財報塊 | 新聞塊 |
|---|---|---|
| JPM | 1,534 | 117 |
| NVDA | 587 | 239 |
| MSFT | 528 | 223 |
| 2454（聯發科） | 503 | 93 |
| 2330（台積電） | 286 | 217 |

美股敘事文件不但不缺，財報塊數反而居全庫之冠——NVDA 587 塊還多於原例對照的聯發科 503 塊，原因是 2026-09-09 章節建立的 SEC 雙軌（`fetch_edgar` 全文、`fetch_sec_financials` 的 XBRL 數字）。**真正的落差在新聞覆蓋不均，不在財報**，而新聞覆蓋不均正是本項（待辦 5）要解的問題，本輪已一併補齊（詳見下方新聞缺口與來源選型段落）。故此項併入待辦 5 後，隨本輪一併結案、自待辦移除，不另立來源工程。

**真正的缺口是 4 檔零新聞，且成因分兩種**：

| 標的 | 財報塊 | 新聞塊 | Yahoo RSS 現況 | 成因 |
|---|---|---|---|---|
| TSM | 371 | 0 | 回 20 篇 | 抓取從未被觸發，屬程式缺陷 |
| 3049（精金科技） | 107 | 0 | 回 0 篇 | 來源不覆蓋 |
| 2380（虹光精密） | 95 | 0 | 回 0 篇 | 來源不覆蓋 |
| 3025（星通資訊） | 87 | 0 | 回 0 篇 | 來源不覆蓋 |

來源缺口只發生在台股中小型股（2330／2454／2308 等大型股 Yahoo 都有覆蓋）；美股那側 Yahoo 覆蓋完整，不需要新來源。

**TSM 的成因是路由層 bug，已修**。`_stale_companies()`（`src/graph.py:962`）回傳 `(stale, missing)`，`route_after_tools`（`:1162`）兩者都用：`if stale or missing: return "agent"`；但 `agent` 節點（`:821` 修復前）原為 `if stale := _stale_companies(state)[0]:`，只取 `stale`、丟掉 `missing`。零新聞標的永遠落在 `missing`，於是路由把它送回 agent，agent 卻收不到指名該補哪一家的 directive——`graph.py:817-819` 的註解明寫「模型讀到『該補抓』會照做卻補錯家，所以要程式直接指名」，`missing` 這條路正好繞過該機制，是兩處共用 `_stale_companies` 要防的漂移本身已經發生。log 佐證：修復前的「指名過期標的」紀錄只有 `stale` 欄位（例 `{"node":"agent","stale":["2308","2330","SPCX"]}`），從無 `missing`。修法（`src/graph.py:820-829`）：改為 `stale, missing = _stale_companies(state)`，兩者措辭分開——`missing` 沒有天數可填，用「完全沒有檢索到新聞」，硬湊數字會讓訊息與 log 都失真；log fields 加 `missing`。

**來源選型：三個候選被實測淘汰**：

| 候選 | 實測結果 | 判定 |
|---|---|---|
| Google News RSS（原文點名） | 標題精準，但 link 是不透明 wrapper，`trafilatura` 抽出 0 字元（581KB）；解 wrapper 需打未公開的 `batchexecute` 端點，實測解不出原始 URL | 否決：維護性差，且會靜默退化成只存標題 |
| yfinance `get_news`（原文點名） | 2380／3049／3025 一律回 0 篇，與 Yahoo RSS 同源 | 否決：解不到缺口 |
| cnyes `/tag/<代號>` | 頁面 JS 渲染，regex 抓到的是側欄熱門新聞——三個不同代號抓到完全相同且與該公司無關的三篇 | 否決：會把不相干新聞掛到錯的公司名下，比沒有更糟 |
| Yahoo 台股個股頁 `tw.stock.yahoo.com/quote/<代號>.TW/news`（採用） | 每檔 20 篇、靜態 HTML、跨代號零重疊（2380∩3049=0、2380∩2379=0）、標題確為該公司、`bare_extraction` 抽得 5,537~6,485 字元且日期正確 | 採用 |

採用案與現行 RSS 同母站但不同端點：RSS 走 `feeds.finance.yahoo.com`（美股導向，台股中小型股空手），個股頁走 `tw.stock.yahoo.com`（台股在地內容）——不是換掉 Yahoo，是補上 Yahoo 沒供應的那一塊。Finnhub 依使用者指示不採用。

**實作內容**：`src/update.py:807-863` 新增 `fetch_tw_stock_news(company, limit=10)`：regex + `dict.fromkeys` 保序去重、逐篇 `source_exists` 跳過、`bare_extraction`（`len(text)<100` 跳過）、`ingest_text(..., market="tw")` 明確傳市場（依 `init.sql`「市場由寫入端決定」原則，不靠 company 推），例外只攔 `(requests.RequestException, OSError, ValueError)`，DB／embedding 失敗往上拋。`src/update.py:743-805` 的 `fetch_news` 順帶補上缺少的 `source_exists(link)` + `skipped` 計數（`fetch_market_news` 早就有，`fetch_news` 一直沒有）——實測跨 NVDA／MSFT／2330 的 Yahoo top-10，30 篇中 7 篇（23%）已在庫，每次補抓都重跑一次 trafilatura 下載與 embedding。接線方式為在 `fetch_news` 的台股分支內 fallback（RSS 回 0 篇且為台股代號才走個股頁），不在 `graph.py` 的 `calls` 加一筆——`calls` 有明文順序契約（`graph.py:705-707` 的 `calls[-1:]` 靠「新聞排最後」），多加會踩到它，且補抓耗時 69% 花在 embedding，無條件多打一個來源等於多一段延遲。

**額外修掉一個計畫未預期的缺陷**：Yahoo 個股頁部分連結經中文標題 URL 編碼後超過 `doc_chunks.source` 的 `varchar(512)`（實測虹光一篇公告連結 544 字元），會讓整批插入失敗並中斷抓取。選擇跳過該篇而非截斷 URL——截斷會讓不同長連結共用前綴、騙過 `source_exists` 去重。

**驗證結果**：全庫零新聞標的歸零：

```
 company | news_chunks
---------+-------------
(0 rows)
```

三檔台股缺口補齊：

| 標的 | market | chunks | articles | date_null | max |
|---|---|---|---|---|---|
| 2380 | tw | 85 | 9 | 0 | 2026-09-07 |
| 3025 | tw | 95 | 10 | 0 | 2026-09-04 |
| 3049 | tw | 105 | 10 | 0 | 2026-09-10 |

TSM 走既有 RSS 路徑補回 16 塊／2 篇，`created_at` 從停滯的 2026-09-09 更新至 2026-09-21，證明 TSM 從不缺來源、缺的是觸發。

端到端驗證（真模型、真 MCP tools，僅在 state 重現「TSM 檢索不到新聞」）：

```
log fields = [{"node": "agent", "stale": [], "missing": ["TSM"]}]
tool_calls  = [{"name": "fetch_company_data", "args": {"ticker": "TSM"}}]
```

確認 `missing` 進了 log，且模型據此對 TSM 發出補抓呼叫。

**回歸**：`test_fetch.py`（新增 missing directive 迴歸）、`test_market_links.py`（假 HTML 測 regex，不碰網路）、`test_market_column.py`（新增 `fetch_tw_stock_news` 寫入 `market='tw'` 斷言）、`test_ingest.py` 四檔全過。

**待辦條目改寫**：待辦第 5 項剩餘範圍改為熱門標的定時抓取＋retry＋隨機延遲（屬排程議題，現行補抓是查詢驅動、尚無定時器）。(a)、(c) 因實測已成立而移除；(b) 本輪完成；(d) 跨來源去重評估後判斷不採用，移入「已評估不採用」，詳見該區塊。

### 九、按來源重跑 ingest 的能力盤點（規劃，尚未實作）

承第二節的來源盤點查詢，本節評估的是下一步：查得出缺口之後，要怎麼讓某個來源重新抓取並入庫。這個能力原本被當成「已評估不採用」`CHUNK_SIZE` 單位一項的專屬前置成本，重估後確認它是**三個場景共用的基礎建設**：(1) chunk 參數改變——若 `CHUNK_SIZE` 的觸發條件成立，屆時需要這個能力才能重切生效；(2) embedding 模型換代——`db/init.sql` 的向量維度綁死 bge-m3 1024 維，換模型必須全庫重來、無法漸進；(3) 來源內容更新（財報改版、抓錯檔重抓）——這個與 chunk 單位無關，現在就會遇到，META 那筆（見第一節）就是人工查出來的。

**現況實測數字**（本次人工查庫所得，早於第二節 `list_sources()` 工具上線，統計口徑只含財報與新聞）：`doc_chunks` 依來源前綴分佈為 `EDGAR:` 16 源 6,718 塊、`https...`（新聞原文連結）525 源 2,690 塊、`data/*.pdf`（本地檔路徑）9 源 1,445 塊、`SEC-XBRL:` 12 源 12 塊、`TWSE-API:` 6 源 9 塊。財報合計 43 個來源（16+9+12+6）、**7,444** 塊。另有 427 塊 `company IS NULL`（全域市場新聞）。

**關鍵發現：這不是單一機制，而是四種重跑路徑**——`source` 欄位的格式本身就有四種，重跑方式各不相同：

- `EDGAR:<TICKER>:<accession>` → 可從 source 字串還原，呼叫 `fetch_edgar(ticker, form)`
- `SEC-XBRL:<TICKER>:<accession>` → 同上，呼叫 `fetch_sec_financials(ticker)`
- `TWSE-API:<co_id>:<label>` → 呼叫 `fetch_tw_financials(co_id)`
- `https://...`（新聞）→ source 就是原文連結，但新聞不需要重跑（90 天內佔 98%、自然汰換）
- `data/*.pdf` → **這一類最麻煩：source 是本地檔路徑，無法重新抓取，只能在檔案還在時重讀**。實查 9 個 PDF 檔案全部還在 container 內，故目前可重跑；但這是靠運氣，不是靠設計——檔案一旦被清掉就永久無法重建該來源。

另一個關鍵：`ingest_text`（`src/ingest.py`）收的是**已經抽好的文字**，不是來源位址，`source` 對它而言只是一個標籤。所以重跑能力不能只包 `ingest`，必須是「查出 source → 依前綴分派到對應的 fetch 函式 → 重新抽文字 → 走 ingest_text」這一整條，落點應在 `src/update.py` 而非 `src/ingest.py`。

**具體項目**：

1. **來源盤點查詢**——已於第二節完成（`list_sources()` + `inventory` 子命令）。
2. **依前綴分派的重跑函式**——落在 `src/update.py`，把上述四種前綴對應到既有 fetch 函式。既有的 `delete_by_source(source)` 已在 `ingest_text` 內做掉去重，重跑同一來源不會累積重複資料，這層不必重做。
3. **本地 PDF 來源的處理決策**——檔案不在時要明確失敗並記 log，不可靜默跳過（否則會重演 META 那種「以為有、其實沒有」）。同時應考慮是否把原始檔落地保存，讓 `data/*.pdf` 這類來源不再依賴檔案碰巧還在。
4. **批次重跑與失敗隔離**——一次重跑 43 個財報來源，單一來源失敗不能中斷整批，要逐來源記結果。理由直接來自 META：該次是 embedding 資源型失敗，整軌沒入庫卻沒有中斷別的來源，結果拖到人工查才發現。
5. **重跑前後的塊數對照報表**——重跑本身就是驗證點，前後塊數與 `chunk_unit`／`chunk_size`／`embed_model` 三欄的分佈要能直接看出哪些是新切法。
6. **`EMBED_BATCH_SIZE` 的重驗**——這是 chunk 參數改動的連帶成本：`EMBED_BATCH_SIZE=400` 是依現行 char/800 的塊數實測出來的值，塊變大則總塊數下降，同一個 400 不能直接沿用；600 批次已實測會抖，依專案慣例須實測、不接受推導。

**CP 值判斷**：三個場景中**只有第 3 個（來源內容更新）是現在就有的需求**，前兩個都要等選值或換模型才觸發。盤點查詢已完成（第二節），剩下的最小可用部分是 EDGAR／SEC-XBRL／TWSE-API 三種可重抓前綴的分派重跑，本地 PDF 與批次報表可後補。不建議一次做完整套。

### 十、`CHUNK_SIZE` 候選值重測：證明不了優劣，選值前置仍是 golden set

承 2026-09-20 章節第二節的切法量測，本次重跑同一支 `tests/bench_chunk_tokens.py`（樣本 400），針對候選值（384／600／900 配 overlap 50／75／100）各臂實測中英文 token 分佈：384/50 臂中文中位 270、英文 303；600/75 臂中文 406、英文 474；900/100 臂中文 687、英文 770。

**這組量測能證明「換 token 計數有效」，卻證明不了「384 比 900 好」**：三臂的中英文分佈都已對齊（換算後中英差距縮小到可接受範圍），量的是分佈，不是檢索品質，三臂在這個指標上都達標。依專案「效能參數須有實測數據、不接受推導」的慣例，現在就算願付重灌成本也選不出值——要選值需要的是檢索品質數字（Recall、citation 正確率），即待辦「chunk 策略功能擴充」的 golden set 前置。

**換算比本身也隨語料漂移，這是本次重測最該留下的發現**：2026-09-20 實測中文 1.60、英文 3.84 字元／token（相差 2.4 倍）；本次（09-21）同一支腳本重測為中文 1.77、英文 4.14（相差 2.3 倍）。語料持續增長使比例移動，代表任何寫死的換算值都需要複測，不能沿用歷史數字推導。

**零截斷風險，現行參數沒有壞**：實查 `doc_chunks`，財報 8,185 塊、新聞 2,680 塊，沒有任何一塊超過 1000 字元（max 800），最壞情況是中文 687 token，對 bge-m3 的 8192 context window 差約 12 倍。「中英文不對齊」在語料以英文為主（財報 7,247 塊英文對 938 塊中文）的現況下也不是主要病灶。

**結論：待辦「`CHUNK_SIZE` 單位不一致」自此撤下，機制已備、選值依據未建立**，移入「已評估不採用」，觸發條件為 golden set 到位而能量出檢索品質差異、或正式環境出現實際截斷或檢索品質問題的實例。重跑成本的論證見第九節；`EMBED_BATCH_SIZE` 需重驗這件事見第九節具體項目第 6 項。

**golden set 的規格（chunk 擴充與數字直答共用）**：50-100 題，涵蓋單一數值、年增率計算、跨年度比較、表格問答、註腳問答、管理層歸因、風險因素、同詞多章節歧義八類，量 Recall@5／@10、context precision、citation 正確率、表格數值正確率、token 成本與延遲。可沿用 `tests/eval_data/*_annotations.json` 加 checker 腳本的既有標注集模式，不必另建框架。chunk 擴充分兩支：parent-child 卡在 `pypdf.extract_text()` 拿不到標題層級，等於要換 parser 並改 `doc_chunks` schema；表格獨立處理的收益只落在約 11% 的中文語料（938／8,185 塊），其餘英文財報的數字已由 XBRL 那一軌解掉。數字直答通道的價值只剩「消除檢索誤差」，因為 `retrieve_context` 中位 0.5s、佔總耗時 0.0%（第六節），繞過檢索省不到延遲；出處標註可沿用現有 `[來源N]` 機制（第七節），真正缺的是數字題答錯率，同樣要靠 golden set 才量得出來。

### 十一、本輪一併評估、判斷不採用的四項

以下四項與今天的主線工作無直接關聯，是處理第二／八節時一併盤點到的待辦或構想，評估後判斷不採用，移入「已評估不採用」：

**跨來源標題相似度去重（`src/update.py` 的 `fetch_news`）**：待辦原文「新聞來源」項的第 4 步（標題相似度 + 發布時間 ±2 小時去重），本輪新增台股個股頁來源（第八節）時一併評估，判斷不做。新來源與 Yahoo RSS 的覆蓋面互斥：Yahoo 有的台股大型股個股頁是補充，Yahoo 空手的中小型股那側根本沒東西可重複，跨來源重複率預期極低；相似度門檻是需實測才能定的參數，依專案慣例不接受推導值，現在庫內沒有重複樣本可量。`delete_by_source`（URL 精確比對）+ `source_exists` 已覆蓋同來源重複。觸發條件：庫內出現實際的跨來源重複樣本，或新增第三個台股新聞來源時，屆時拿真實重複率定門檻。

**新聞定時排程（`src/update.py` 的 `fetch_news`、`src/mcp_server.py` 的 `fetch_company_data`）**：原「新聞來源」待辦的最後一步是熱門標的每 1-2 小時定時抓一次並加上 retry 與隨機延遲，評估後判斷不做，維持現行的查詢驅動（`fetch_company_data` 只在 LLM 於對話中呼叫時才觸發補抓）。不採用的理由來自本專案的實際使用形態：(1) 專案不長時間啟用——本機起來用一段時間就關，排程在關機期間不會執行，開機後還要面對積壓的時間窗，定時的「定時」在這種使用形態下並不成立；(2) 與前台查詢搶資源——補抓耗時 69% 花在 embedding（2026-09-19 實測 n=5，詳見該日章節第三節），背景排程會與使用者當下的查詢爭同一個本機 Ollama，而單題延遲已在 186-470 秒的量級；(3) 查詢驅動更貼合需求——要用時才抓，抓的一定是當下要看的標的；定時抓取則會為沒人要看的標的付出 embedding 成本。retry 與失敗隔離這層機制應與第九節「批次重跑與失敗隔離」共用，日後若任一方要做，做成共用、不要寫兩份。市場標籤約束（新增任何新聞來源都需同時決定市場標籤，否則寫入的塊 `market` 為 NULL 而被市場過濾排除）適用於新增任何新聞來源，不隨本項一起作廢，現行以 `MARKET_SOURCES` 的 key `_tw`／`_us` 尾碼標明。觸發條件：使用形態改變才重新評估——例如專案改為常駐服務或部署到正式環境持續運行，屆時「資料隨時新鮮」才成為真需求。

**補抓軌別拆成獨立 MCP tool（`src/mcp_server.py` 的 `fetch_company_data`、`src/graph.py` 的 `fetch_missing_data`）**：構想是把 `fetch_company_data` 內部的數條補抓軌（台股 `fetch_tw_financials`／`fetch_mops`，美股 `fetch_sec_financials`／`fetch_edgar`，兩邊都有 `fetch_news`）各自暴露成獨立 MCP tool，讓 LLM 自行決定只補財報或只補新聞、其餘直接查 RAG。先釐清一件事：拆分本身早就完成了——`src/graph.py` 的 `calls` 已經是各自獨立、各自成敗的多條軌（一軌掛掉仍有另一軌），2026-09-07 的 MCP 改造也已把「查 RAG」與「補抓」分成 `search_knowledge_base` 與 `fetch_company_data` 兩個 tool、由 LLM 自行判斷先查再補。真正要評估的不是「拆開」，而只是「要不要把每一軌都暴露給 LLM 選」這一層。三個不採用的理由：(1) 省不到主成本——補抓耗時 69% 花在 embedding，少點一軌省下的是 HTTP 那一小段，不是瓶頸；(2) 程式已在做更準的裁剪——`has_report` 判斷會把 `calls` 收斂成 `calls[-1:]`（已有財報就只補新聞），這是依庫內實際狀態決定的，比讓 LLM 猜準，而且不花 token；(3) 可能反而更慢——tool 輪數上限 4 是 2026-09-19 A/B 定案的，把一個 tool 拆成兩個，LLM 可能要兩輪才做完現在一輪的事。觸發條件：log 量到不必要軌別的浪費佔比，`source` 欄位已於第四節落檔，這個數字現在查得出來；在量到之前動工就是推導值，會重蹈 `CHUNK_SIZE` 那一項的覆轍。

**雙掛牌對照表改為 API 查詢＋落地快取（`src/tickers.py` 的 `TW_US_DUAL_LISTED`）**：原待辦寫「四檔手動維護」，卡在資料來源——既有 yfinance 與兩個官方 OpenAPI 都沒有 ADR 對應欄位，須先找到可靠端點才值得動工。撤下的關鍵理由：即使找到端點也不該做，不是卡在端點。實查 `src/tickers.py`，現況不是「四檔」而是兩張表共 11 檔：`TW_US_DUAL_LISTED` 5 檔（2330/TSM、2303/UMC、2412/CHT、3711/ASX、8150/IMOS）、`TW_US_OTC_ONLY` 6 檔（2881、2882、2317、2891、2886、2409）。兩表刻意分開：OTC 的 Level 1／非贊助 ADR 不向 SEC 申報，美股那側查不到財報，放進主表會讓反問後選美股拿到空手；富智康（港股 2038 ↔ FXCNY）則因鍵位一律當台股代號用會被誤判去查證交所 API 而刻意排除。這不是一張可被 API 直接取代的對照表，而是一張帶業務判定的表——ADR 端點能回答「有沒有 ADR」，答不出「美股那側查不查得到財報」，該判定仍須人工，API 化只解掉一半。改動面也不只 `src/tickers.py`：`src/graph.py` 有兩處直接以 `TW_US_DUAL_LISTED[tw]` 下標取值，改為 API＋落地快取等於把零延遲、零失敗的同步 dict 換成會失敗、會延遲的查詢，反問路徑須另外處理查不到的情況。觸發條件本身也不易到達：台股 ADR 主板掛牌數量本就極少，新增等同有新公司赴 NYSE/NASDAQ 掛牌，數年一次，而處理成本是往 dict 加一行——成本收益倒掛。觸發條件：若日後主表需維護的檔數成長到人工維護明顯吃力的規模，或找到同時能回答「有無 ADR」與「美股側是否申報 SEC」的端點，再重新評估。

### 十二、`[即時市場數據]` 觀測計數的誤報修復

2026-09-19 已把「模型在決策卡裡自創 `[即時市場數據]` 這個引用標記」這項既有行為降級為「可被觀測」——`check_answer_format()` 的 `unknown_citation_marker` 規則會記 log，但不擋輸出。本次（09-21）實測已累積 17 筆命中：09-19（0）／09-20（8）／09-21（9）。

**分析命中內容後發現 13 筆屬誤報**——命中的是 `已知事實`、`推論` 這兩個欄名本身。`trend_field_inference` 明文要求「明確標示為推論」，模型照做在內文寫出 `【推論】` 行內標籤，驗證層卻把 prompt 自己要求的輸出記成違規。

**根因已修**：`src/graph.py` 的 `unknown_citation_marker` 掃描加上 `and m.group(1).strip() not in expected_names`，把預期欄名整組排除在掃描之外；`[即時市場數據]` 那 7 筆仍會抓到，已有測試雙向釘住。這正好回答了 2026-09-19 章節第八節留下的未決問題（「`unknown_citation_marker` 可能誤報內文正常使用的中括號，需等 log 累積後看誤報率」）——**誤報率為 13/17**，修復後計數才乾淨。

**本項狀態不變**：`[即時市場數據]` 仍是既有行為、7 筆、低優先、繼續觀測中；這次修的是「計數被假警報污染」，不是關閉這個觀測項，詳見「已知限制」。

### 改動內容

| 項目 | 改動說明 | commit |
|---|---|---|
| META EDGAR 全文重新入庫 | 執行 `python -m src.update report --market us --company META --form 10-Q`，EDGAR 全文由 0 塊補齊至 740 塊 | — |
| `list_sources()` 來源盤點查詢 | `src/vectorstore.py` 新增，依 source 聚合並回報切法出處三欄 | `b378e3c` |
| `inventory()` 與 `inventory` 子命令 | `src/update.py` 新增，唯讀，可用 `--doc-type`／`--company` 篩選 | `b378e3c` |
| `inventory` 軌別缺口判定的 self-check（新增） | `tests/test_inventory.py`，餵造假形狀而非連實庫，確保能重現偵測到 META 修復前的缺口 | `b378e3c` |
| 軌別判定擴及台股、美股單軌改白名單 | `src/update.py` 的 `_TRACKS`／`_NO_NUM_TRACK`／`_track_of`／`inventory` | `b378e3c` |
| self-check 擴至 8 組（台股與白名單案例） | `tests/test_inventory.py` | `b378e3c` |
| 2380 財報數字補跑 | 執行 `fetch_tw_financials('2380')`，補上缺漏的 `TWSE-API` 數字軌 | — |
| 2380 缺口成因查證、6514 的 auto_fetch 標註問題查證 | `data/logs/` 比對；成因在 `src/graph.py` 的 `fetch_missing_data` | — |
| image 重建並換容器、`inventory`／`test_ingest`／`eval_rag_retrieval` 驗證 | `docker compose build app` 後 `up -d app`，確認四個 `docker cp` 送入的檔案已被新 image 覆蓋 | — |
| `fetch_missing_data` 的 company 與 source 標籤修正 | `src/graph.py`：`calls` 改成 `(company, source, fn)` 三元組，市場新聞帶 `company=None`，每筆新增 `source=` | — |
| auto_fetch log 標籤的 self-check（新增） | `tests/test_fetch.py`：攔 `graph.log_duration` 收欄位，驗正常與例外路徑的 company／source；已做變異驗證 | — |
| `rewrite_question` 的 qid 改用改寫後問句 | `src/graph.py` | — |
| `market` 反問偵測與 prompt 條件附加 | `src/graph.py` 的 `rewrite_question`／`_last_turn_is_market_reask`，重用既有 `_last_dual_listed` | — |
| `doc_chunks` 新增 `market` 欄位與索引 | `db/init.sql`（CREATE 與 ALTER 兩路徑） | — |
| 寫入端市場歸屬判斷 | `src/ingest.py` 的 `ingest_text`（新增 `market` 參數，不傳則由 company 推定）、`src/update.py` 的 `_market_of_source` | — |
| `insert_chunks` 寫入 `market` 欄位 | `src/vectorstore.py` | — |
| 既有塊回填 market（10,442 塊代號回填＋258 塊新聞標題回填） | 一次性 UPDATE，非程式改動 | — |
| 檢索層依 market 過濾 | `src/vectorstore.py` 的 `similarity_search`、`src/graph.py` 的 `retrieve_context`（`both`→`None`）、`src/mcp_server.py` 的 `_seed_prompt`／`search_knowledge_base` | — |
| 多輪市場一致性題組（新增） | `tests/eval_multiturn_market.py`、`tests/eval_data/multiturn_annotations.json`，9 題 5 類 | — |
| market 相關 self-check（新增） | `tests/test_market_reask_detect.py`、`tests/test_market_column.py`、`tests/test_market_filter.py` | — |
| AI 執行時間重數（純分析，無程式改動） | `data/logs/app*.log` 全檔逐檔 `jq` 過濾後彙總，`select(.message=="generate")` 過濾條件不變 | — |
| 待辦 3（原待辦 5）前置問題查證（純分析，無程式改動） | 讀 `src/graph.py`／`src/update.py`／`src/ingest.py` 確認出處標註機制已自動成立，改寫該項敘述 | — |
| `missing` 標的丟失修復 | `src/graph.py:820-829` 的 `agent` 節點改為 `stale, missing = _stale_companies(state)`，兩者措辭分開、log fields 加 `missing` | — |
| 台股個股頁新聞來源 | `src/update.py:807-863` 新增 `fetch_tw_stock_news(company, limit=10)`，`ingest_text(..., market="tw")` 明確傳市場 | — |
| `fetch_news` 補去重計數 | `src/update.py:743-805` 補上 `source_exists(link)` + `skipped` 計數 | — |
| TSM／2380／3025／3049 新聞缺口補跑 | 執行補抓，驗證結果見上節 | — |
| 待辦 5（新聞來源）相關 self-check（新增／擴充） | `tests/test_fetch.py`（missing directive 迴歸）、`tests/test_market_links.py`（regex 測試）、`tests/test_market_column.py`（`fetch_tw_stock_news` 市場欄位斷言） | — |
| MCP tool stub 補上 market 參數 | `tests/test_mcp_tools.py` | — |
| `unknown_citation_marker` 排除預期欄名 | `src/graph.py`：掃描條件加 `and m.group(1).strip() not in expected_names` | `214d137` |

---

## 2026-09-23　Ruff 靜態檢查導入、MCP 無驗證啟動收斂、CLI logging 缺口修復、補資料迴圈與新聞失敗回報修復、測試套件遷移至 pytest

四條各自獨立的工作，同一天做完。核心是**導入 Ruff 靜態檢查**，同時處理該過程暴露出來的既有問題——MCP server 的無驗證啟動風險與 CLI 路徑上完全失效的 logging；接著修復兩個獨立發現的 agent 迴圈與新聞抓取失敗回報的既有 bug；最後把整個測試套件從手寫 assert script 遷移到 pytest，過程中連帶抓出兩處測試會打到真實外部服務的問題。

### 一、Ruff 唯讀檢查與規則集校準

專案先前無 Ruff 設定。用 `uvx ruff@latest check`（未安裝進專案）跑預設規則，得 3,711 筆告警。**規則集選擇本身才是主要工作**，而非逐一修復告警。

前三名皆為 RUF003、RUF002、RUF001（ambiguous-unicode-character），3,711 筆中佔多數。這三條是在抗議中文全角標點（，。「」），而本專案註解與字串大量使用中文。排除後重跑，前三名改為 S101（assert 591 筆，幾乎全在 tests/，pytest 用 assert 是正確寫法）、E501（line-too-long 428 筆，專案原無行寬慣例）、T201（print 146 筆，其中 127 筆在 tests/ 與 bench_/eval_ 腳本）。

新增 `pyproject.toml`，設定 select 與 ignore，仍是「套件安裝走 requirements.txt、設定只管 lint」的慣例。配置為：select `["E","F","W","B","SIM","UP","C4","T20","G","S"]`，line-length 100，ignore RUF001/002/003（中文標點）、DTZ（另立一項）、E501（理由見下）、per-file-ignores 中 tests/ 忽略 S101/T20/E402，src/ 的 CLI 進入點與 i18n.py 忽略 T20（因為這些模組的 print 屬終端呈現或自我檢查，而非日誌）。**E501 改為 ignore 的理由**：115 筆中多數是 src/i18n.py 的翻譯字串（55 筆）與中文說明註解，折行反而降低可讀性。line-length 參數仍保留供日後 ruff format 參考。結果從 3,711 筆降至 48 筆，剩餘皆為測試檔既有風格項。

isort（I）刻意未納入 select：既有風格是一行塞多個名稱靠 line-length 折行。合併後超過 100 字元時，`--fix` 會改寫成一個名稱一行，製造與功能無關的大 diff。排序目前已正確，本次手動修正真正的排序錯誤（src/graph.py 的 `from langgraph.graph import StateGraph, END` → `END, StateGraph`、src/config.py 的 import 分組空行），設定內註明需要時手動跑 `uvx ruff check --select I --fix src`。

### 二、DTZ 與時區約定：11 筆判定為不可修改

初判認為 `date.today()` 在不同時區容器會給出不同交易日，屬真風險。讀過程式碼與部署後推翻：docker-compose.yml 三個 service（第 10/35/71 行）全部設了 `TZ: ${TZ:-Asia/Taipei}`，時區是部署層固定的。src/logging_setup.py 第 33 行的註解明確寫下約定：「用本地時間（容器已設 TZ=Asia/Taipei），與專案其他『今天』的判斷一致」。

各處用法與其理由：src/graph.py:754 餵給模型的「今天日期」要的就是台北的今天；src/graph.py:916、src/mcp_server.py:99/191 算新聞距今天數，同一基準相減；src/vectorstore.py:78 docstring 明說要對齊 Chainlit 寫入的 naive 本地時間字串格式，改成 aware 會直接寫壞字典序比較（該處刻意用字典序比大小以吃到索引）；src/app.py:322 PDF 報表的產生時間戳。改成 UTC 會讓「今天」在台北時間早上 8 點前退回前一天。結論是整組在設定檔 ignore 並註明理由，而非逐處修改——這是引入 bug 而非修 bug。

### 三、.env 與 git 歷史的金鑰洩漏查證

檢查範圍：.env 使用方式、git 歷史（146 個 commit）是否曾洩漏金鑰。

**結果：未發現洩漏**。`git log --all -- .env` 回 0 commits，.env 從未被追蹤；`git log --all --diff-filter=A --name-only` 顯示歷史上被加入的 env 類檔案只有 .env.example；`git show f501103:.gitignore`（初始 commit）已含 .env。最關鍵的是 **.gitignore 在初始 commit 就已包含 .env**，避免了最常見的洩漏模式（「先 commit 了 .env、後來補 .gitignore」）。Pickaxe 逐一搜索金鑰前綴 sk-ant-／sk-proj-／AIza／pplx-／tvly-／OPENAI_API_KEY=／ANTHROPIC_API_KEY=／GOOGLE_API_KEY=，全部 0 筆。

.env 使用方式評價：load_dotenv() 只在 src/config.py 呼叫一次，全專案唯一的其他 os.getenv 是 src/app.py:60 的 OAuth 開關判斷。config.py 對 Langfuse 的處理是正確做法——`LANGFUSE_ENABLED = bool(os.getenv("LANGFUSE_PUBLIC_KEY"))` 只判斷存在性，金鑰值由 SDK 自己讀環境變數，不進 Python 變數。

**已知限制**：git log 只看得到 commit 進本 repo 的內容。若金鑰曾貼進 issue、PR 描述、CI log 或聊天，此法查不到。以本專案（本機 + Docker、無 GitHub Actions）而言風險低，但這是「未發現洩漏」而非「已證明無洩漏」。

### 四、MCP server 無驗證啟動改為容器內 fail-closed

**問題**：src/mcp_server.py 的 `__main__` 原本在 `MCP_AUTH_TOKEN` 未設定時只印 warning 就繼續 `uvicorn.run(host="0.0.0.0", port=8000)`。「無 token 也開得起來 + 綁全介面」的組合意味著只要容器 port 被 expose 到非本機環境、.env 忘了帶 token，就是一個無驗證的公開 tool 端點。

採寬鬆版而非嚴格版，這是刻意的取捨：目前沒有第三方外接 MCP client，嚴格版（一律要求 token、另設開關才能降級）的預設擋不到真實風險，卻讓本機開發多一道手續。故只在容器內缺 token 時擋——那才是 port 可能被 expose 出去的情境；容器外維持現行 warning 放行。判斷沿用 src/logging_setup.py 的 `_log_name()` 既有的 `Path("/.dockerenv").exists()`，不引入新的設定 key。`host="0.0.0.0"` 不動（容器內要讓其他 service 連得到），加 `# noqa: S104` 並註明理由——無驗證的情況已在上面擋掉。日後要收緊只需把 `elif Path("/.dockerenv").exists():` 改成 `else:`，程式碼內已註明。

**驗證結果（rebuild image 後實跑）**：容器內有 token 時正常啟動、驗證啟用、healthy；容器內無 token 時拒絕啟動、exit code 1、印出清晰訊息「MCP_AUTH_TOKEN 未設定，容器內拒絕無驗證啟動。請在 .env 設定後重啟。」；本機直接跑無 token 時啟動成功加 warning（行為照舊）。

### 五、CLI 進入點的 logging 缺口修復

這是本次最有價值的發現，屬於既有問題而非本次引入。

**起點**：原計畫只把 src/update.py:282 的 `print` 改成 log.info（該行是 AI 路徑上一次外部下載的起點，沒有對應的 log）。改完後實跑 `python -m src.update report --market us --company AAPL`，終端有看到 INFO 輸出，但 **data/logs/ 當天完全沒有對應檔案**。

**根因**：`setup_logging()` 只在 src/app.py 與 src/mcp_server.py 的 `__main__` 被呼叫。src/update.py 的 `main()` 從未呼叫過，root logger 的 handlers 是空的（實測 `logging.getLogger().handlers` 回 `[]`）。該模組以及它呼叫的 ingest 的所有 `log.*` 全部只落到 stderr，從未進過 JSON Lines 檔案。

**危險性**：這個缺口在終端看不出來，stderr 照樣印得出訊息，只有去翻 data/logs/ 才會發現當天沒有生成對應檔案。它讓 2026-09-13 章節建立的可觀測性目標在 CLI 路徑上實際失效，而抓取正是最需要回測耗時的一段。若未發現此缺口，原計畫的改動會讓情況變糟——print 改成 log 之後，該筆紀錄會從終端消失、檔案裡也沒有。

**修復**：src/update.py 的 `main()` 開頭加 `setup_logging("update")`（並補 import）。一行，落在 CLI 進入點而非各個函式，所有呼叫端一次覆蓋。

**驗證（再次 rebuild 後）**：data/logs/update.log 生成，新紀錄落地，包括下游 ingest 的耗時紀錄與 embedding 批次進度。**順帶救回 ingest 的耗時紀錄**：同一份 update.log 內另有多筆 ingest 紀錄（「開始 embedding」「embedding 批次完成」「已寫入 pgvector」），這些在 CLI 路徑上同樣是一直丟失的，一併恢復。

### 六、update.py 其餘 16 筆 print 刻意保留

初判認為 src/update.py 的 17 筆 print 全部違反 logging 規則。逐一對應到所屬函式後推翻。inventory() 印的是對齊過的終端報表（來源前綴表格、軌別交叉表、缺口警示、合計列），塞進 JSON Lines 反而讀不了，與 tests/ 的 bench/eval 腳本同性質。fetch_mops() 的 5 筆屬於同一個形狀：每個失敗點前面都已經有對應的 `log.warning(..., extra={"fields": {..., "reason": "mops_blocked"}})`，print 出去的是 MOPS_MANUAL_GUIDE（多行手動下載步驟指引，給人看的操作說明，不是日誌）。結構化紀錄已經落地，回測拿得到 reason，沒有缺口。

結論是「AI 執行路徑上的紀錄一律走 logging」與「給人看的終端輸出用 print」兩者並存，per-file-ignores 的 T20 設定即是把這個判斷固化成規則而非口頭約定。驗證時已確認 inventory 的表格輸出未受影響。

### 七、.env / .env.example 補金鑰來源註記

在每個 secret 欄位補「去哪申請／如何產生」，這是最便宜的分發機制，也避免值被貼到聊天軟體。兩個檔案同步（使用者要求），**.env 只加註解、不動任何現有的值**，兩檔 key 集合維持一致。

補的內容：MCP_AUTH_TOKEN 註明容器內必填、留空會拒絕啟動，附產生指令 `python -c "import secrets; print(secrets.token_urlsafe(32))"`；LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 為 Langfuse UI > Settings > API Keys，註明 pk-lf- / sk-lf- 前綴；OAUTH_GOOGLE_CLIENT_ID / SECRET 補上「Application type 選 Web application」。

### 八、Ruff 安全告警逐項查證

四筆安全告警皆為誤報或已受控：

| 告警 | 位置 | 判定 |
|---|---|---|
| S608 hardcoded-sql-expression | src/vectorstore.py:191 | 誤報。f-string 只組 WHERE/ORDER BY 的固定片段，所有值都走 `%(name)s` 參數化 |
| S324 insecure-hash (sha1) | src/graph.py:115 | 誤報。用途是 log 關聯鍵（問題文字的短 hash），非密碼學用途 |
| S314 XML 解析 | src/update.py:761 | 低風險。解析的是 Yahoo RSS，非使用者輸入 |
| S104 bind-all-interfaces | src/mcp_server.py:243 | Docker 內必要，已加 noqa 並註明；真問題（fail-open）已於第四節修掉 |

### 九、補資料迴圈退化：首輪與剛補抓完就被判定「完全沒有新聞」

`ef58496`（09-22，見上節「一」的 `missing` 修復）本身引入了一個新的退化：`_news_ages_by_company`（`src/graph.py`）用 `{}` 同時代表「還沒查」與「查了但沒有」兩種狀態，`_stale_companies` 分不出兩者，於是在第一輪（`messages=[]`，尚未檢索）與剛執行完 `fetch_company_data` 的那一輪，把每家公司都判定為 `missing`，程式因而在 directive 裡指名這些公司「完全沒有檢索到新聞」，反過來叫模型去重抓剛抓完的資料，或是在還沒查庫前就搶先補抓——每次補抓耗時約 1-3 分鐘。

**修法**：`_news_ages_by_company` 現在回傳 `None` 代表「最後一次補抓之後沒有任何 `search_knowledge_base` 檢索」，`_stale_companies` 對 `None` 回 `([], [])`，交還 LLM 自行判斷，不再強制指名。

**self-check**：`tests/test_fetch.py` 新增 case A（`messages=[]` 不產生任何 directive，拿掉修復後會失敗，已驗證）與 case B（檢索結果只有 NVDA 的 chunk 時，會對 TSM 產生「完全沒有檢索到新聞」的 directive，確認判斷仍照舊生效）。

### 十、新聞來源全數失敗時的回報訊息與實際結果矛盾

`fetch_news`／`fetch_tw_stock_news`／`fetch_market_news`（`src/update.py`）在所有來源都抓取失敗時，`FetchResult.ok` 已正確回 `False`，但 `detail` 仍寫「…更新完成，共寫入 0 筆 chunk」。LLM 透過 `fetch_market_overview`／`fetch_company_data` 這兩個 MCP tool 只讀得到 `detail` 文字，看到「完成」就會誤判已經抓到新資料。

**修法在來源端**：`ok=False` 時 `detail` 改寫成「…抓取失敗：沒有取得任何文章（來源無回應、改版或內文抽取失敗）。」三個函式各自獨立套用同一改法，兩個 MCP tool 因此一併覆蓋，不需另外修工具層。**self-check**：`tests/test_news_fetch_failure.py`（模擬全部來源回 HTTP 500），拿掉修復後確認會失敗。**已知限制**：這個情境的 log 仍記在 `INFO` 層級，未升級。

### 十一、測試套件遷移至 pytest

`tests/*.py` 原本是手寫 `assert` 腳本、靠 `sys.path.insert` 補模組路徑，09-02 章節已列為技術債。本次一次遷移完成：新增 `requirements-dev.txt`（`requirements.txt` + pytest，不進 Docker image）；`pyproject.toml` 加 `[tool.pytest.ini_options]`（`testpaths=tests`、`pythonpath=.`），拿掉所有手寫的 path hack。33 個檔案改寫成 `def test_*` 函式，手動屬性替換與自製 log handler 改用 pytest 內建的 `monkeypatch`／`caplog`；未新增 `conftest.py`（沒有 fixture 被兩個以上檔案共用），也未引入 pytest-mock（`monkeypatch` 加標準庫 `unittest.mock` 已足夠）。`tests/test_market_filter.py` 在連不到 DB 時以 2 秒逾時探測自動 `skip`（原因「需要 Postgres」）；`tests/bench_*.py`／`tests/eval_*.py` 維持不被收集。31 個檔案改寫前後的 assert 數量相同，`test_chart_earnings_marker`（4→3）與 `test_retrieve_context`（36→34）的差異只來自「手寫 sentinel 判斷『應該要拋例外』」改寫成 `pytest.raises` 少了外層計數，不是少測。全套結果 **240 passed、4 skipped**，單檔獨立執行、整套一次執行、檔案順序反過來執行三種跑法結果一致。README 新增 Testing／測試段落。

遷移過程揪出兩處測試會打到真實外部服務：

- **`src/app.py` 在模組載入時就執行新聞／對話留存清理（`DELETE`）**：任何 `import src.app` 的測試（5 個檔案）都會連帶開啟 Postgres pool；沒有 DB 時，退出時留下背景重連錯誤；有 DB 時，跑測試會真的對資料庫執行留存清理、刪掉過期資料。修法是把清理移進 `@cl.on_app_startup def prune_expired()`（chainlit 2.11 的啟動 hook）。**驗證（rebuild image 後）**：app 啟動時 `pg_stat_activity` 可見兩條 `DELETE` 確實來自 app 容器；完整跑一次測試套件，pool 開啟次數為零。
- **`tests/test_tracing.py` 的「啟用」路徑用了真實 `.env` 的 Langfuse 金鑰**：會建立真實 client 並在測試結束時把 span 送出去，且在未設金鑰時整段判斷會被跳過、等於沒測到。改為強制啟用、用 `MagicMock` 換掉 client 與 `CallbackHandler`；同時補上 span 名稱等於節點名稱的斷言；並把一條原本沒有意義的斷言（檢查字串 `"s2"`，但從未傳入過）換成有效版本（`session_id=None` 時，metadata 裡不應出現 `langfuse_session_id` 欄位）。**結果**：套件輸出不再出現 Langfuse「Failed to export」或 Postgres 連線錯誤。

### 改動內容

| 項目 | 改動說明 | commit |
|---|---|---|
| pyproject.toml 新增 | Ruff 設定：select、ignore、line-length、per-file-ignores | `4635129` |
| import 排序修正 | src/graph.py:34、src/config.py:3 各一處，isort 未納入自動化 | `71738b3`／`3860946` |
| src/mcp_server.py fail-closed 修復 | 容器內缺 token 時拒絕啟動、exit code 1，本機 warning 放行；`Path("/.dockerenv").exists()` 判斷；`host="0.0.0.0"` 加 `# noqa: S104` 與註明理由；補 `from pathlib import Path` | `3860946` |
| src/update.py 補 setup_logging（CLI logging 缺口修復） | `main()` 開頭加 `setup_logging("update")`、補 import；第一行確保後續所有日誌落地 | `7db90a6` |
| src/update.py:282 print 改 log.info | 該行是 AI 路徑上一次外部下載的起點 | `7db90a6` |
| .env 與 .env.example 補金鑰來源註記 | MCP_AUTH_TOKEN 補產生指令與容器內必填說明；LANGFUSE 與 OAUTH 各補一行來源說明。兩檔同步，.env 只加註解不動既有值，key 集合維持一致 | `3860946` |
| `_news_ages_by_company` 分清「未查」與「查了沒有」 | `src/graph.py`：無檢索時回 `None` 而非 `{}`，`_stale_companies` 對 `None` 回 `([], [])`；`tests/test_fetch.py` 新增「首輪未檢索不指名」與「檢索結果只有他家時照舊指名」兩個 case | `71738b3` |
| 新聞來源全滅時的 detail 訊息修正 | `src/update.py` 的 `fetch_news`／`fetch_tw_stock_news`／`fetch_market_news`：`ok=False` 時 detail 改寫「抓取失敗」而非「更新完成」；新增 `tests/test_news_fetch_failure.py` | `7b8c88c` |
| app 啟動清理移出模組載入 | `src/app.py`：`delete_news_older_than`／`delete_threads_older_than` 移入 `@cl.on_app_startup def prune_expired()` | `c1fd0cd` |
| 測試套件遷移至 pytest | 新增 `requirements-dev.txt`、`pyproject.toml` 的 `[tool.pytest.ini_options]`；33 個測試檔改寫為 `def test_*`；`tests/test_tracing.py` 啟用路徑改用 `MagicMock`、補齊斷言 | `4635129` |
| 相關測試通過 | 全套 240 passed、4 skipped；另外 test_logging_setup、test_update、test_mcp_tools、test_fetch、test_ingest、test_inventory 六支涵蓋本節改動觸及的模組 | — |

---

## 2026-09-24　雙掛牌併陳行情漏抓 ADR、補抓變慢觀測點補齊

同一條調查線：先修好雙掛牌併陳時台美行情抓取不一致的漏洞，再補足補抓效能觀測點的缺口。兩部分分別針對「已知的確定性缺陷」與「有根據但缺數據的假設」。

### 一、雙掛牌併陳行情漏抓 ADR

問題案例：「台積電的 ADR 與台股表現有什麼差異」時，系統判定了 `market="both"`、檢索到了 TSM 新聞與 EDGAR 財報，卻只抓了 2330 的行情快照、TSM 的沒有。根因在於 `generate` 節點呼叫 `get_market_snapshots(companies)` 時只帶了台股代號清單，沒有把 `peer_company` 併進去。這個漏洞只在這一處出現；同檔案的 `cross_market_split`（跨市場判斷用）與 `_seed_prompt`（agent 首輪引導訊息）都已正確併入 peer。

**修法**：新增 `_side_by_side(state)` 函式，在 market="both" 且有 peer 時把 `peer_company` 併入代號清單，做為行情抓取、跨市場判斷、missing 清單三處的共用清單源。`cross_market_split` 改用它、`generate` 的行情抓取改用它、missing 計算也改用它。另外 `resolve_market` 原本不記判定結果，這次是從檢索來源反推才確認 market=both；改為每個分支回傳前統一記一筆 log（companies、market、peer_company、ask_market）。

### 二、補抓變慢觀測點補齊

前一階段對補抓延遲的根因分析得出三個發現，都基於「log 空白時間」與「檢索結果來源」這類間接證據，缺乏直接觀測。本次依專案「效能判斷需有實測數據」的慣例補足觀測點。四個新事件的落點分別在 PDF 解析、EDGAR 解析、MOPS 下載完成、pgvector 寫入；並補上「寫庫快慢取決於何種原因」的 A/B 實測步驟（先上線觀測點、再做對照組驗證）。

**新增觀測項目**：
- `resolve_market`：已於上節補上，app log 記錄。
- `PDF 解析完成`（mcp log）：pages、chars、elapsed_ms。
- `EDGAR 解析完成`（mcp log）：chars、elapsed_ms。
- `MOPS 下載完成`（mcp log）：bytes、elapsed_ms。原本只有 print 輸出。
- 「已寫入 pgvector」新增 `delete_ms`、`insert_ms` 欄位，區分刪除舊 chunk 與寫入新 chunk 各自的耗時。

**待 A/B 實測的假設**（先不動工，觀測數據上線後由使用者決策）：
- **發現 1**：併發補抓時寫庫變慢，疑似是 pypdf／trafilatura 解析佔住 GIL，導致同一個 process 的其他執行緒被卡住。
- **發現 2**：embedding 變慢，疑似是 Ollama 的 head-of-line 排隊現象。

修法候選項（待驗證後選擇）：發現 1 成立時用 `ProcessPoolExecutor` 把解析移出主 process；發現 2 成立時調整 `EMBED_BATCH_SIZE` 或 `OLLAMA_NUM_PARALLEL`。

### 改動內容

| 項目 | 改動說明 | commit |
|---|---|---|
| `_side_by_side` 新增 | `src/graph.py`：併陳代號清單的統一來源，market="both" 且有 peer 時併入 peer_company，供行情抓取、跨市場判斷、missing 清單共用 | `28a6337` |
| `cross_market_split` 改用 `_side_by_side` | `src/graph.py`：移除重複邏輯，統一調用新函式 | `28a6337` |
| `generate` 行情抓取改用 `_side_by_side` | `src/graph.py`：`get_market_snapshots` 參數由 `companies` 改為 `quote_codes`；missing 清單計算同步改用新清單 | `28a6337` |
| `resolve_market` 統一記錄判定結果 | `src/graph.py`：新增 `_log_resolve_market()` 內部函式，5 個 return 分支皆呼叫它；記錄 companies、market、peer_company、ask_market | `28a6337` |
| PDF 解析完成事件 | `src/ingest.py` `load_text()`：量 pypdf 解析耗時，記錄 `log_duration("PDF 解析完成", ..., source, pages, chars, elapsed_ms)` | `b245a6c` |
| EDGAR 解析完成事件 | `src/update.py` `_fetch_edgar()`：量 trafilatura.extract 加 fallback 的耗時，記錄 `log_duration("EDGAR 解析完成", ..., company, source="edgar", chars, elapsed_ms)` | `b245a6c` |
| MOPS 下載完成事件 | `src/update.py` `fetch_mops()`：print 改 `log.info`，記錄 company、source="mops"、bytes、elapsed_ms（自首次 POST 開始量） | `b245a6c` |
| pgvector 寫入事件細分 | `src/ingest.py` `ingest_text()`：分別量 `delete_by_source` 與 `insert_chunks` 耗時，併入「已寫入 pgvector」log 的 delete_ms、insert_ms 欄位 | `b245a6c` |
| 測試：`_side_by_side` | `tests/test_dual_market.py`：新增 `_side_by_side` 的測試（both 才併入 peer）。專案沒有可 stub LLM 呼叫 `generate()` 的測試寫法，行情實際送出兩檔需在 Chainlit 驗證 | `28a6337` |
| 測試：pgvector 寫入事件 | `tests/test_ingest.py`：驗證「已寫入 pgvector」記錄有 delete_ms、insert_ms 欄位 | `b245a6c` |

---

## 2026-10-07　雙掛牌比較補上系統計算的溢價與 EPS 換算、Ollama context 截斷查證、eps2 跨幣別直接比修正

同一條調查線：雙掛牌比較題（「台積電的 ADR 與台股表現有什麼差異」「EPS 差多少」）讓模型自己換算幣別與股數比，結果不是算錯就是拒答，改為程式先算好、模型只需引用。過程中用 A/B 驗證時發現答案常在固定字數斷句，查出根因是 Ollama 以 4096 context 載入模型、長 prompt 被靜默截斷，於是補上 token 用量觀測、讓 context 大小可調，並補跑 16384／32768 兩臂定下預設值。驗收時發現的兩個既有誤判，一個已修（bench 的 `cites_premium` 判定方式），另一個（eps2 跨幣別直接比較）查出根因並修正，收在第四節。

### 一、雙掛牌比較加上系統計算的 ADR 溢價

問「台積電 ADR 與台股表現有什麼差異」時，模型只拿到兩個不同幣別的報價，沒有換股比例與匯率可用，於是自己掰出與報價矛盾的說法。改為在程式內算好溢價：`ADR_RATIO`（每檔比例已對照 FY2025 20-F 核實）× `USD/TWD`（`TWD=X`，與既有行情快照並行抓取），兩邊報價都成功時才附上一段可直接引用的溢價區塊。

`ADR_PREMIUM=off|block` 供 A/B 切換（預設 `block`）。`tests/bench_adr_premium.py` 的 A/B 結果：有溢價區塊時 3/3 題都引用了溢價率，沒有區塊則 0/3；額外在 prompt 加一句「可以引用這個區塊」的例外句沒有造成差異，故捨棄不用。

### 二、ADR EPS 折合台股每股的換算

問 EPS 差多少時，模型不是拒答（「無法計算差額」）就是自己換算算錯——曾把比例乘反（×5 而非 ÷5），也曾把台幣報價誤當美元。改為在程式內算好：取兩邊 `earnings_dates` 最新一次 EPS，公布日相差 3 天內視為同一季，才在台股 EPS 旁附上 `ADR EPS ÷ ratio × USD/TWD` 的換算值。`format_adr_premium` 改回傳 `(text, metrics)`，順手拆掉原本給 log 用的重複計算。

`ADR_PREMIUM` 新增 `eps` 臂並改為預設值。針對三種問法（「EPS 差多少」「誰比較高」「換算成台股每股是多少」）的 A/B：`eps` 臂 3/3 引用了程式算好的換算值，`block` 臂（只有溢價區塊、沒有 EPS 換算）3/3 全答錯——兩次自行換算算錯、一次拒答。

### 三、Ollama context 截斷查證：記錄 token 用量、`OLLAMA_NUM_CTX` 可調

驗證第二節時發現部分回答固定在某個字數斷句，查出根因是 Ollama 用 4096 context 載入 `qwen3.5:9b`，超出的 prompt 被靜默截到約 2050 token（`num_ctx` 一半再扣幾碼 keep），模型看不到被截掉的那段輸入卻不會報錯。

`rewrite_question`／`agent`／`generate` 三個節點記錄 Ollama 回報的 `prompt_tokens`／`output_tokens`／`done_reason`／`prefill_ms`／`decode_ms`／`load_ms`（取自 `response_metadata`，缺欄位就不放進 log，不補假值），`prompt_tokens` 貼近截斷門檻時另記一筆 warning。新增 `OLLAMA_NUM_CTX` 並讓三個 `ChatOllama` 實例共用同一個值——Ollama 收到不同 `num_ctx` 會重新載入模型，節點間輪流呼叫若值不一致，等於每次切換都多付一次載入時間。

**num_ctx A/B 結果：預設值定為 32768。** `data/bench/numctx_ab.jsonl`（`adr`／`eps`／`eps2`／`invest` 四題 × 4096／16384／32768 三組）：

| `num_ctx` | 截斷 | 決策卡欄位 | `[來源N]` 引用 | SIZE | GPU |
|---|---|---|---|---|---|
| 4096 | 4/4 題皆截到 2050 token | 0～1 欄 | 0/4 | 5.5 GB | — |
| 16384 | 0/4 | 9 欄 | 4/4 | 5.9 GB | 100% |
| 32768 | 0/4 | 9 欄 | 4/4 | 6.6 GB | 100% |

16384 與 32768 兩組結果幾乎相同；選 32768 是因為歷史紀錄最長 prompt 達 22048 token，16384 裝不下，代價是多付約 0.7 GB 記憶體，兩組讀 prompt 的速度相同（約 80 tok/s）。

截斷規則已實測確認：原始 prompt 達到 `num_ctx` 才會截斷，截完固定剩 `num_ctx // 2 + 2` token（4096→2050、32768→16386）；未截斷的 prompt，`prompt_tokens` 可以落在 0 到 `num_ctx` 之間任何值。原本的門檻「`prompt_tokens >= num_ctx // 2 - 8`」在 16384 下會把沒截斷的 11338 token 誤報成截斷，改為「`prompt_tokens` 落在 `num_ctx // 2 + 2` 的 ±8 以內才判定截斷」。

**已知限制**：Ollama 回報的 `prompt_eval_count` 是「截斷後」的值，程式端看不到原始 prompt 真正有多長，這個門檻偵測到的其實是「`prompt_tokens` 貼著已知的截斷上限」而非「原始 prompt 遠大於 `num_ctx`」；若原始 prompt 剛好落在 limit ±8 以內、其實沒被截斷，仍會被誤報。

驗證：正式改用 32768 後，容器內 adr 題的 `prompt_tokens` 為 11338，未觸發截斷警告；該題讀 prompt 約 130 秒，總耗時 306 秒——11k token 的 prompt 光讀就要上百秒，是下一個待辦的量測對象（見上方待辦第 2 項）。

跑 A/B 時 bench 本身也補強：新增 `invest`（單一公司投資題，看決策卡欄位完整度）、`--q` 改為逗號分隔可跑多題、`--out` 可指定結果路徑，並新增 `cites_source` 檢查 `[來源N]` 格式引用。`_llms` 的 `lru_cache` key 不含 `num_ctx`，建 fixture 或切換 `num_ctx` 前後都要呼叫 `cache_clear()`，否則會沿用舊 `num_ctx` 建出的 `ChatOllama` 實例。

驗收不截斷的兩組時另發現兩個既有誤判：adr 題的 `cites_premium` 判定用 regex 只認「溢價」兩字，模型其實已寫成「高於台股現價 19.03%」這種帶數字的句子卻被判未引用；eps2 題模型並未使用程式算好的換算值，直接比較 27.25 元與 4.31 美元，得出「台股 EPS 較高」的錯誤結論（換算後約 27.4 元，其實是 ADR 較高）。前者已於本節修好（見下），後者查出根因並修正，見第四節。

### 四、bench 改依數值比對引用；eps2 跨幣別直接比較修正

**bench 判定方式修正**：`cites_premium`／`cites_eps` 改成從 bench 實際擷取的 ADR 換算區塊文字裡取出溢價率與換算後 EPS 的數值，再比對答案是否引用了同一個數值，不再用「溢價」「換算」這類固定字眼配 regex 找句子——固定字眼配不到模型自行改寫的說法，數值比對不受措辭影響。

**eps2 的根因是兩份跨市場指示互相衝突**：`dual_market_warning` 要求「不得換算成同一數字比較」，是為了擋模型自行亂換算；但雙掛牌且有 ADR 換算區塊時，程式已經算好換算值、區塊本身就是在告訴模型「這個數字你可以直接引用」，兩句指示同時出現在 prompt 裡，模型選擇遵守了前者、跳過换算區塊，直接拿台股 27.25 元與 ADR 4.31 美元比大小。

**修法**：有 ADR 換算區塊時，`generate` 改用新增的 `dual_market_warning_adr`（i18n）——要求引用區塊算好的台幣等值與差距百分比，禁止跨幣別直接比較原始數字；區塊沒有 EPS 等值那一行時（見下方重現實驗），只能把兩邊 EPS 分開陳述、不得判斷誰高誰低。沒有換算區塊、或開關關閉時，仍用舊版 `dual_market_warning`。新開關 `config.ADR_COMPARE_RULE`（預設 `on`），`off` 為舊行為，供 A/B 對照；新增 3 個測試覆蓋「有區塊＋on」「有區塊＋off」「無區塊」三種組合，全套 **276 passed、4 skipped**。

**重現實驗**：凍結行情（固定報價、固定匯率），在換算區塊有 EPS 等值行的情況下，匯率 31.70～31.95 共跑 6 次，舊規則（`dual_market_warning`）在這 6 次都正確引用了換算值——換算區塊本身已經夠清楚，匯率數值不是觸發誤判的原因。把 EPS 等值行拿掉後（模擬 `yfinance` 的 `earnings_dates` 抓取失敗，或台美兩邊公布日相差超過 3 天、系統判定不算同一季），舊規則立即重現本節一開始的誤判（答「台股 27.25 元 vs ADR 4.48 美元，台股較高」，兩次都把下一季共識預估的 4.48 美元當成了實際 EPS）；改用新規則後同一情境下改為分開陳述兩邊數字、不判斷高低。各情境只跑 1 次，樣本小，不是嚴謹 A/B，但足以定位觸發條件：**換算區塊缺 EPS 等值行**才會重現跨幣別直接比，保留 `ADR_COMPARE_RULE` 開關供日後正式 A/B。

### 改動內容

| 項目 | 改動說明 | commit |
|---|---|---|
| ADR 溢價計算與引用區塊 | `src/market.py`：新增溢價計算（`ADR_RATIO` × `USD/TWD`）；`src/graph.py`：並行抓取 ADR 匯率與行情快照，兩邊成功才附區塊；`src/tickers.py`：新增 `ADR_RATIO`；`src/config.py`：新增 `ADR_PREMIUM` 開關；`src/i18n.py`：溢價區塊文案；`tests/bench_adr_premium.py` 新增、`tests/test_dual_market.py`／`tests/test_market.py` 補測試 | `a91086e` |
| ADR EPS 換算值 | `src/market.py`：`format_adr_premium` 改回傳 `(text, metrics)`，新增 EPS 換算（同季判定 3 天內、`ADR EPS ÷ ratio × USD/TWD`）；`src/config.py`／`src/i18n.py`：`ADR_PREMIUM` 新增 `eps` 臂並設為預設；`tests/bench_adr_premium.py` 改為多問法 A/B 並改用 `setup_logging` 落地到 `data/logs`，拿掉不可靠的 `self_convert` regex 判定 | `7feaed4` |
| Ollama token 用量記錄與 `OLLAMA_NUM_CTX` | `src/graph.py`：新增 `_ollama_usage()`（從 `response_metadata` 取 token 數與耗時）、`_warn_if_truncated()`（`prompt_tokens` 貼近截斷門檻時記 warning），`rewrite_question`／`agent`／`generate` 併入記錄；`src/config.py`：新增 `OLLAMA_NUM_CTX`（預設 4096），三個 `ChatOllama` 實例共用；`tests/test_ollama_usage.py` 新增 | `f45088d` |
| `OLLAMA_NUM_CTX` 預設值改為 32768、截斷門檻修正 | `src/config.py`：預設 4096 → 32768，註解記錄 A/B 數據；`src/graph.py`：`_warn_if_truncated` 門檻由「`>= num_ctx//2 - 8`」改為「貼齊 `num_ctx//2 + 2` 的 ±8 以內」；`tests/test_ollama_usage.py` 補 32768 情境與 11338 不誤報的斷言 | `088c0d2` |
| bench 新增 invest 題與 num_ctx A/B 支援 | `tests/bench_adr_premium.py`：新增 `invest` 題與 `INVEST_FIXTURE_NUM_CTX`、`--q` 改逗號分隔、新增 `--out`、新增 `cites_source()` 與 `_generate_with_usage()`（monkeypatch `_ollama_usage` 取回每次呼叫的 token 用量）；記錄 10-07 三組 A/B 結果 | `2bd910f` |
| bench 改依數值比對引用 | `tests/bench_adr_premium.py`：`cites_premium`／`cites_eps` 改成從實際擷取的換算區塊文字取出溢價率與換算 EPS 數值後比對，取代固定字眼 regex | `aff6720` |
| eps2 跨幣別直接比較修正 | `src/i18n.py`：新增 `dual_market_warning_adr`（中英各一）；`src/graph.py` 的 `generate`：有 ADR 換算區塊且 `ADR_COMPARE_RULE=on` 時改用該字串；`src/config.py`：新增 `ADR_COMPARE_RULE` 開關（預設 `on`）；`tests/test_dual_market.py` 新增 3 個測試覆蓋三種開關／區塊組合 | `—` |

待辦（本節新增，詳見上方待辦第 3 項）：eps2 回答期間台股 EPS 與 ADR EPS 可能取自不同期（檢索文件 vs 行情快照）；曾把下一季共識預估誤當實際 EPS；曾把換算方向說反（「ADR EPS 乘以 5」，應除以 5 再乘匯率，新規則那次重現 log 另有一筆「決策卡格式違規」警告尚未查）；eps3 把 ADR 股價的台幣等值講得像 EPS；bench 可考慮存下換算區塊全文方便追查；`ADR_COMPARE_RULE` 開關的 A/B 結束後評估是否移除。
