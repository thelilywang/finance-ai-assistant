"""HTTP API 進入點。

用法：
    python -m src.api.main

並行上限：本機 Ollama 一次只能跑一題，同時進來的請求會在 Ollama 排隊，
多開 worker 只會搶同一張 GPU，所以固定單一 worker。
"""
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import tracing
from ..graph import build_graph
from ..logging_setup import log_duration, setup_logging
from .routers import ask, health, jobs
from .schemas import ErrorBody, ErrorResponse
from .settings import settings

log = logging.getLogger("api")
_IN_DOCKER = Path("/.dockerenv").exists()
# compose healthcheck 每 30 秒打一次這兩個路徑，記進 access log 會洗版
_QUIET_PATHS = {"/health", "/ready"}


def _check_secret() -> None:
    secret = settings.API_JWT_SECRET
    if not secret:
        # 只擋容器內——那才是 port 可能被 expose 出去的情境，本機開發照舊放行
        if _IN_DOCKER:
            raise SystemExit("API_JWT_SECRET 未設定，容器內拒絕無驗證啟動。請在 .env 設定後重啟。")
        log.warning("API_JWT_SECRET 未設定，未啟用身分驗證（僅適合本機開發）")
    elif len(secret.encode()) < 32:
        raise SystemExit("API_JWT_SECRET 至少 32 bytes（HS256 的 secret 太短容易被暴力破解）。")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("api")
    _check_secret()
    app.state.graph = await build_graph()
    try:
        yield
    finally:
        tracing.flush()


def _error(status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message))
    return JSONResponse(body.model_dump(), status_code=status, headers=headers)


async def _http_error(_: Request, exc: StarletteHTTPException):
    return _error(exc.status_code, f"http_{exc.status_code}", str(exc.detail),
                  getattr(exc, "headers", None))


async def _validation_error(_: Request, exc: RequestValidationError):
    msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
    return _error(422, "validation_error", msg)


async def _request_context(request: Request, call_next):
    """帶入或產生 X-Request-ID、回寫到 response header，並記一筆 access log。"""
    # client 帶的值不可信，截斷避免超長字串寫進 log
    request_id = request.headers.get("X-Request-ID", "")[:64] or uuid.uuid4().hex
    started = time.monotonic()
    status = 500  # 未處理的例外由下方 except 回 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        log.exception("unhandled error", extra={"fields": {"request_id": request_id}})
        # 在這裡回 500，而不是交給外層的 ServerErrorMiddleware：
        # 才能帶 X-Request-ID 並用統一錯誤格式；例外細節只進 log
        return _error(500, "internal_error", "internal error", {"X-Request-ID": request_id})
    finally:
        if request.url.path not in _QUIET_PATHS:
            # SSE（/api/v1/ask）的 elapsed_ms 量到 response 開始送出（TTFB），不含整段串流
            log_duration(log, "request", started, request_id=request_id,
                         method=request.method, path=request.url.path, status=status)


def create_app() -> FastAPI:
    app = FastAPI(title="Finance AI Assistant API", lifespan=lifespan)
    # 只有設定了來源才啟用 CORS；空清單＝不允許跨來源
    if settings.API_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.API_CORS_ORIGINS,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )
    # 後註冊的在最外層：preflight 由 CORS 直接回應，也要帶 X-Request-ID 並記 log
    app.middleware("http")(_request_context)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.include_router(health.router)
    app.include_router(ask.router)
    app.include_router(jobs.router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    # 容器內要讓其他 service 連得到，必須綁全介面；無驗證的情況已在 lifespan 擋掉
    host = "0.0.0.0" if _IN_DOCKER else settings.API_HOST  # noqa: S104
    uvicorn.run(app, host=host, port=settings.API_PORT, access_log=False)
