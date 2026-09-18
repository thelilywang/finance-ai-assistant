# 維護歷程

紀錄專案已知的技術債、優化候選項與決策依據。重點不只在「做了什麼」，也在「為什麼這樣取捨」與「什麼是已知但刻意延後的」。

---

## 目前待辦（依 CP 值排序）

1. **決策卡缺乏輸出驗證層**（`src/graph.py` 的 `generate`、`src/i18n.py` 的 `trend_*` 系列）
   決策卡的所有格式規則——欄位數、免責聲明、引用編號合法性、金額是否標幣別、比較表結構——目前只存在於 prompt 文案，程式端零檢查。這是多個已觀察到的缺陷的共同根因：09-17 加字數約束導致免責聲明遺漏、09-18 加幣別約束導致整欄棄權、模型自創 `[即時市場數據]` 這個未定義的引用標記（下一項）、同一份 prompt 兩次執行跑出不同的表格結構（幣別寫在表格列 vs 寫在表格後小結）。共通點是**只能靠人逐份目視才發現，且每次都是在踩到之後**。
   **預期做法**：`generate` 產出後掃一遍，比對實際欄名與 `allowed_fields` 的預期集合、檢查免責聲明存在、檢查 `[來源N]` 的 N 落在 `retrieved` 範圍內，違規只寫 log 不擋輸出（品質問題不該讓使用者拿不到答案）。這比繼續疊文案有長期價值——文案改動的效果無法回歸測試，log 可以。難度：小至中。
2. **`[即時市場數據]` 被當成引用標記**（`src/i18n.py` 的 `trend_rules_common`、`src/app.py:130` 的來源清單）
   引用規則只允許 `[來源1]`～`[來源N]`，且 prompt 明文說行情快照不參與來源編號，但模型自創了 `[即時市場數據]` 這個標記。**這不是幻覺**——被標注的數字都真實來自快照，問題是它違反格式契約：`app.py` 依編號組出的來源清單對不上這個標記。2026-09-18 比對本次改動前後的輸出確認為**既有行為**，非本次引入。屬格式契約問題，該由上一項的 post-check 處理，不是再加一句文案。難度：小（併入上一項）。
3. **README Demo / Screenshot 補齊**（`README.md:12-13`, `:109-110`）
   目前為 TODO，先跳過晚點再補。難度：小（0.5-1 天）。
4. **數字類查詢的直答通道**（`src/graph.py` 的 `assemble`/`generate`、`src/mcp_server.py`）
   官方 OpenAPI 取得的結構化財報數字目前與 PDF 文字一樣進 `doc_chunks`，走同一條向量檢索路徑。「台積電最新一季 EPS 多少」這類純數字問題其實不需要 embedding 相似度比對——資料庫裡就有確定的那一格，繞過檢索可同時降低延遲與消除檢索誤差。要做需新增一個直查結構化數字的 MCP tool，並調整 `assemble`/`generate` 的 context 組裝與引用編號邏輯。**前置問題**：直答的數字若不進 `retrieved` 就沒有 `[來源N]` 編號，牴觸決策卡「不得編造資料中沒有的數字」的反幻覺規則（`src/i18n.py:70`），需先決定這類數字如何標註出處。影響面大，刻意獨立處理。
5. **雙掛牌對照表改為 API 查詢 + 落地快取**（`src/tickers.py` 的 `TW_US_DUAL_LISTED`）
   目前台美雙掛牌（台積電＝2330／TSM）的對應關係是寫死的靜態 dict，四檔手動維護。台股 ADR 檔數少且極少變動，靜態表在現階段夠用且零延遲，但新增標的要改程式。預期做法是改為 API 查詢後落地快取（優先讀資料表、查不到才打 API）。**卡在資料來源**：既有的 yfinance 與兩個官方 OpenAPI 都沒有 ADR 對應欄位，靠公司名稱模糊比對不穩，須先找到可靠端點才值得動工。在那之前往靜態表加一行即可。
6. **MCP server 未對外開放與 healthcheck**（`docker-compose.yml`）
   `mcp-server` 目前只在 docker 內部網路提供服務，未映射 port 到 host，Claude Desktop 等外部 client 尚無法連入（Bearer 驗證已就緒，開放時即可把關）。另外 FastMCP 沒有現成的 health endpoint，`depends_on` 只能用 `service_started`，實際就緒檢查靠 app 端每次開對話時連線（失敗會顯示錯誤訊息）。等真的需要外部存取或遇到啟動競態時再處理。
