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

### 待辦（依 CP 值排序）

1. **README Demo / Screenshot 補齊**（`README.md:12-13`, `:109-110`）
   目前為 TODO，先跳過晚點再補。難度：小（0.5-1 天）。

### 保持現狀（已知，僅口頭說明，不列入近期修復）

- **無連線池**（`src/vectorstore.py:14-17`）— 每次查詢新建 DB 連線，`retrieve` 一輪最多疊 4 次。現階段單機 demo 規模無明顯瓶頸；換 `psycopg_pool.ConnectionPool` 是標準解法，但先用真實延遲數據決定要不要做。
- **MOPS 爬蟲脆弱性**（`src/update.py:112-163`）— MOPS 無官方 API，兩段式表單 POST + regex 解析 HTML，網站改版即失效。已有 try/except 全包 + 失敗降級印手動下載指引（`update.py:115` docstring 已明確標註此限制），屬結構性風險而非程式碼品質問題。
- **Ticker regex fallback 誤判**（`src/graph.py:102-106`）— 純英文問題可能誤抓一般單字當 ticker。程式碼內已有 `ponytail:` 註解標註風險與升級路徑（僅在含中文時啟用 fallback）。修復前需先補測試案例，避免 regression。
- **Rewrite regex bypass 誤判追問**（`src/graph.py:60-61`）— 用一次 regex 判斷換取省一次 LLM 呼叫，代價是「追問中剛好含代號/年份」的案例會被誤判成獨立問題不做改寫。屬效能與正確性的刻意取捨。
- **測試為手寫 assert script，非 pytest**（`tests/*.py`，7 個檔案）— 目前僅覆蓋純函式（`route_after_retrieve`、`unique_sources`、格式化函式等），核心節點 `retrieve`/`auto_fetch`/`generate` 因直接耦合 DB 與本地 LLM，未做 mock 層、無自動化覆蓋。轉 pytest 本身工程量小（1 天內），但要測核心節點需先做依賴注入（2-3 天+），現階段 CP 值不如上述待辦項目。

---

## 待補紀錄

後續每次修復或有新決策時，於本檔案新增一節（日期 + 標題），保留「做了什麼／為什麼／取捨」，不需重複貼完整程式碼片段，指向檔案路徑 + 行號即可。
