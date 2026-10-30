"""HTTP API 進入點。

用法：
    python -m src.api.main

並行上限：本機 Ollama 一次只能跑一題，同時進來的請求會在 Ollama 排隊，
多開 worker 只會搶同一張 GPU，所以固定單一 worker。
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import tracing
from ..graph import build_graph
from ..logging_setup import setup_logging
from .routers import ask, health
from .schemas import ErrorBody, ErrorResponse
from .settings import settings

log = logging.getLogger("api")
_IN_DOCKER = Path("/.dockerenv").exists()


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


def create_app() -> FastAPI:
    app = FastAPI(title="Finance AI Assistant API", lifespan=lifespan)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.include_router(health.router)
    app.include_router(ask.router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    # 容器內要讓其他 service 連得到，必須綁全介面；無驗證的情況已在 lifespan 擋掉
    host = "0.0.0.0" if _IN_DOCKER else settings.API_HOST  # noqa: S104
    uvicorn.run(app, host=host, port=settings.API_PORT)
