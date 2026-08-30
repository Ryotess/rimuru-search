from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


class OperationType(StrEnum):
    SEED = "SEED"
    RESEED = "RESEED"


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


class SeedRequest(BaseModel):
    operation: OperationType
    force: bool = False


class TaskResponse(BaseModel):
    task_id: UUID
    operation: OperationType
    status: TaskStatus
    created_at: datetime
    completed_at: datetime | None = None
    progress: str | None = None
    total_rows_processed: int = 0
    chunks_completed: int = 0
    error: str | None = None


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
