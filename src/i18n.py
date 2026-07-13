"""集中管理雙語字串，不引入 i18n 套件。"""
import re

STRINGS = {
    "zh": {
        "fetch_notice": "🔍 資料庫沒有這檔股票的資料，已自動抓取最新財報/新聞（首次約需 1-3 分鐘 embedding），正在重新檢索…",
        "sources_label": "參考來源",
        "report_generated_at": "產生時間",
        "no_result_fetched": (
            "已嘗試自動抓取「{company}」的財報與新聞，但仍查無資料。"
            "可能是未上市公司（如 SpaceX）、代號/ticker 有誤，或該來源暫時無法取得。"
            "若你有相關文件，可手動匯入：python -m src.ingest --file <路徑> --company <代號>"
        ),
        "no_result_plain": (
            "資料庫中找不到與這個問題相關的財報或新聞內容。"
            "問題若有指名上市公司（代號或 ticker）會自動抓取資料，"
            "也可以手動匯入：python -m src.ingest --file <路徑> --company <代號>，或換個問法。"
        ),
        "answer_lang_rule": "- 全文以繁體中文回答",
        "trend_section": (
            "## 📈 投資趨勢觀點\n"
            "（以資深投資經理人的角色，僅根據上述參考資料，用 2-4 句話給出該個股近期的投資/操作趨勢觀點：\n"
            "趨勢方向、值得關注的點、風險。不得引入資料以外的資訊。）"
        ),
        "disclaimer": "以上非投資建議，僅為資料解讀，投資請自行判斷。",
        "settings_label": "語言 / Language",
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
        "sources_label": "Sources",
        "report_generated_at": "Generated at",
        "no_result_fetched": (
            "Tried auto-fetching filings and news for \"{company}\" but still found nothing. "
            "It may be a private company (e.g. SpaceX), an incorrect ticker/code, or the source is temporarily unavailable. "
            "If you have relevant documents, import them manually: python -m src.ingest --file <path> --company <ticker>"
        ),
        "no_result_plain": (
            "No filings or news related to this question were found in the database. "
            "If your question names a listed company (ticker or code), data will be auto-fetched; "
            "you can also import manually: python -m src.ingest --file <path> --company <ticker>, or rephrase your question."
        ),
        "answer_lang_rule": "- Answer entirely in English",
        "trend_section": (
            "## 📈 Investment Trend View\n"
            "(As a senior investment manager, using only the reference material above, give a 2-4 sentence "
            "view on this stock's recent investment/trading trend: direction, points worth watching, and risks. "
            "Do not introduce information outside the reference material.)"
        ),
        "disclaimer": "This is not investment advice — data interpretation only. Invest at your own discretion.",
        "settings_label": "語言 / Language",
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