7. **AI 執行時間的持續觀測與回測**（`data/logs/`、`src/logging_setup.py`）— **持續性項目，不是做完就關掉**
   logfile 已逐節點記錄耗時（`rewrite_question`／`extract_filters`／`agent`／`generate`／`retrieve`），同一題以 `qid` 串連。需累積一段時間的真實使用資料後，分析各節點耗時分佈：已知瓶頸是本地模型生成，但**佔比多少尚未用數據確認**，這是決定下一輪優化該投在哪裡的依據（例如若 `agent` 的 tool loop 輪數才是主因，優化 `generate` 就是做白工）。分析方式：`data/logs/*.log` 是 JSON Lines，可直接用 pandas 或 jq 彙總。

   **現況：`generate` 僅 1 筆，門檻未達。** 已有一次真人完整問答讓四個 LLM 節點全部觸發，串連機制確認可用，但一筆不足以推翻或證實任何佔比假設。**開始分析的門檻是 `generate` 累積約 30 筆以上**（涵蓋不同題型與是否命中快取）；在那之前不要拿零星樣本或 smoke test 的數字當結論。彙總時注意 log 欄位名為 `node` 而非 `event`（`select(.node=="generate")`）。
8. **`answer_shape` 誤判率的量測**（`src/graph.py` 的 `extract_filters`）
   目前 `answer_shape` 預設 `"full"` 是靠「誤判成 news 會讓投資題失去素材，代價不對稱」的風險論證選的，不是靠實測錯誤率。2026-09-17 的 A/B 中 5 題 20 次分類全部正確，但 5 題不構成誤判率估計。要驗證這個預設是否過於保守（若實際上大多數新聞題都被判成 `full`，欄位裁剪的節省就吃不到），需要一份人工標註的問題集——這也是目前唯一還會讓那次改動效益歸零的未知數。難度：小，但要先花時間標題目。
9. **生成改為 streaming 輸出**（`src/graph.py` 的 `generate`）
   目前 `generate` 用 `.invoke()` 等完整回應才回傳，使用者要盯著空畫面 90 至 160 秒。改 `.stream()` 不會讓總耗時變短，但**首字時間**會從「全長生成完」降到「首個 token」，體感差異極大。這與 09-17 的欄位裁剪是**正交**的兩件事——一個減少總量、一個改善等待感受，可疊加。影響面是 `generate` 的回傳介面與 `app.py`／`cli.py` 的顯示層（Chainlit 有現成的 token streaming 支援），另需確認 Langfuse 的 span 在 streaming 下仍能正確收尾。難度：中（1-2 天）。
10. **決策卡的 `## 📈` 結構邊界改用非 emoji 標記**（`src/i18n.py` 的 `trend_*` 系列、`src/graph.py` 的 `assemble`）
   決策卡各欄位目前以 emoji 標題（`## 📈` 等）當結構邊界，下游若要解析欄位就得依賴 emoji 字面值。2026-09-17 改為逐欄組裝 prompt 時刻意**沒有**一併處理，以免把「換欄位邊界」的風險混進效能改動裡。單獨做的前置條件是先確認有沒有下游真的在解析這些標題——若只是給人看的顯示，就屬於「不必做」而非「待辦」。
11. **跨市場比較題的檢索素材落差**（`src/graph.py` 的 `retrieve_context`）
    語料以台股為主，問「NVDA 與聯發科比較」時美股標的往往只有 yfinance 行情數字、沒有任何敘事文件，比較表中該標的的定性欄位只能誠實寫「檢索資料不足」。誠實留白優於編造（反幻覺原則優先），但比較表半邊空白的體驗不好。這是**檢索面的資料覆蓋問題，不是生成面的 bug**，要解得從語料來源下手（增加美股新聞／財報來源），不是改 prompt。難度：中至大，視新增來源而定。
12. **`dual_market_warning` 措辭不精確且觸發條件過窄**（`src/i18n.py` 的 `dual_market_warning`、`src/graph.py` 的 `generate`）
    措辭把台美雙掛牌的 ADR 一律當成美元計價來提醒，實際上 ADR 的計價與換算關係比這句話複雜。另外觸發條件是「單一公司且為雙掛牌且 `market == "both"`」，多標的比較題不會觸發——但跨市場比較正是最需要提醒幣別的場合。2026-09-18 在 `market.py` 的快照加入 `currency` 欄後，幣別資訊已直接進 prompt，此條的急迫性下降，但措辭錯誤本身還在。難度：小。
