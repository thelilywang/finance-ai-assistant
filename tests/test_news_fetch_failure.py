"""新聞來源全數失敗時，FetchResult 的 detail 不能寫「更新完成」。

LLM 只讀得到 detail（fetch_market_overview／fetch_company_data 直接回傳），
ok=False 卻寫「完成」會讓模型以為已抓到新資料。
"""
from types import SimpleNamespace

import src.update as update


def test_market_news_all_sources_down_reports_failure(monkeypatch):
    monkeypatch.setattr(update.requests, "get",
                        lambda *a, **k: SimpleNamespace(status_code=500, text=""))
    result = update.fetch_market_news(3)
    assert not result.ok
    assert "失敗" in result.detail and "完成" not in result.detail, result.detail
