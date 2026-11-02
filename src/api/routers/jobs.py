import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ..deps import get_current_user, get_graph
from ..schemas import AnswerResult, AskRequest, JobCreated, JobStatus
from ..service import run_graph

log = logging.getLogger("api")
router = APIRouter(prefix="/api/v1")

# ponytail: job 存在記憶體 dict，重啟就消失、只支援單一 process；要持久化或多 worker 時改用 Redis 加 arq。
_jobs: dict[str, dict] = {}  # job_id -> {"user": str, "status": JobStatus}


async def _run_job(job_id: str, graph, req: AskRequest, user: str) -> None:
    job = _jobs[job_id]["status"]
    session_id = f"api-{job_id[:8]}"
    job.status = "running"
    try:
        async for event, data in run_graph(graph, req, user, session_id):
            if event == "done":  # 非同步 job 不推 step／token，只留最終結果
                job.result = AnswerResult(**data)
        job.status = "done"
    except Exception:
        # 細節留在 log，不外洩給 client
        log.exception("job 失敗", extra={"fields": {"job_id": job_id, "session_id": session_id, "user": user}})
        job.status, job.error = "error", "internal error"


@router.post("/jobs", status_code=202, response_model=JobCreated)
async def create_job(
    req: AskRequest,
    tasks: BackgroundTasks,
    graph: Annotated[object, Depends(get_graph)],
    user: Annotated[str, Depends(get_current_user)],
):
    job_id = uuid4().hex
    _jobs[job_id] = {"user": user, "status": JobStatus(job_id=job_id, status="pending")}
    tasks.add_task(_run_job, job_id, graph, req, user)
    return JobCreated(job_id=job_id)


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str, user: Annotated[str, Depends(get_current_user)]):
    job = _jobs.get(job_id)
    # 非建立者也回 404，不洩漏別人 job 的存在
    if job is None or job["user"] != user:
        raise HTTPException(404, "job not found")
    return job["status"]