13. **logfile 保留策略與敏感資料**（`config.LOG_BACKUP_DAYS`）
   目前只記錄長度（`prompt_chars`／`answer_chars`）而非內容，故無個資疑慮。若未來為了回測要記錄 prompt／回應全文，需先決定保留天數與去識別化方式——專案已有 `NEWS_RETENTION_DAYS`／`THREAD_RETENTION_DAYS` 的保留期慣例可循（後者的註解明確指出「對話含提問內容，屬個資，留短一點」）。另需觀測 `LOG_BACKUP_DAYS=30` 是否合適：日檔大小取決於實際使用量，累積一段時間後回頭確認磁碟佔用與「回測要看多久以前」的實際需求是否匹配。

## 保持現狀（已評估，判斷暫不處理）

- **`_select_exhibit` 的「取最大 htm」啟發式——維持觀察**（`src/update.py`）— 尚未實際誤挑過，`ingest_text` 的入庫字數警示已是後備防線。原設想的升級路徑（優先選 EX-99.1）經實測不成立：ASML 樣本中 EX-99.1 是新聞稿、EX-99.2 才是投影片，真正財報是 EX-99.4，改用類型標籤反而更差。

- **領域微調 Embedding 與 Cross-Encoder 重排——評估後不採用**（`src/config.py` 的 `EMBEDDING_MODEL`、`src/graph.py` 的 `retrieve_context`）— 兩者皆為擋掉離題查詢而評估，2026-09-10 判斷不做。**領域專用 Embedding** 針對的病因（通用模型對時間詞權重過高）經實測並不存在，換模型卻要重跑全庫 embedding 並重新量測所有門檻。**Cross-Encoder 重排**技術上可行，但要對每次檢索的 top-K 逐筆推論，在生成速度已是瓶頸的前提下只會惡化延遲。離題攔截最後由 LLM 意圖分類以零額外延遲解決（推翻過程與量測數字見 2026-09-10 章節）。若未來語料跨足多領域、或改用推理速度足夠的硬體，可重新評估 Cross-Encoder 作為檢索精度（而非離題過濾）的手段。

- **異質文檔重排與配額控制——量測後判斷不需處理**（`src/graph.py` 的 `retrieve_context`）— 原列為待辦，2026-09-10 實測後撤下。跨來源重排的前提（兩種文檔在同一名次空間混排）不成立：四次檢索各自 `ORDER BY` 後串接，財報與新聞從未進入同一個排序，再加一層重排是重解已解的問題。配額維持主檢索 5／補新聞 3／補市場新聞 2：原疑慮是純財報問題固定補 3 條新聞屬浪費，但比對引用編號後確認那些新聞確實被決策卡引用，且 `trend_section` 明文要求財報＋新聞＋行情齊備才給傾向，砍掉會讓必填欄位失去素材。那 3 條新聞是必要成本。

- **多標的時圖表只涵蓋第一家——2026-09-18 撤下，已逐家併陳**（`src/app.py` 的圖表段）— 09-16 原判斷是「逐家併陳要重排互動版面與 PDF 結構，代價遠大於收益」。這個代價估錯了：`report_pdf(report_md, figures)` 本來就吃扁平的 figure 串列並依序附圖，多家只是多幾張圖，PDF 端不需任何重排；互動版面只需把圖表 `name` 帶上代號即可區分。實際改動是一層 `for company in companies` 迴圈。**仍維持現狀的部分**：`_primary` 的另外兩個使用者——`no_result`（查無資料時的行情補充）與 `ask_market`（雙掛牌市場反問，多標的時由 `resolve_market` 明確跳過，理由是「兩家公司比較還要先選市場體感很差」）——都不影響決策卡欄位與圖表，維持取第一家或略過。

- **堆疊 prompt 約束會擠掉欄位本職——2026-09-18 實測，勿再用文案解格式問題**（`src/i18n.py` 的 `trend_field_*` 系列）— 這是本專案第二次踩到同一個坑。09-09 為決策卡加字數約束，結果輸出反而變長 35% 且遺漏免責聲明；09-18 為 `trend_field_valuation`／`trend_field_consensus` 各加一句幣別標示要求，模型改為整欄輸出「無法提供估值觀察」，即使快照裡的 PE 與目標價都齊備——直接違反決策卡三原則中的「不得整段棄權」。兩次的共通機制是**單一欄位的指令密度存在上限，超過之後模型優先滿足新約束、犧牲該欄原本的職責**。實作上的結論有兩條：新約束只加在最需要它的那一欄（幣別最後只留在 `trend_field_comparison`，跨幣別並排只發生在比較表裡，而幣別語意一點沒丟失），以及**格式契約要靠程式檢查而非文案**（待辦第 1 項）。

