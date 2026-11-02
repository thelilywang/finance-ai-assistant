"""HTTP API：驗證、統一錯誤格式、SSE 事件順序。不連 Ollama／DB／MCP。"""
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from src.api import main
from src.api.deps import get_graph
from src.api.routers import jobs
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


def _token(secret=SECRET, exp_in=3600, sub="alice"):
    return jwt.encode({"sub": sub, "exp": int(time.time()) + exp_in}, secret, "HS256")


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
    r = _ask(client, _token())
    assert (r.headers["cache-control"], r.headers["x-accel-buffering"]) == ("no-cache", "no")
    text = r.text
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


def test_request_id_generated_and_echoed(client):
    assert len(client.get("/health").headers["X-Request-ID"]) == 32
    r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"
    r = client.get("/health", headers={"X-Request-ID": "x" * 500})
    assert r.headers["X-Request-ID"] == "x" * 64


def test_access_log_for_business_endpoint_not_health(client, caplog):
    with caplog.at_level("INFO", logger="api"):
        client.get("/health")
        assert not [r for r in caplog.records if r.message == "request"]
        r = _ask(client, _token())
    (rec,) = [x for x in caplog.records if x.message == "request"]
    f = rec.fields
    assert f["request_id"] == r.headers["X-Request-ID"]
    assert (f["method"], f["path"], f["status"]) == ("POST", "/api/v1/ask", 200)
    assert isinstance(f["elapsed_ms"], int)


def test_cors_enabled_only_when_configured(client, monkeypatch):
    origin = "http://localhost:3000"
    assert "access-control-allow-origin" not in client.get("/health", headers={"Origin": origin}).headers

    monkeypatch.setattr(settings, "API_CORS_ORIGINS", [origin])
    with TestClient(main.create_app()) as c:
        r = c.options("/api/v1/ask", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization"})
        assert r.headers["access-control-allow-origin"] == origin
        assert "X-Request-ID" in r.headers
        r = c.get("/health", headers={"Origin": origin})
        assert r.headers["access-control-allow-origin"] == origin
        assert "X-Request-ID" in r.headers["access-control-expose-headers"]


def test_unhandled_error_logged_as_500(monkeypatch, caplog):
    async def fake_build():
        return FakeGraph()

    monkeypatch.setattr(main, "build_graph", fake_build)
    app = main.create_app()

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as c, caplog.at_level("INFO", logger="api"):
        r = c.get("/boom", headers={"X-Request-ID": "err-1"})
    assert r.status_code == 500 and r.headers["X-Request-ID"] == "err-1"
    assert r.json()["error"] == {"code": "internal_error", "message": "internal error"} and "boom" not in r.text
    (err,) = [r for r in caplog.records if r.message == "unhandled error"]
    assert err.exc_info and err.fields == {"request_id": "err-1"}
    (rec,) = [r for r in caplog.records if r.message == "request"]
    assert (rec.fields["request_id"], rec.fields["status"]) == ("err-1", 500)


def _auth(token=None):
    return {"Authorization": f"Bearer {token or _token()}"}


def _create_job(client, token=None):
    return client.post("/api/v1/jobs", json={"question": "台積電營收"}, headers=_auth(token))


def test_job_done(client):
    r = _create_job(client)
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    body = client.get(f"/api/v1/jobs/{job_id}", headers=_auth()).json()
    assert body["status"] == "done"
    assert body["result"]["answer"] == "你好" and body["result"]["sources"] == ["a.pdf"]


def test_job_not_found_404(client):
    r = client.get("/api/v1/jobs/nope", headers=_auth())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "http_404"


def test_job_of_other_user_404(client):
    job_id = _create_job(client).json()["job_id"]
    r = client.get(f"/api/v1/jobs/{job_id}", headers=_auth(_token(sub="bob")))
    assert r.status_code == 404


def test_job_graph_error(client):
    client.app.dependency_overrides[get_graph] = lambda: FakeGraph(fail=True)
    job_id = _create_job(client).json()["job_id"]
    r = client.get(f"/api/v1/jobs/{job_id}", headers=_auth())
    assert r.json()["status"] == "error" and r.json()["error"] == "internal error"
    assert "boom" not in r.text


def test_job_create_needs_token(client):
    r = client.post("/api/v1/jobs", json={"question": "x"})
    assert r.status_code == 401


def test_job_expired_pruned_on_create(client, monkeypatch):
    old = _create_job(client).json()["job_id"]
    monkeypatch.setattr(jobs, "_JOB_TTL_S", -1)  # 讓已完成的 job 視為過期
    new = _create_job(client).json()["job_id"]
    assert client.get(f"/api/v1/jobs/{old}", headers=_auth()).status_code == 404
    r = client.get(f"/api/v1/jobs/{new}", headers=_auth())
    assert r.status_code == 200 and r.json()["status"] == "done"
