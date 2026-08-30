from uuid import UUID

from fastapi import APIRouter, HTTPException

from src.seeding.schemas import (
    SeedRequest,
    TaskListResponse,
    TaskResponse,
)
from src.seeding.service import TaskState, seed_task_manager

router = APIRouter(prefix="/v1/seeding", tags=["seeding"])


def _state_to_response(state: TaskState) -> TaskResponse:
    return TaskResponse(
        task_id=state.task_id,
        operation=state.operation,
        status=state.status,
        created_at=state.created_at,
        completed_at=state.completed_at,
        progress=state.progress,
        total_rows_processed=state.total_rows_processed,
        chunks_completed=state.chunks_completed,
        error=state.error,
    )


@router.post("/tasks", response_model=TaskResponse)
async def create_seed_task(payload: SeedRequest) -> TaskResponse:
    try:
        state = await seed_task_manager.submit(
            operation=payload.operation, force=payload.force
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _state_to_response(state)


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks() -> TaskListResponse:
    tasks = await seed_task_manager.list_tasks()
    return TaskListResponse(tasks=[_state_to_response(t) for t in tasks])


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID) -> TaskResponse:
    state = await seed_task_manager.get_task(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _state_to_response(state)