- **Redis 取代程序內的 query embedding 快取——評估後不採用**（`src/graph.py` 的 `_embed_query_cached`）— 2026-09-13 判斷不做。原設想是快取跨程序共享能提高命中率，但現在只有 `app` 與 `mcp-server` 兩個單一程序，而快取收益集中在同一題的 agent tool loop 內，本來就在同一程序，跨程序共享收不到額外命中。代價則包含一個 container、網路依賴、1024 維向量序列化（每筆約 8KB，往返可能比本機 dict 慢）與一組「Redis 掛了怎麼辦」的降級路徑。**觸發條件**：MCP server 要跑多 worker／多副本，或希望快取跨重啟存活；屆時 `_embed_query_cached()` 的介面不用改，只換內部儲存。

- **單一 SQL 用 `UNION ALL` 取回三段檢索——評估後不採用**（`src/graph.py` 的 `retrieve_context`）— 2026-09-13 判斷不做。可省下兩次往返與連線佔用，但要在 SQL 裡表達「主結果有新聞就不要同公司新聞」這類條件邏輯，會把現在讀得懂的 Python 條件變成難維護的 SQL；三段各自 `ORDER BY` 也是刻意設計，見上方「異質文檔重排」一項。連線佔用本身經實測並非問題（詳見 2026-09-13 章節），這個優化要解的成本並不存在。

- **改用 async DB driver 取代 ThreadPoolExecutor——評估後不採用**（`src/graph.py` 的 `_retrieve_parallel`）— 2026-09-13 判斷不做。`retrieve_context` 是同步函式、被 `asyncio.to_thread` 包著呼叫，改 async 要一路改到 graph 節點與 MCP tool，影響面遠大於收益——而並行本身的效益幅度小，遠小於快取的貢獻（量測數字見 2026-09-13 章節的實測表）。

- **回應延遲過長，輸入側架構已無可省**（`src/graph.py` 的 `generate` 節點）— 單題總耗時 186 至 470 秒。三個可行方向已於 09-09 收斂：`_trim_for_llm` 裁掉 agent 迴圈重複傳遞的 context（降低 context 膨脹，不改善延遲）、`route_after_tools` 在資料明顯足夠時跳過第二輪 agent 決策（結構性省下一次 LLM 呼叫，該節點原佔 82 至 106 秒）、決策卡字數約束經 A/B 實測反使輸出變長 35% 並遺漏免責聲明，已排除。另兩項候選亦已排除：合併 `rewrite_question`/`extract_filters` 僅佔 3%；換用較小或 MLX 版本的模型會先失去 tool calling 與結構化輸出能力。**剩餘瓶頸是本地模型的生成速度本身（穩定在每秒約 10 字，`generate` 一題需 90 至 160 秒），屬硬體限制而非架構問題**，換用推理速度更高的硬體才會改變。詳見 2026-09-08、09-09 章節。

  **2026-09-17 部分推翻此條的範圍**：上述收斂全部針對「輸入側」（context 大小、呼叫次數、模型選用），結論在該範圍內仍成立。但「每秒字數固定」推不出「總時間不可壓」——還有**輸出字數**這個變數。決策卡欄位依意圖與證據裁剪後，news 題實測字數降 36.5%、時間同向降 23.6%（詳見 09-17 章節）。**教訓是「硬體限制」的結論當初被套用得太寬**：正確的說法是每秒輸出 token 數受硬體限制，而不是回應時間受硬體限制。仍然成立的部分是體感——121s 與 159s 都太久，量級沒變，那要靠 streaming（待辦第 9 項）而非繼續砍總量。
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
| Ticker regex fallback 誤判 | 治本而非修 regex：`extract_filters` 從手寫 prompt + `json.loads` 改用 `with_structured_output(ExtractedFilters)`，代號由 Pydantic `field_validator` 呼叫新增的 `normalize_ticker()` 正規化（去除 `.TW`/`.PR.A` 等後綴並驗證格式）。原本的 regex fallback（純英文問題會誤抓一般單字當 ticker）直接移除；多標的問題當時改為回報錯誤而非硬猜一個代號（該降級已於 2026-09-16 由多標的支援取代）。同時修正三處既有的 `isdigit() and len==4` 台股判斷——ETF 新制 6 碼、特別股與可轉債的字母尾碼會被誤判成美股，統一改用 `is_tw_ticker()`。 | `2a00991` |

