"""HTTP API：驗證、統一錯誤格式、SSE 事件順序。不連 Ollama／DB／MCP。"""
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from src.api import main
from src.api.deps import get_graph
from src.api.settings import settings

SECRET = "x" * 32


class FakeGraph:
    def __init__(self, fail: bool = False):
        self.fail = fail

    async def astream(self, state, **kwargs):
        yield "updates", {"extract_filters": {}}
        yield "messages", (AIMessageChunk(content="你好"), {"langgraph_node": "generate"})
        if self.fail:
            raise RuntimeError("boom")
        yield "values", {**state, "answer": "你好", "retrieved": [{"source": "a.pdf"}] * 2,
                         "ask_market": False, "peer_company": None}


@pytest.fixture
def client(monkeypatch):
    async def fake_build():
        return FakeGraph()

    monkeypatch.setattr(main, "build_graph", fake_build)
    monkeypatch.setattr(settings, "API_JWT_SECRET", SECRET)
    with TestClient(main.create_app()) as c:
        yield c


def _token(secret=SECRET, exp_in=3600):
    return jwt.encode({"sub": "alice", "exp": int(time.time()) + exp_in}, secret, "HS256")


def _ask(client, token=None, **body):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/api/v1/ask", json={"question": "台積電營收", **body}, headers=headers)


def test_health_needs_no_token(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}


def test_ready_503_when_graph_missing(client):
    client.app.state.graph = None
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "http_503"


@pytest.mark.parametrize("token", [None, _token("y" * 32), _token(exp_in=-10)])
def test_bad_token_401(client, token):
    r = _ask(client, token)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.json()["error"]["code"] == "http_401"


def test_valid_token_200(client):
    assert _ask(client, _token()).status_code == 200


def test_empty_question_422(client):
    r = client.post("/api/v1/ask", json={"question": ""}, headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error" and "question" in err["message"]


def test_sse_order_and_done(client):
    text = _ask(client, _token()).text
    assert text.index("event: step") < text.index("event: token") < text.index("event: done")
    assert 'data: {"node": "retrieve"}' in text
    assert '"answer": "你好"' in text and '"sources": ["a.pdf"]' in text


def test_graph_error_becomes_error_event(client):
    client.app.dependency_overrides[get_graph] = lambda: FakeGraph(fail=True)
    text = _ask(client, _token()).text
    assert "event: error" in text and "boom" not in text


def test_empty_secret_disables_auth(client, monkeypatch):
    monkeypatch.setattr(settings, "API_JWT_SECRET", "")
    assert _ask(client).status_code == 200
