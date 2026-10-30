import json
import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..deps import get_current_user, get_graph
from ..schemas import AskRequest
from ..service import run_graph

log = logging.getLogger("api")
router = APIRouter(prefix="/api/v1")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/ask")
async def ask(
    req: AskRequest,
    graph: Annotated[object, Depends(get_graph)],
    user: Annotated[str, Depends(get_current_user)],
):
    session_id = f"api-{uuid4().hex[:8]}"

    async def events():
        try:
            async for event, data in run_graph(graph, req, user, session_id):
                yield _sse(event, data)
        except Exception:
            # 串流開始後 status code 已送出，只能用 error 事件告知；細節留在 log，不外洩
            log.exception("ask 失敗", extra={"fields": {"session_id": session_id, "user": user}})
            yield _sse("error", {"message": "internal error"})

    return StreamingResponse(events(), media_type="text/event-stream")
