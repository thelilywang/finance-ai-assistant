"""集中管理雙語字串，不引入 i18n 套件。"""
import re

STRINGS = {
    "zh": {
        "fetch_notice": "🔍 資料庫沒有這檔股票的資料，已自動抓取最新財報/新聞（首次約需 1-3 分鐘 embedding），正在重新檢索…",
        "connecting": "正在連接資料服務…",
        "connect_failed": (
            "⚠️ 資料服務連線失敗，暫時無法查詢。\n\n"
            "請確認 mcp-server 服務已啟動（`docker compose up -d mcp-server`），"
            "並檢查 MCP_SERVER_URL / MCP_AUTH_TOKEN 設定是否正確。\n\n錯誤訊息：{error}"
        ),
        "sources_label": "參考來源",
        "report_generated_at": "產生時間",
        "no_result_fetched": (
            "已嘗試自動抓取「{company}」的財報與新聞，但仍查無資料。"
            "可能是未上市公司（如 SpaceX）、代號/ticker 有誤，或該來源暫時無法取得。"
            "若你有相關文件，可手動匯入：python -m src.ingest --file <路徑> --company <代號>"
        ),
        "ask_market": (
            "「{name}」在台股與美股都有掛牌，兩邊的數字不能直接比較："
            "台股（{tw}）以新台幣計價、按季公布；美股（{us}）是 ADR，以美元計價，"
            "且每股基準不同（1 股 ADR 對應數股台股普通股）。\n\n"
            "請問你要看哪一邊？（請點選下方按鈕）"
        ),
        "market_btn_tw": "台股 {tw}",
        "market_btn_us": "美股 {us}",
        "market_btn_both": "兩邊都要",
        "market_btn_tw_tip": "以新台幣計價、按季公布",
        "market_btn_us_tip": "ADR，以美元計價",
        "market_btn_both_tip": "並列呈現，不換算成同一數字",
        "market_picked": "已選擇：{choice}",
        "otc_adr_note": (
            "（補充：{name} 在美股有 ADR（{us}），但屬場外交易（OTC）、未向 SEC 申報財報，"
            "本系統取不到其財務數字，以下僅為台股（{tw}）資料。）"
        ),
        "dual_market_warning": (
            "本題同時涵蓋台股（{tw}）與美股（{us}）。兩市場的計價幣別、公布期間與每股基準皆不同"
            "（同一家公司的台股本股與美股 ADR 另有股數換算比例），請分開陳述、標明各自幣別與期間，"
            "不得直接相除、相減或換算成同一數字比較。幣別一律取自「即時市場數據」的 currency 欄，"
            "不得由代號推測。"
        ),
        "dual_market_warning_adr": (
            "本題同時涵蓋台股（{tw}）與其美股 ADR（{us}）。兩邊的計價幣別與公布期間不同，"
            "且 1 股 ADR 對應多股台股普通股，原始數字不可直接比較。比較兩邊的股價或 EPS 時，"
            "一律引用上方「ADR 換算」區塊算好的台幣等值與差距百分比，不得拿不同幣別的原始數字"
            "直接比大小，也不得自行重算。區塊裡沒有 EPS 等值時，兩邊的 EPS 只能分開陳述、"
            "標明幣別，不得判斷誰高誰低。幣別一律取自「即時市場數據」的 currency 欄，"
            "不得由代號推測。"
        ),
        "no_result_plain": (
            "資料庫中找不到與這個問題相關的財報或新聞內容。"
            "問題若有指名上市公司（代號或 ticker）會自動抓取資料，"
            "也可以手動匯入：python -m src.ingest --file <路徑> --company <代號>，或換個問法。"
        ),
        "off_topic": (
            "這個問題看起來不在財經資料的範圍內。本助理只回答上市公司的財報與新聞相關問題。\n\n"
            "請改問特定公司的財務表現、營運狀況或市場動態，例如「台積電最新一季毛利率如何」"
            "或「NVDA 近期有什麼新聞」。"
        ),
        "answer_lang_rule": "- 全文以繁體中文回答",
        "trend_header": (
            "## 📈 投資決策參考\n"
            "（以 buy-side 分析師的角色填寫下列欄位。格式硬性要求：每欄輸出成獨立的 markdown 條列項目"
            "「- **欄名**：內容」，欄名粗體、內容務必簡潔；已知事實／推論／觸發條件的多個點用巢狀子條列，不得把多欄擠在同一行："
        ),
        "trend_field_conclusion": "- **一句話結論**：",
        "trend_field_facts": "- **已知事實**：1-2 點子條列，每點必附 [來源N]",
        "trend_field_inference": "- **推論**：1-2 點子條列，明確標示為推論",
        "trend_field_upside": "- **利多**：",
        "trend_field_risk": "- **風險**：",
        "trend_field_comparison": (
            "- **標的比較**：輸出一張 markdown 表格，第一欄是比較項目、其餘每欄一家標的"
            "（表頭寫「公司名（代號）」，公司名取自「即時市場數據」的 name 欄，取不到就只寫代號）。"
            "比較項目自行依題目決定 3-5 項，其中至少一半須為定性項目"
            "（如市場定位、成長動能來源、風險來源），不得整張表都是行情數字——"
            "純數字的比較與「估值觀察」欄重複。表格後接 2-3 句定性對比小結。"
            "每個定性格子必附 [來源N]，推不出來就寫「檢索資料不足」，不得用產業常識填空。"
            "金額類數字（股價、目標價、市值）必須標明幣別，幣別取自各標的「即時市場數據」的 "
            "currency 欄，不得由代號推測；各標的幣別不同時不得相除、相減或換算成同一數字比較。"
            "不得給資金配置比例、不得寫「若只能選一檔」、不得給加碼／減碼指令。"
            "（本欄以 markdown 表格呈現，不套用單行條列格式；表格須含 |---| 分隔列。）"
        ),
        "trend_field_valuation": (
            "- **估值觀察**：僅根據「即時市場數據」的數字。本題有多個標的時逐家分列，"
            "每家以「公司名（代號）」標示（公司名取自「即時市場數據」的 name 欄，取不到就只寫代號，"
            "不得自行補寫）；只寫「即時市場數據」中實際出現的標的，未取得行情的標的不得生成數字"
        ),
        "trend_field_consensus": (
            "- **市場共識與門檻**：僅根據「即時市場數據」中的分析師共識數字，"
            "列出當季 EPS／營收共識區間與過去幾季 beat/miss。本題有多個標的時逐家分列，"
            "每家以「公司名（代號）」標示（公司名取自 name 欄，取不到就只寫代號，不得自行補寫）；"
            "只寫「即時市場數據」中實際出現的標的，未取得行情的標的不得生成數字"
        ),
        "trend_field_scenario": (
            "- **情境解讀**：三點子條列「若高於共識上緣」「若落在區間內」「若低於下緣」，"
            "各給一句市場可能如何解讀（條件式描述，不得給機率、不得給加碼／減碼指令）。"
            "本題有多個標的時逐家分列，每家以「公司名（代號）」標示（公司名取自 name 欄，"
            "取不到就只寫代號，不得自行補寫）；只寫「即時市場數據」中實際出現的標的"
        ),
        "trend_field_earnings_call": (
            "- **法說會/財報關注清單**：2-3 點，優先引用檢索資料中與 guidance 相關的內容（附 [來源N]）；"
            "沒有就列通用關注項（營收指引、毛利率指引、資本支出）"
        ),
        "trend_field_recommendation": "- **建議傾向**：給「偏多／中性觀望／偏空」其一並附一句依據",
        "trend_field_trigger": "- **觸發條件**：「轉積極」「轉保守」兩點子條列（條件式描述，非指令）",
        "trend_field_next_event": "- **下一個關鍵事件**：",
        "trend_field_tracking_indicators": "- **建議追蹤指標**：2-3 個",
        "market_partial_note": (
            "（注意：以下即時行情僅為 {shown} 一家，本題其他標的（{others}）未取得即時行情。"
            "凡引用行情數字處必須標明是 {shown}，不得套用到其他標的。）"
        ),
        "adr_premium_header": (
            "ADR 換算（系統依上列價格、匯率與換算比例計算，可直接引用，勿自行重算；"
            "EPS 等值與台股 EPS 的差距主要來自匯率時點不同）"
        ),
        "trend_rules_common": (
            "只輸出上方列出的欄位。未列出的欄位完全不要輸出（不要輸出欄名、不要寫「資料不足」、"
            "不要寫「無」、不要用任何佔位文字）。不得輸出信心百分比；情境解讀不得含機率數字；"
            "不得編造資料中沒有的數字。）"
        ),
        # 跨市場素材的防線。掛在哪一欄由 config.CROSS_MARKET_GUARD 決定，不寫死在
        # common——共用規則區每多一條約束就擠壓所有欄位的本職（專案已兩次實測驗證）。
        "cross_market_guard": (
            "（本欄限制：參考資料屬於問句沒問的那個市場時（例如問美股卻只有台股大盤、"
            "台股個股的資料），不得拿它來填本欄，改寫「參考資料中無美股／台股對應資料」"
            "（依問句的市場擇一）。）"
        ),
        "no_result_market": (
            "雖查無相關財報/新聞資料，以下為即時行情供參考：\n{snapshot}\n"
            "建議追蹤：下次財報/月營收公告、法說會，以及營收與毛利率變化。以上非投資建議。"
        ),
        "disclaimer": "以上非投資建議，僅為資料解讀，投資請自行判斷。",
        "citation_label": "來源",
        "settings_label": "語言 / Language",
        "model_label": "模型 / Model",
        "step_analyze": "解析問題",
        "step_retrieve": "檢索資料庫",
        "step_fetch": "自動抓取財報/新聞（首次約 1-3 分鐘）",
        "step_generate": "生成回答",
        "starters": [
            ("AAPL 最新一季營收？", "AAPL 最新一季營收多少？"),
            ("2330 毛利率？", "台積電（2330）最新一季的毛利率是多少？"),
            ("2330 負面新聞？", "2330 最近有沒有負面新聞？"),
            ("NVDA 最新財報重點？", "NVDA 最新財報重點是什麼？"),
        ],
    },
    "en": {
        "fetch_notice": "🔍 No data for this ticker yet — fetching the latest filings/news now "
        "(first time takes ~1-3 min to embed), retrying retrieval…",
        "connecting": "Connecting to the data service…",
        "connect_failed": (
            "⚠️ Could not reach the data service, queries are unavailable right now.\n\n"
            "Check that the mcp-server service is running (`docker compose up -d mcp-server`) "
            "and that MCP_SERVER_URL / MCP_AUTH_TOKEN are set correctly.\n\nError: {error}"
        ),
        "sources_label": "Sources",
        "report_generated_at": "Generated at",
        "no_result_fetched": (
            "Tried auto-fetching filings and news for \"{company}\" but still found nothing. "
            "It may be a private company (e.g. SpaceX), an incorrect ticker/code, or the source is temporarily unavailable. "
            "If you have relevant documents, import them manually: python -m src.ingest --file <path> --company <ticker>"
        ),
        "ask_market": (
            "\"{name}\" is listed in both Taiwan and the US, and the figures are not directly comparable: "
            "the Taiwan listing ({tw}) reports in TWD on a quarterly basis, while the US listing ({us}) is an ADR "
            "reporting in USD, with a different per-share basis (one ADR represents several ordinary shares).\n\n"
            "Which one would you like? (Please pick a button below.)"
        ),
        "market_btn_tw": "Taiwan {tw}",
        "market_btn_us": "US {us}",
        "market_btn_both": "Both",
        "market_btn_tw_tip": "Reports in TWD, quarterly",
        "market_btn_us_tip": "ADR, reports in USD",
        "market_btn_both_tip": "Shown side by side, never merged into one figure",
        "market_picked": "Selected: {choice}",
        "otc_adr_note": (
            "(Note: {name} also has a US ADR ({us}), but it trades over-the-counter and files no "
            "reports with the SEC, so no financial figures are available for it here. "
            "The following covers the Taiwan listing ({tw}) only.)"
        ),
        "dual_market_warning": (
            "This question covers both Taiwan-listed ({tw}) and US-listed ({us}) tickers. Quote currency, "
            "reporting period and per-share basis all differ across the two markets (and a Taiwan listing and "
            "its US ADR have a share-conversion ratio on top of that), so present them separately with explicit "
            "currency and period; never divide, subtract or convert them into a single comparable number. "
            "Take each currency from the `currency` field in the \"real-time market data\", never from the ticker symbol."
        ),
        "dual_market_warning_adr": (
            "This question covers both the Taiwan listing ({tw}) and its US ADR ({us}). Quote currency and "
            "reporting period differ, and 1 ADR share corresponds to several Taiwan common shares, so the raw "
            "numbers are not directly comparable. When comparing price or EPS across the two, always cite the "
            "TWD-equivalent value and the percentage gap already computed in the \"ADR conversion\" block above; "
            "never compare the raw numbers across currencies, and never recompute it yourself. When the block has "
            "no EPS-equivalent value, state the two sides' EPS separately with their currencies and do not judge "
            "which is higher. Take each currency from the `currency` field in the \"real-time market data\", "
            "never from the ticker symbol."
        ),
        "no_result_plain": (
            "No filings or news related to this question were found in the database. "
            "If your question names a listed company (ticker or code), data will be auto-fetched; "
            "you can also import manually: python -m src.ingest --file <path> --company <ticker>, or rephrase your question."
        ),
        "off_topic": (
            "This question appears to fall outside the scope of financial data. "
            "This assistant only answers questions about listed companies' filings and news.\n\n"
            "Please ask about a specific company's financial performance, operations, or market "
            "activity, such as \"What was TSMC's gross margin last quarter?\" or "
            "\"Any recent news on NVDA?\"."
        ),
        "answer_lang_rule": "- Answer entirely in English",
        "trend_header": (
            "## 📈 Investment Decision Reference\n"
            "(As a buy-side analyst, fill in the fields below. Strict formatting: output each field as its own "
            "markdown list item \"- **Field**: content\" with the field name in bold, content concise; use nested "
            "sub-bullets for multiple points under Known facts / Inference / Triggers; never cram fields onto one line:"
        ),
        "trend_field_conclusion": "- **One-line conclusion**:",
        "trend_field_facts": "- **Known facts**: 1-2 sub-bullets, each must cite [Source N]",
        "trend_field_inference": "- **Inference**: 1-2 sub-bullets, clearly labeled as inference",
        "trend_field_upside": "- **Positives**:",
        "trend_field_risk": "- **Risks**:",
        "trend_field_comparison": (
            "- **Ticker comparison**: output a markdown table whose first column is the comparison item and "
            "each remaining column one ticker (header reads \"Company name (ticker)\", the name taken from the "
            "`name` field of the \"real-time market data\"; ticker alone if unavailable). Choose 3-5 comparison "
            "items yourself based on the question, at least half of which must be qualitative (e.g. market "
            "positioning, growth drivers, sources of risk); the table must not consist solely of market figures, "
            "which would duplicate the \"Valuation check\" field. Follow the table with a 2-3 sentence qualitative "
            "summary. "
            "Every qualitative cell must cite [Source N]; write \"insufficient retrieved data\" when it cannot be "
            "derived, never fill it in from industry general knowledge. Monetary figures (price, target price, "
            "market cap) must state their currency, taken from each ticker's `currency` field in the \"real-time "
            "market data\", never inferred from the ticker symbol; when tickers differ in currency, never divide, "
            "subtract or convert them into a single comparable number. No capital allocation percentages, no "
            "\"if you could pick only one\", no add/trim instructions. "
            "(This field is rendered as a markdown table and is exempt from the single-line bullet format; "
            "the table must include the |---| separator row.)"
        ),
        "trend_field_valuation": (
            "- **Valuation check**: based only on figures from the \"real-time market data\". When the question "
            "covers multiple tickers, list each separately, labeled \"Company name (ticker)\" (name from the "
            "`name` field; ticker alone if unavailable, never invent it); cover only tickers actually present in "
            "the \"real-time market data\" and never generate figures for tickers without a quote"
        ),
        "trend_field_consensus": (
            "- **Consensus & thresholds**: based only on analyst consensus figures from the \"real-time market data\"; "
            "list the current-quarter EPS/revenue consensus range and recent quarters' beat/miss. When the question "
            "covers multiple tickers, list each separately, labeled \"Company name (ticker)\" (name from the `name` "
            "field; ticker alone if unavailable, never invent it); cover only tickers actually present in the "
            "\"real-time market data\" and never generate figures for tickers without a quote"
        ),
        "trend_field_scenario": (
            "- **Scenario read**: three sub-bullets \"if above the consensus high\" / \"if within the range\" / "
            "\"if below the low\", each with one sentence on how the market may interpret it "
            "(conditional description; no probabilities, no add/trim instructions). When the question covers "
            "multiple tickers, list each separately, labeled \"Company name (ticker)\" (name from the `name` field; "
            "ticker alone if unavailable, never invent it); cover only tickers present in the market data"
        ),
        "trend_field_earnings_call": (
            "- **Earnings call watch list**: 2-3 items, preferring guidance-related content from the retrieved "
            "material (with [Source N]); if none, list generic items (revenue guidance, margin guidance, capex)"
        ),
        "trend_field_recommendation": (
            "- **Stance**: give \"Bullish / Neutral-wait / Bearish\" with one supporting reason"
        ),
        "trend_field_trigger": (
            "- **Triggers**: two sub-bullets \"turn positive\" / \"turn cautious\" "
            "(conditional description, not an instruction)"
        ),
        "trend_field_next_event": "- **Next key event**:",
        "trend_field_tracking_indicators": "- **Metrics to watch**: 2-3 items",
        "market_partial_note": (
            "(Note: the market snapshot below covers {shown} only; no live quote was retrieved for the "
            "other tickers in this question ({others}). Whenever you cite a market figure, state that it "
            "is {shown}'s, and never apply it to the other tickers.)"
        ),
        "adr_premium_header": (
            "ADR conversion (computed by the system from the prices/FX/ratio above; cite it "
            "directly, do not recompute; the gap between the EPS equivalent and the Taiwan-listed "
            "EPS is mainly due to differing FX timing)"
        ),
        "trend_rules_common": (
            "Only output the fields listed above. Do not output any field not listed (no field name, no "
            "\"insufficient data\", no \"N/A\", no placeholder text of any kind). Never output a confidence "
            "percentage; the scenario read must not contain probability figures; "
            "never fabricate numbers not in the reference material.)"
        ),
        "cross_market_guard": (
            "(Constraint for this field: when the reference material belongs to a market the question did "
            "not ask about (e.g. the question is about US stocks but only Taiwan index/single-stock "
            "material is available), do not use it to fill this field — write \"no US/Taiwan material in "
            "the reference set\" (pick the one matching the question's market) instead.)"
        ),
        "no_result_market": (
            "No related filings/news were found, but here is the current market snapshot:\n{snapshot}\n"
            "Suggested watch items: next earnings/monthly revenue release, earnings call, and revenue/margin trends. "
            "This is not investment advice."
        ),
        "disclaimer": "This is not investment advice — data interpretation only. Invest at your own discretion.",
        "citation_label": "Source ",
        "settings_label": "語言 / Language",
        "model_label": "模型 / Model",
        "step_analyze": "Analyzing question",
        "step_retrieve": "Retrieving from database",
        "step_fetch": "Auto-fetching filings/news (first time ~1-3 min)",
        "step_generate": "Generating answer",
        "starters": [
            ("AAPL latest quarter revenue?", "What was AAPL's revenue in the latest quarter?"),
            ("2330 gross margin?", "What is TSMC (2330)'s gross margin in the latest quarter?"),
            ("2330 negative news?", "Any negative news about 2330 recently?"),
            ("NVDA latest earnings highlights?", "What are the highlights of NVDA's latest earnings report?"),
        ],
    },
}