---

## 2026-09-04　靜默選錯修正：MOPS 財報選檔、Rewrite 追問誤判

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

改用標準庫 `logging` 輸出 JSON Lines 到已掛載的 `data/logs/`，四個 LLM 呼叫點與 `retrieve_context` 各記 `elapsed_ms`，同一題以 `qid` 串連（設定細節見改動內容表）。**只記長度不記內容**，避免把提問寫進 log（保留策略未定前不落地個資，見待辦第 10 項）。

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

**已知限制**：只改紀錄的正確性，未改變任何抓取行為；補抓成功率要等實際使用累積後才答得出來（門檻見待辦第 7 項）。

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

**取捨**：多標的時直接略過雙掛牌的市場反問——兩家公司做比較還要先回答「要台股還美股」體感很差，而「雙掛牌 ∩ 多標的」是罕見交集。走勢圖與 ADR 提醒同理，都是單一公司概念，其範圍與重新評估條件見「保持現狀」對應一條。

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

**行情抓取的循環依賴用三態解。** 吃行情的三欄要不要納入，取決於快照抓沒抓到；但值不值得抓，又取決於有沒有欄位要用它——而 `get_market_snapshot` 是 blocking 未快取網路呼叫（實測冷啟 2.50 至 3.55 秒、熱 0.90 至 0.94 秒），就擋在 first token 前面。解法是 `has_market: bool | None` 兩段求值：第一段傳 `None`（語意為「還沒抓」，樂觀視同可能有，讓吃行情的欄位留在候選集供 `needs_market` 判斷），抓完後第二段傳實際結果定案。用 boolean 會自我實現否定——`False` 抑制那些欄位、`needs_market` 因此為假、行情永遠不會被抓。第二段同時關掉另一個失敗模式：抓失敗時那些欄位自動剔除，不會留一個沒素材的空欄逼模型寫「資料不足」。

**「不得整段棄權」改為測試斷言。** `conclusion`／`facts`／`inference`／`upside`／`risk` 五欄在任何形式、任何證據狀態下無條件輸出。寫在註解裡，下一個調 gating 邏輯的人隨時會破壞它，故 `tests/test_allowed_fields.py` 對「形式 × 證據集 × 行情狀態」的完整交叉組合逐一斷言這五欄必然存在。

**取捨**：計時起點前移先獨立 commit（`34cfd5c`）——舊計時器緊貼 LLM 呼叫之前，而行情抓取就發生在那之前、同一節點之內，用它量兩段式的節省會完全看不見。拆開是因為這個修正獨立於 gating 正確，方案若因 A/B 數字不佳被 revert 也該留著。另有一項結構調整刻意未併入，以免把欄位邊界的風險混進效能改動（待辦第 10 項）。`answer_shape` 是對整個問句判定一次的回答形式，與標的數無關——多標的比較題同樣共用一個形式，`allowed_fields` 不讀 `companies`，故不在 09-16 那批「多標的時取第一家」的降級範圍內。

**驗收**（同容器同模型 `qwen3.5:9b`，5 題 × 2 次 × 開關兩組共 20 次，0 失敗；`market` 預先指定以繞過雙掛牌反問，否則 2330 題會停在市場詢問而到不了 `generate`）：

| 題型 | 欄位數 開→關 | 輸出字數 開→關 | 節點總時長 開→關 |
|---|---|---|---|
| news（2 題） | 8 → 13 | 805 → 1,267（**−36.5%**） | 121.4s → 158.8s（**−23.6%**） |
| full（2 題） | 13 → 13 | 691 → 769（−10.1%） | 114.3s → 104.1s（+9.9%） |
| 邊界（1 題） | 11 → 13 | 1,313 → 1,332（−1.4%） | 165.7s → 168.1s（−1.4%） |

**news 題的假設成立：字數降 36.5%，時間同向降 23.6%。** 逐題目視確認被剔除的五欄（估值觀察／市場共識與門檻／情境解讀／法說會關注清單／建議傾向）在輸出中**連欄名都沒出現**，且無「資料不足」佔位；關閉開關時同題同模型則五欄全數出現——這是「不放進 prompt」與「請模型省略」的差別被實際驗證。

