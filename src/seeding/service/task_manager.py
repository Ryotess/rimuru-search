import asyncio
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from inspect import isawaitable
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.cache.client import get_redis
from src.cache.config import cache_settings
from src.database import SessionLocal
from src.logging_config import logger
from src.seeding.schemas import OperationType, TaskStatus
from src.seeding.service.retry import is_retryable

LOCK_TTL = 86400  # 24h

# Lua script: only DEL if lock value matches (atomic owner-check + release)
_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


@dataclass
class TaskState:
    task_id: UUID
    operation: OperationType
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    progress: str | None = None
    total_rows_processed: int = 0
    chunks_completed: int = 0
    error: str | None = None


class SeedTaskManager:
    def __init__(self) -> None:
        self._state: TaskState | None = None
        self._running_async_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Redis lock helpers
    # ------------------------------------------------------------------

    def _lock_key(self) -> str:
        return f"{cache_settings.key_prefix}:seeding:lock"

    def _lock_value(self, task_id: UUID) -> bytes:
        return str(task_id).encode()

    async def _acquire_lock(self, task_id: UUID) -> bool:
        redis = get_redis()
        if redis is None:
            logger.warning("Redis not available; proceeding without distributed lock")
            return True
        acquired = await redis.set(
            self._lock_key(),
            self._lock_value(task_id),
            nx=True,
            ex=LOCK_TTL,
        )
        return bool(acquired)

    async def _release_lock(self, task_id: UUID) -> None:
        redis = get_redis()
        if redis is None:
            return
        release_result = redis.eval(
            _RELEASE_LOCK_SCRIPT,
            1,
            self._lock_key(),
            self._lock_value(task_id),
        )
        if isawaitable(release_result):
            await release_result

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _insert_task(self, task_id: UUID, operation: OperationType) -> None:
        async with SessionLocal() as db:
            await db.execute(
                text(
                    "INSERT INTO seeding_tasks (id, operation, status) "
                    "VALUES (:id, :operation, 'RUNNING')"
                ),
                {"id": task_id, "operation": operation.value},
            )
            await db.commit()

    async def _update_task(
        self,
        task_id: UUID,
        status: TaskStatus,
        *,
        chunks_completed: int | None = None,
        total_rows_processed: int | None = None,
        progress: str | None = None,
        completed_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        set_parts = ["status = :status"]
        params: dict[str, Any] = {"task_id": task_id, "status": status.value}

        if chunks_completed is not None:
            set_parts.append("chunks_completed = :chunks_completed")
            params["chunks_completed"] = chunks_completed
        if total_rows_processed is not None:
            set_parts.append("total_rows_processed = :total_rows_processed")
            params["total_rows_processed"] = total_rows_processed
        if progress is not None:
            set_parts.append("progress = :progress")
            params["progress"] = progress
        if completed_at is not None:
            set_parts.append("completed_at = :completed_at")
            params["completed_at"] = completed_at
        if error is not None:
            set_parts.append("error = :error")
            params["error"] = error

        async with SessionLocal() as db:
            await db.execute(
                text(
                    f"UPDATE seeding_tasks SET {', '.join(set_parts)} WHERE id = :task_id"  # noqa: S608  # Column fragments come only from the fixed names above.
                ),
                params,
            )
            await db.commit()

    async def _find_interrupted_task(
        self, operation: OperationType
    ) -> tuple[UUID, int, int] | None:
        async with SessionLocal() as db:
            result = await db.execute(
                text(
                    "SELECT id, chunks_completed, total_rows_processed "
                    "FROM seeding_tasks "
                    "WHERE status = 'INTERRUPTED' AND operation = :operation "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"operation": operation.value},
            )
            row = result.fetchone()
        if row is None:
            return None
        return (row.id, row.chunks_completed, row.total_rows_processed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit(
        self, operation: OperationType, *, force: bool = False
    ) -> TaskState:
        if self._state is not None and self._state.status == TaskStatus.RUNNING:
            raise RuntimeError(f"Task {self._state.task_id} is already in progress")

        interrupted = await self._find_interrupted_task(operation)

        if interrupted is not None and not force:
            task_id, start_chunk, total_rows = interrupted
            if not await self._acquire_lock(task_id):
                raise RuntimeError("Another instance is already running a seeding task")
            await self._update_task(task_id, TaskStatus.RUNNING)
            state = TaskState(
                task_id=task_id,
                operation=operation,
                status=TaskStatus.RUNNING,
                chunks_completed=start_chunk,
                total_rows_processed=total_rows,
            )
            self._state = state
            self._running_async_task = asyncio.create_task(
                self._run(state, start_chunk=start_chunk)
            )
            return state

        if interrupted is not None and force:
            await self._update_task(
                interrupted[0],
                TaskStatus.CANCELLED,
                completed_at=datetime.now(UTC),
            )

        task_id = uuid.uuid4()

        if not await self._acquire_lock(task_id):
            raise RuntimeError("Another instance is already running a seeding task")

        try:
            await self._insert_task(task_id, operation)
        except Exception:
            await self._release_lock(task_id)
            raise

        state = TaskState(
            task_id=task_id, operation=operation, status=TaskStatus.RUNNING
        )
        self._state = state
        self._running_async_task = asyncio.create_task(self._run(state))
        return state

    async def get_task(self, task_id: UUID) -> TaskState | None:
        if self._state and self._state.task_id == task_id:
            return self._state
        async with SessionLocal() as db:
            result = await db.execute(
                text("SELECT * FROM seeding_tasks WHERE id = :id"), {"id": task_id}
            )
            row = result.fetchone()
        if row is None:
            return None
        return TaskState(
            task_id=row.id,
            operation=OperationType(row.operation),
            status=TaskStatus(row.status),
            created_at=row.created_at,
            completed_at=row.completed_at,
            progress=row.progress,
            total_rows_processed=row.total_rows_processed,
            chunks_completed=row.chunks_completed,
            error=row.error,
        )

    async def list_tasks(self) -> list[TaskState]:
        async with SessionLocal() as db:
            result = await db.execute(
                text("SELECT * FROM seeding_tasks ORDER BY created_at DESC LIMIT 20")
            )
            rows = result.fetchall()
        return [
            TaskState(
                task_id=row.id,
                operation=OperationType(row.operation),
                status=TaskStatus(row.status),
                created_at=row.created_at,
                completed_at=row.completed_at,
                progress=row.progress,
                total_rows_processed=row.total_rows_processed,
                chunks_completed=row.chunks_completed,
                error=row.error,
            )
            for row in rows
        ]

    async def cancel_running(self) -> None:
        """Called on graceful pod shutdown — marks task as INTERRUPTED so it can be resumed."""
        if self._state is None or self._running_async_task is None:
            return
        state = self._state
        state.status = TaskStatus.INTERRUPTED
        state.completed_at = datetime.now(UTC)
        await self._update_task(
            state.task_id,
            TaskStatus.INTERRUPTED,
            chunks_completed=state.chunks_completed,
            total_rows_processed=state.total_rows_processed,
            completed_at=state.completed_at,
        )
        await self._release_lock(state.task_id)
        self._running_async_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await self._running_async_task
        self._running_async_task = None

    # ------------------------------------------------------------------
    # Internal run logic
    # ------------------------------------------------------------------

    async def _run(self, state: TaskState, start_chunk: int = 0) -> None:
        try:
            if state.operation == OperationType.SEED:
                await self._run_seed(state, start_chunk=start_chunk)
            elif state.operation == OperationType.RESEED:
                await self._run_reseed(state, start_chunk=start_chunk)

            state.status = TaskStatus.COMPLETED
            state.completed_at = datetime.now(UTC)
            await self._update_task(
                state.task_id,
                TaskStatus.COMPLETED,
                completed_at=state.completed_at,
                chunks_completed=state.chunks_completed,
                total_rows_processed=state.total_rows_processed,
            )
        except asyncio.CancelledError:
            # cancel_running() already wrote INTERRUPTED to DB
            logger.info("Task {} asyncio task cancelled", state.task_id)
        except Exception as exc:
            if is_retryable(exc):
                final_status = TaskStatus.INTERRUPTED
                logger.warning(
                    "Task {} interrupted (retryable): {}", state.task_id, exc
                )
            else:
                final_status = TaskStatus.FAILED
                logger.error("Task {} failed: {}", state.task_id, exc)

            state.status = final_status
            state.error = str(exc)
            state.completed_at = datetime.now(UTC)
            if final_status == TaskStatus.INTERRUPTED:
                await self._update_task(
                    state.task_id,
                    final_status,
                    completed_at=state.completed_at,
                    error=state.error,
                    chunks_completed=state.chunks_completed,
                    total_rows_processed=state.total_rows_processed,
                )
            else:
                await self._update_task(
                    state.task_id,
                    final_status,
                    completed_at=state.completed_at,
                    error=state.error,
                )
        finally:
            await self._release_lock(state.task_id)
            self._running_async_task = None

    def _make_chunk_callback(self, state: TaskState):
        async def on_chunk_done(chunk_idx: int, inserted: int) -> None:
            state.chunks_completed = chunk_idx
            state.total_rows_processed += inserted
            state.progress = (
                f"Processed chunk {state.chunks_completed}, "
                f"total rows: {state.total_rows_processed}"
            )
            logger.info("Task {}: {}", state.task_id, state.progress)
            await self._update_task(
                state.task_id,
                TaskStatus.RUNNING,
                chunks_completed=state.chunks_completed,
                total_rows_processed=state.total_rows_processed,
                progress=state.progress,
            )

        return on_chunk_done

    async def _run_seed(self, state: TaskState, start_chunk: int = 0) -> None:
        from src.seeding.service.seeder import seed

        state.progress = "Seeding via source API"
        await seed(
            on_chunk_done=self._make_chunk_callback(state),
            start_chunk=start_chunk,
        )

    async def _run_reseed(self, state: TaskState, start_chunk: int = 0) -> None:
        from src.seeding.service.reseed import reseed

        def on_step(step_desc: str) -> None:
            state.progress = step_desc
            logger.info("Task {}: {}", state.task_id, state.progress)

        await reseed(
            on_step=on_step,
            on_chunk_done=self._make_chunk_callback(state),
            start_chunk=start_chunk,
        )


seed_task_manager = SeedTaskManager()
