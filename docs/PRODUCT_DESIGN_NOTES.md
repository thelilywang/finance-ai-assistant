# Product Design Notes

[English](#english) | [中文](#中文)

---

<a id="english"></a>
## English

## Why this exists

Individual investors who want to go deeper than a stock's headline price face a wall of unstructured information: quarterly filings, earnings-call transcripts, analyst notes, and a constant stream of news. Reading all of it is slow; skimming risks missing the number that actually matters. Generic LLM chat tools fill the gap with fluent answers that aren't grounded in anything checkable — you can't tell if a number is real or a plausible-sounding guess.

**Task breakdown**, for a typical question like "is this company's margin improving?":

1. Locate the relevant filing section or news article (often across multiple sources and quarters)
2. Extract and compare the specific figures
3. Cross-check the figure against current market context (price, analyst expectations, upcoming catalysts)
4. Form a view — and know how confident to be in it

Step 1 is pure retrieval and the best target for automation. Steps 3–4 benefit from augmentation — surfacing context faster — but the judgment call in step 4 should stay with the user. That split shaped the whole product: **an assistant that retrieves and organizes evidence, and is explicit about the boundary between "here's what the data says" and "here's what you should decide."**

This is a local-first RAG (Retrieval-Augmented Generation) system: LangGraph orchestrates retrieval and generation, Ollama runs the LLM and embedding model on-device, and pgvector stores the indexed evidence. Data is pulled from SEC EDGAR, Taiwan's MOPS filings system, and news sources (Yahoo Finance RSS, udn, cmoney, cnyes).

---

## Product & UX Design

### How the user interacts with it

The interface is a chat window (Chainlit). The user asks a question in natural language; the system retrieves relevant filing/news excerpts, generates an answer with inline citations, and appends a structured **decision card** — a fixed-format summary (facts, inference, valuation, analyst consensus & thresholds, scenario read, stance, triggers to watch, key upcoming event) plus a live price/EPS chart and a downloadable PDF. If the user asks about a company not yet in the database, the system fetches its filings and news automatically before answering.

### Key AI UX considerations

| Consideration | Design | Implementation |
|---|---|---|
| **Inputs & feedback loops** | Unconstrained natural language — no forms, no ticker dropdowns; the system extracts company/document-type filters itself | Thumbs up/down on each answer; no retraining pipeline behind it yet, but it's the seam where a "was this useful" signal would plug in at larger scale |
| **Transparency** | Source-level transparency, not model-internals transparency — every factual claim traces to a retrieved chunk, not an attempt to explain the LLM's own reasoning | `[SourceN]` inline citations; decision card states plainly which filings/news/live market data it drew from |
| **Communicating uncertainty** | No invented probabilities or confidence scores; the system is allowed to say "no data found" instead of guessing | Decision-card thresholds are the *actual* analyst-consensus range from live market data (low/avg/high); scenario language is strictly conditional ("if EPS comes in above the consensus high…"); empty retrieval after auto-fetch returns an honest no-result answer instead of a hallucinated one |

At the same time, the decision card is designed to never go completely silent: even with thin data, it still surfaces what to watch (triggers, next earnings date, key metrics) so the user isn't left with nothing actionable. Only the directional "stance" is gated on having enough corroborating data — full honesty about uncertainty, not a full retreat from usefulness.

### Automation vs. augmentation

| | Scope in this product |
|---|---|
| **Automated** | Retrieval — finding and organizing evidence across filings, news, and live market data |
| **Kept as augmentation** | The investment decision itself — the system supports the user's judgment, it doesn't replace it |

Every answer ends with a disclaimer to that effect, and the design (conditional language, no bare confidence numbers, no "buy/sell" verdicts) reinforces it structurally rather than relying on a disclaimer alone.

---

## Privacy Considerations

### What data is involved

| Data | Privacy status |
|---|---|
| Financial filings & news | Not personal data — public-record information about companies, no PII in the core retrieval corpus |
| User's own questions & chat history | Potentially sensitive — a query history ("why does this person keep asking about company X") can reveal an investment thesis or other sensitive intent |

### Design response

The architecture is **local-first by construction**, not an add-on privacy feature: the LLM and embedding model run on Ollama on the user's own machine, and the vector database is a local Postgres instance. Nothing is sent to a third-party inference API — this is the reason the local-model stack was chosen over calling a hosted LLM API in the first place. Chat history is currently kept in-memory per browser session and cleared on refresh; it's not yet persisted to disk, which sidesteps a whole category of "how long do we retain this" questions but would need to be revisited if durable history became a feature.

### Applicable regulation, if this went from side-project to a real product

| Regulation | When it applies | Obligation it creates |
|---|---|---|
| Taiwan's Personal Data Protection Act (個人資料保護法) | The moment chat history or any user-identifying data is persisted | Stated collection purpose, retention policy, deletion mechanism |
| GDPR | If EU users are in scope | Right to access/erasure needs a concrete implementation, not just a policy statement |
| Data-provider usage terms (SEC EDGAR, Yahoo Finance, MOPS) | Any redistribution or hosted use of fetched data | Not privacy law, but usage/rate-limit terms — local personal use and a hosted product face very different terms, worth a compliance pass before public deployment |

None of this is implemented yet (no formal retention policy, no deletion flow) — at side-project / single-user scale it hasn't been load-bearing, since chat history isn't even persisted today. It's worth naming because a real launch is exactly the point where "local-first" stops being a sufficient answer on its own.

---

## Ethical Considerations

### Where bias could enter

| Source | Description | Effect |
|---|---|---|
| **Source coverage bias** | Filings come only from SEC EDGAR and Taiwan's MOPS, both covering listed companies only; news is drawn from a handful of outlets (Yahoo Finance, udn, cmoney, cnyes), all US/Taiwan-focused | Answer quality tracks media coverage, not investment merit — a well-covered company gets a richer answer regardless of its actual fundamentals. This is the single biggest fairness risk in the current design |
| **Retrieval bias** | Embedding-based semantic search performs better on companies with a longer history of indexed documents | A newly listed or sparsely filed company yields thinner evidence and a less confident (or absent) decision-card stance — arguably correct behavior (thin evidence → thin conclusion), but coverage quality isn't evenly distributed |
| **Deployment-context risk** | The tool is built for decision support, but nothing stops a user from treating a decision-card "stance" as a buy/sell signal | Gap between intended use and possible misuse — the disclaimer and conditional-language design (no verdicts, no bare confidence numbers) are a mitigation, not a complete fix |

### How the product responds to fairness, accountability, and transparency

| Goal | Approach |
|---|---|
| **Fairness** | Rather than claiming the system treats all companies equally (it doesn't — coverage is uneven by construction), the design goal is to be honest about *when* evidence is thin, instead of papering over a coverage gap with a fluent-sounding answer |
| **Accountability** | Every claim traces to a specific, checkable source; if a claim turns out wrong, it can be traced to exactly which citation it came from, rather than disappearing inside opaque generation |
| **Transparency** | Citations for facts, plain statement of what data underlies the decision card, no pretense of exposing the model's internal reasoning |

Accountability here is narrow: the system doesn't act on the user's behalf (no auto-trading, no auto-alerts), so the decision — and its outcome — stays with the user. What the system does provide is traceability within each answer: its "stance" links back to the specific sources cited right there in that same response.

---

<a id="中文"></a>
## 中文

## 為什麼做這個專案

想深入研究個股的散戶投資人,面對的是大量非結構化資訊:季報、法說會逐字稿、分析師報告、還有源源不絕的新聞。全部讀完太慢,只看重點又怕漏掉真正關鍵的數字。市面上泛用的 LLM 聊天工具雖然能給出流暢的答案,但沒有可查核的依據——你分不出哪個數字是真實的、哪個只是講得很像真的猜測。

**拆解一個典型問題**,例如「這家公司的毛利率是不是在改善?」:

1. 找到相關的財報段落或新聞(常常橫跨多個來源、多個季度)
2. 抽取並比對具體數字
3. 對照當下市場狀況(股價、分析師預期、即將發生的催化事件)
4. 形成看法——並且知道這個看法該有多少信心

第一步是純檢索,最適合自動化。第三、四步適合用「輔助」而非「取代」的方式加速,但第四步的判斷應該留給使用者自己做。這個拆分定義了整個產品的方向:**一個負責檢索與整理證據的助理,並且清楚劃分「資料顯示什麼」與「你該做什麼決定」這兩件事的界線。**

這是一個 local-first 的 RAG(檢索增強生成)系統:LangGraph 負責檢索與生成的流程編排,Ollama 在本機執行 LLM 與 embedding 模型,pgvector 儲存索引後的證據。資料來源包括美國 SEC EDGAR、台灣公開資訊觀測站(MOPS)、以及新聞來源(Yahoo Finance RSS、udn、cmoney、鉅亨網)。

---

## 產品與使用者體驗設計

### 使用者如何互動

介面是一個聊天視窗(Chainlit)。使用者用自然語言提問,系統檢索相關財報/新聞片段,生成帶有內文引註的回答,並在結尾附上結構化的**決策卡**——固定格式的摘要(事實、推論、估值、分析師共識與門檻、情境解讀、立場、觸發條件、即將發生的關鍵事件),加上即時股價/EPS 圖表與可下載的 PDF。若使用者問到資料庫裡還沒有的公司,系統會在回答前自動抓取該公司的財報與新聞。

### AI 產品 UX 關鍵考量

| 考量項目 | 設計原則 | 實作方式 |
|---|---|---|
| **輸入與回饋迴路** | 不受限的自然語言——沒有表單,沒有股票代號下拉選單;公司與文件類型過濾條件由系統自動抽取 | 每則回答旁的讚/踩按鈕;目前背後沒有重新訓練機制,但這是未來擴大規模時「這則回答是否有用」訊號可以介接進來的接口 |
| **透明度** | 「來源層級」的透明,而非「模型內部」的透明——每個事實性主張連回被檢索到的原文,而非嘗試解釋 LLM 自己的推理過程 | `[來源N]` 內文引註;決策卡明確陳述使用了哪些財報/新聞/即時市場數據 |
| **傳達不確定性** | 不捏造機率或信心分數;系統可以回答「查無資料」而非用猜測填補空白 | 決策卡的門檻是即時市場數據抓來的**真實**分析師共識區間(低/平均/高);情境描述一律用條件句(「若 EPS 高於共識區間上緣…」);補抓資料後檢索仍全空時,誠實回覆查無資料,而非生成幻覺答案 |

同時,決策卡的設計原則是不整段棄權:即使資料稀薄,依然會列出該關注什麼(觸發條件、下次財報日、觀察指標),讓使用者不會兩手空空。只有方向性的「立場」需要足夠的佐證資料才會給出——對不確定性誠實,但不是對有用性投降。

### 自動化 vs. 輔助

| | 在這個產品中的範圍 |
|---|---|
| **自動化的部分** | 檢索——在財報、新聞、即時市場數據中尋找並整理證據 |
| **保留為輔助的部分** | 投資決策本身——系統支援使用者的判斷,不取代它 |

每則回答結尾都有相應的免責聲明,而且設計本身(條件式語句、不給裸的信心分數、不給「買/賣」判決)也從結構上強化這個原則,而不只是靠一句免責聲明帶過。

---

## 隱私考量

### 涉及哪些資料

| 資料 | 隱私狀態 |
|---|---|
| 財報與新聞 | 不是個人資料——公司的公開紀錄資訊,核心檢索語料庫裡沒有 PII |
| 使用者自己的提問與對話紀錄 | 可能敏感——一段查詢歷史(「這個人為什麼一直在問某公司」)可能透露投資論點或其他敏感意圖 |

### 設計上的回應

架構本身就是 **local-first**,不是事後加上去的隱私功能:LLM 與 embedding 模型透過 Ollama 在使用者自己的機器上執行,向量資料庫是本機的 Postgres 實例,沒有任何資料送往第三方推論 API——選擇本地模型架構而非呼叫託管 LLM API,一開始的理由就是這個。對話紀錄目前只存在瀏覽器 session 的記憶體裡,重新整理就清空,尚未落地到硬碟——這樣做迴避了一整類「該保留多久」的問題,但如果未來要做持久化歷史紀錄,就必須重新面對這個問題。

### 若從個人專案走向正式產品,適用的法規

| 法規 | 何時適用 | 產生的義務 |
|---|---|---|
| 台灣個人資料保護法 | 一旦對話紀錄或任何可識別使用者的資料開始持久化儲存 | 明確的蒐集目的、保存期限政策、刪除機制 |
| GDPR | 若服務歐盟使用者 | 被遺忘權/存取權需要具體落地的機制,不能只是政策聲明 |
| 資料供應商使用條款(SEC EDGAR、Yahoo Finance、MOPS) | 任何再散布或正式服務化的使用情境 | 不是隱私法,但涉及使用/速率限制條款——本機個人使用與正式產品面對的條款完全不同,對外服務前值得做一次合規檢視 |

以上都還沒有落地(沒有正式的資料保存政策,沒有刪除流程)——在個人專案/單一使用者的規模下,這些還不是真正吃重的問題,畢竟對話紀錄目前根本沒有持久化儲存。特別寫出來是因為,正式產品上線正是「local-first」不再足以單獨作為答案的那個時間點。

---

## 倫理考量

### 偏誤可能從哪裡進來

| 來源 | 說明 | 影響 |
|---|---|---|
| **資料來源覆蓋偏誤** | 財報只來自 SEC EDGAR 與台灣 MOPS,兩者都只涵蓋上市櫃公司;新聞來源集中在少數幾家(Yahoo Finance、udn、cmoney、鉅亨網),都是美股/台股導向 | 答案品質跟著媒體覆蓋率走,而非投資價值——被充分報導的公司會得到更豐富的答案,跟公司本身的基本面好壞無關。這是目前設計中最大的公平性風險 |
| **檢索偏誤** | 以 embedding 為基礎的語意檢索,對已累積較多索引文件的公司表現較好 | 新上市或申報文件稀少的公司,檢索到的證據較薄弱,決策卡的「立場」也會更保守(或乾脆不給)——某種程度上是「正確」行為(證據薄弱→結論保守),但代表覆蓋品質並非平均分布 |
| **部署情境風險** | 工具設計定位是「決策輔助」,但沒有機制能阻止使用者把決策卡的「立場」直接當成買賣訊號 | 「設計初衷」與「可能誤用」之間的落差——免責聲明與條件式語言設計(不給判決、不給裸信心分數)是緩解措施,不是完整解方 |

### 產品如何回應公平性、當責、透明度

| 目標 | 做法 |
|---|---|
| **公平性** | 與其宣稱系統對所有公司一視同仁(事實上並非如此——覆蓋率本來就不均),設計目標是讓系統在證據薄弱時誠實承認,而不是用一段流暢的答案掩蓋覆蓋率的缺口 |
| **當責** | 每個主張都能追溯到具體、可查核的來源;若某個主張後來被證實有誤,可以精確指出它來自哪一則引註,而不是消失在不透明的生成過程裡 |
| **透明** | 事實有引註,決策卡的資料依據會明說,不假裝能揭露模型內部的推理過程 |

這裡的當責範圍較窄：系統不會代替使用者做任何動作（不自動下單、不自動示警），決策與結果都由使用者自己承擔。系統提供的是單則回答內的可追溯性：這則回答的「立場」會連回同一則回答裡引用的具體來源。