**`temperature=0` 下輸出字數完全可重現**：同題同設定連跑兩次字數一模一樣（772／772、1109／1109、837／837、1424／1424）。

**full 與邊界題的差異是雜訊，不是效果。** full 題兩組設定允許的欄位集合完全相同（13 欄，只有排列順序不同），所以字數那 10.1% 的差來自 prompt 欄位順序造成的模型自由度，與 gating 無關；且該題型實際上兩組都沒輸出決策卡、直接回散文。這與計畫預期的「full 題兩組無差異」一致。

**已知限制——時間軸的雜訊底線高達 ±16 至 37%。** 同題同設定、**輸出字數完全相同**的兩次執行，節點總時長可以差 91.6s 對 118.9s（35%）。這意味著單次比較毫無意義，也是 `MAINTENANCE_LOG.md` 早先「generate 本身的浮動就蓋過了省下的時間」那條記錄的再次印證。本次結論之所以站得住，是因為：(1) 字數是確定性的；(2) news 的時間效果在 rep0（−20.0%）與 rep1（−27.8%）**各自獨立成立**；(3) 執行順序上 gating=1 固定跑在 gating=0 之前，而 rep0 整體比 rep1 慢約 19s，這個暖機梯度是**對 gating=1 不利**的方向，效果仍然存活。若未來要更精確的數字，需隨機化執行順序並加大樣本。**這個節省沒有改變體感的量級**，降低的是總量而非等待感受（見「保持現狀」該條的 09-17 補述）。

**已知限制。** 本次 20 次執行中 `answer_shape` 分類全部正確（邊界題「新聞對股價的影響」如預期判為 `full`），但 5 題不構成誤判率的估計（待辦第 8 項）。另外 `generate` 的 logfile 累積筆數仍未達約 30 筆的分析門檻——本次是以腳本直接驅動 graph 並自行記錄，沒有經過 Chainlit，故未寫進 `app-*.log`（待辦第 7 項的門檻不因本次而推進）。

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

## 2026-09-18　多標的比較題的行情逐家併陳與比較欄位

同一條線的三段：先修好「多標的時四個決策卡欄位無聲消失」這個 bug，再為比較題新增一個比較欄位，最後在驗證中發現幣別標示錯誤、追到資料層修掉。過程中有兩項改動經 A/B 實測後回退，兩者的失敗方向一致，一併記在下方。

**病因是誤用既有機制，不是缺功能。** `generate` 原本只抓 `companies[0]` 一家的行情，其餘標的沒有快照，`allowed_fields(has_market=False)` 因而剔除估值觀察／市場共識／情境解讀，連帶需要三者齊備的建議傾向也一起消失——實測證據同樣齊備下單一公司 13 欄、多標的只剩 9 欄。那條剔除路徑是為「yfinance 抓取失敗」設計的降級（抓不到就別留空欄逼模型寫「資料不足」），多標的走進同一條路徑，但原因是**根本沒去抓**：用「資料不足」實作了「我沒拿」。修法是 `market.py` 新增 `get_market_snapshots(companies)`，沿用 `_retrieve_parallel` 既有的 `ThreadPoolExecutor` 形狀，`has_market` 改判為「至少一家成功」；部分失敗時沿用既有的 `market_partial_note` 在 prompt 中明講哪些標的沒有即時行情，讓缺漏可見而非無聲。

**單張決策卡、欄內逐家列，而不是每家一張卡。** 每家一張完整卡會讓 13 個欄名重複 N 次、輸出字數翻倍，直接吃掉 09-17 剛做完的裁剪效益；而比較題最想要的「對比」反而沒有任何欄位負責寫。故改的是 `trend_field_valuation`／`consensus`／`scenario` 三欄的文案語氣（逐家分列、每家以「公司名（代號）」標示），並新增只在多標的時出現的 `comparison` 欄位承接對比職責。

**公司名沒有新造對照表。** `get_market_snapshot` 已經在呼叫 `ticker.get_info()`，回傳的 dict 裡本來就有 `longName`／`shortName`，`format_snapshot` 只是沒取用——等於免費且涵蓋台美股全部標的的公司名來源。`src/tickers.py` 的雙掛牌對照表只涵蓋五檔，不夠通用，不採用。

