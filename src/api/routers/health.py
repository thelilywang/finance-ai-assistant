from fastapi import APIRouter, HTTPException, Request

from ..schemas import Health

router = APIRouter()


@router.get("/health")
def health() -> Health:
    return Health(status="ok")


@router.get("/ready")
def ready(request: Request) -> Health:
    if getattr(request.app.state, "graph", None) is None:
        raise HTTPException(503, "graph not ready")
    return Health(status="ready")