def detect_lang(languages: str | None) -> str:
    """從瀏覽器 Accept-Language 字串判斷 zh/en，例："zh-TW,zh;q=0.9" -> "zh"。"""
    return "zh" if (languages or "").lower().startswith("zh") else "en"


def detect_question_lang(text: str) -> str | None:
    """從提問文字判斷語言：含 CJK -> zh，含英文字母 -> en，判斷不了（如純代號）回 None。"""
    if re.search(r"[一-鿿]", text):
        return "zh"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return None


def t(lang: str, key: str, **fmt) -> str:
    table = STRINGS.get(lang, STRINGS["zh"])
    s = table[key]
    return s.format(**fmt) if fmt else s


if __name__ == "__main__":
    assert detect_lang("zh-TW,zh;q=0.9") == "zh"
    assert detect_lang("en-US") == "en"
    assert detect_lang(None) == "en"
    assert detect_question_lang("NVDA 最新財報重點是什麼？") == "zh"
    assert detect_question_lang("What was AAPL's revenue?") == "en"
    assert detect_question_lang("2330？") is None
    assert "AAPL" in t("zh", "no_result_fetched", company="AAPL")
    assert "AAPL" in t("en", "no_result_fetched", company="AAPL")
    assert set(STRINGS["zh"].keys()) == set(STRINGS["en"].keys())
    print("i18n self-check OK")
