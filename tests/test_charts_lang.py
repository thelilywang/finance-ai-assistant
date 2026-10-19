"""圖表標題/圖例/標註依 lang 切換；不連 yfinance，monkeypatch 假 Ticker。"""
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src import charts


@pytest.fixture
def fake_yf(monkeypatch):
    idx = pd.date_range("2026-04-01", periods=5, freq="D")
    hist = pd.DataFrame({"Close": [1.0, 2.0, 3.0, 4.0, 5.0]}, index=idx)
    eds = pd.DataFrame({"EPS Estimate": [1.0, 2.0], "Reported EPS": [1.1, 1.9]},
                       index=pd.to_datetime(["2026-01-01", "2026-04-01"]))
    tk = MagicMock(history=MagicMock(return_value=hist), earnings_dates=eds,
                   calendar={"Earnings Date": [idx[-1].date()]})
    monkeypatch.setitem(sys.modules, "yfinance", MagicMock(Ticker=MagicMock(return_value=tk)))


def test_price_chart_lang(fake_yf):
    zh, en = charts.price_chart("nvda"), charts.price_chart("nvda", "en")
    assert zh.layout.title.text == "NVDA 股價走勢（6 個月）"
    assert zh.layout.annotations[0].text == "下次財報"
    assert en.layout.title.text == "NVDA Price (6 months)"
    assert en.layout.annotations[0].text == "Next earnings"
    assert "Close" in en.data[0].hovertemplate and "%{y:.2f}" in en.data[0].hovertemplate


def test_eps_chart_lang(fake_yf):
    zh, en = charts.eps_chart("nvda"), charts.eps_chart("nvda", "en")
    assert zh.data[0].name == "預估 EPS"
    assert en.layout.title.text.startswith("NVDA EPS: Estimate vs Actual")
    assert [d.name for d in en.data] == ["Estimate", "Actual (green beat, red miss)"]
