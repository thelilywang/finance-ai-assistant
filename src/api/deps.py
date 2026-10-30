"""FastAPI 依賴：取 graph、驗 JWT。"""
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .settings import settings

_bearer = HTTPBearer(auto_error=False)  # 預設缺 header 回 403；改自己丟 401


def get_graph(request: Request):
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        raise HTTPException(503, "graph not ready")
    return graph


def get_current_user(
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """驗簽章與 exp，回傳 sub 作為 user_id。secret 為空（本機開發）時不驗證。"""
    if not settings.API_JWT_SECRET:
        return "local"
    unauthorized = HTTPException(
        401, "invalid or missing token", headers={"WWW-Authenticate": "Bearer"}
    )
    if cred is None:
        raise unauthorized
    try:
        claims = jwt.decode(
            cred.credentials, settings.API_JWT_SECRET,
            algorithms=[settings.API_JWT_ALG], options={"require": ["exp", "sub"]},
        )
    except jwt.InvalidTokenError:
        raise unauthorized from None
    return str(claims["sub"])