**幣別的根因在資料層，不在文案。** 驗證跨市場題（NVDA + 2454）時發現輸出寫成「NVIDIA 目標價 215.0 元」——把美元數字標成元。第一直覺是加一句文案要求標明幣別，但這等於要求模型從股票代號推斷計價幣別，本身就是在請求幻覺。查 `format_snapshot` 後確認它從未輸出幣別，而 `info` 裡的 `currency` 欄位在兩個市場都有值（實測 NVDA→USD、2330.TW／2454.TW→TWD）。**修法是在快照的價格數字前面加一行 `currency:`**，讓模型讀到數字時單位已知。這同時修好單一公司題，也對未來的港股日股自動正確，不需要 `is_tw_ticker` 這類判斷。

**推翻的假設一：`trend_header` 的「必須單行條列」是排版偏好，不是契約——但實測不支持鬆綁。** 原本的措辭要求每欄輸出成獨立的 markdown 條列項目、不得把多欄擠在同一行，而 markdown 表格塞不進單一條列項目。全庫只有 `app.py:130` 的 `answer.split("## 📈", 1)[0]` 依賴決策卡格式，而它只用到區段標題、不碰欄位層級，故假設鬆綁措辭無害且能讓 `comparison` 的表格自然合法。A/B 實測後回退：鬆綁組的欄位邊界確實變糊。最後改採範圍更小的做法——在 `trend_field_comparison` 文案末尾加一句「本欄以 markdown 表格呈現，不套用單行條列格式」，把例外限縮在唯一需要它的那一欄，`trend_header` 維持原樣。revert 後重跑確認輸出與基準逐字一致。

**推翻的假設二：幣別約束加在每個吃行情的欄位上會更保險——實際造成整欄棄權。** 詳見「保持現狀」該條。最終狀態是幣別只加在 `trend_field_comparison`。

**驗證**（同容器同模型 `qwen3.5:9b`、`temperature=0`、固定 `retrieved` 素材以排除檢索浮動，直接驅動 graph）：

| 情境 | 欄位數 | 決策卡字數 | 免責聲明 | 比較表 | 幣別誤標 |
|---|---|---|---|---|---|
| 跨市場（NVDA + 2454） | 14 | 1,751 | 有 | 4 列，其中 3 列定性 | 無 |
| 同市場（2330 + 2454） | 14 | 1,794 | 有 | 4 列，其中 3 列定性 | 無（單一幣別） |

四個消失的欄位回來了，`comparison` 出現且渲染為 markdown 表格。表格內容確認不是行情數字的搬運：兩份輸出都是市場定位／成長動能來源／風險來源三列定性加一列估值觀察，每格附 `[來源N]`，推不出來的格子誠實寫「檢索資料不足」而非用產業常識填空。跨市場那份的表格後小結明寫「兩家公司幣別不同（USD vs TWD），故無法直接比較股價絕對值」——**幣別語意只在 `comparison` 一處約束就足夠，不需要在每個欄位重複**。明文禁止的資金配置比例與「若只能選一檔」在兩份輸出中均未出現。

**已知限制——同一份 prompt 的結構不穩定。** 兩次跨市場執行，一次把幣別寫成表格裡的 `| 幣別 | USD | TWD |` 一列、另一次寫在表格後的小結；另有一次把本該獨立成段的小結塞進表格當一列。兩種都不算錯，但顯示格式規則只靠文案時**沒有下限保證**，這是待辦第 1 項（輸出驗證層）的直接依據。另外模型會把快照給的 `Taiwan Semiconductor Manufacturing` 在內文寫成「台積電」——現行「公司名不得自行補寫」的約束只擋住無中生有，沒擋住改寫與翻譯；此例對應正確，影響低，暫不處理。

**已知限制——耗時未量測。** 本次全部驗證以腳本直接驅動 graph 並固定素材，未經 Chainlit，故 `generate` 的 `elapsed_ms` 沒有進 `app-*.log`，多標的並行抓取的實際節省尚無數字（待辦第 7 項的門檻不因本次推進）。串流（待辦第 9 項）與本次正交，刻意不混在同一批改動裡，以免耗時影響量不開。

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

## 待補紀錄

後續每次修復或有新決策時，於本檔案新增一節（日期 + 標題），保留「做了什麼／為什麼／取捨」，不需重複貼完整程式碼片段，指向檔案路徑或函式名即可。新完成的修復項目同時要移出「目前待辦」或「保持現狀」區塊。
