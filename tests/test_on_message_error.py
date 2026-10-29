"""on_message 在串流途中例外時的收尾行為。

重試只涵蓋連線被拒，其餘例外必須在 on_message 內收尾：關閉 step、
顯示 answer_failed（保留已串出的部分內容），且不寫入 history。
"""
import asyncio
from types import SimpleNamespace

import httpx

from src import app
from src.i18n import t


class _Session:
    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


def _setup(monkeypatch, stream):
    sent, closed = [], []
    session = _Session({"graph": object(), "history": [], "lang_setting": "zh",
                        "browser_lang": "zh", "model": None})

    class FakeMessage:
        def __init__(self, content=""):
            self.content = content

        async def stream_token(self, token):
            self.content += token

        async def send(self):
            sent.append(self)

    class FakeTracker:
        def __init__(self, *a, **k):
            pass

        async def start(self):
            pass

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(app.cl, "user_session", session)
    monkeypatch.setattr(app.cl, "Message", FakeMessage)
    monkeypatch.setattr(app, "_StepTracker", FakeTracker)
    monkeypatch.setattr(app, "_stream_answer", stream)
    return session, sent, closed


def _run():
    asyncio.run(app.on_message(SimpleNamespace(content="2330 營收？")))


def test_stream_failure_sends_notice_without_history(monkeypatch):
    async def stream(state, msg, tracker):
        raise httpx.ConnectError("refused")

    session, sent, closed = _setup(monkeypatch, stream)
    _run()
    assert [m.content for m in sent] == [t("zh", "answer_failed")]
    assert session.data["history"] == []
    assert closed == [True]


def test_stream_failure_keeps_partial_content(monkeypatch):
    # 已串出的部分內容要保留，錯誤提示接在後面
    async def stream(state, msg, tracker):
        await msg.stream_token("部分內容")
        raise httpx.ConnectError("refused")

    session, sent, closed = _setup(monkeypatch, stream)
    _run()
    assert sent[0].content == "部分內容\n\n" + t("zh", "answer_failed")
    assert session.data["history"] == []
