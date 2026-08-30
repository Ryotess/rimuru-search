"""Tests for SeedTaskManager._run() error-handling behaviour."""

import uuid
from unittest.mock import AsyncMock

import litellm

from src.seeding.schemas import OperationType, TaskStatus
from src.seeding.service.task_manager import SeedTaskManager, TaskState


def _make_state(
    operation: OperationType = OperationType.RESEED,
    chunks_completed: int = 0,
    total_rows_processed: int = 0,
) -> TaskState:
    return TaskState(
        task_id=uuid.uuid4(),
        operation=operation,
        status=TaskStatus.RUNNING,
        chunks_completed=chunks_completed,
        total_rows_processed=total_rows_processed,
    )


def _patched_manager() -> SeedTaskManager:
    mgr = SeedTaskManager()
    mgr._acquire_lock = AsyncMock(return_value=True)
    mgr._release_lock = AsyncMock()
    mgr._insert_task = AsyncMock()
    mgr._update_task = AsyncMock()
    return mgr


# -----------------------------------------------------------------
# Test 1: retryable Timeout → INTERRUPTED
# -----------------------------------------------------------------
async def test_run_marks_interrupted_on_retryable_timeout():
    mgr = _patched_manager()
    mgr._run_reseed = AsyncMock(
        side_effect=litellm.Timeout(message="timeout", model="m", llm_provider="vllm")
    )

    state = _make_state()
    await mgr._run(state)

    mgr._update_task.assert_called_once()
    call_kwargs = mgr._update_task.call_args
    assert call_kwargs[0][1] == TaskStatus.INTERRUPTED
    assert state.status == TaskStatus.INTERRUPTED


# -----------------------------------------------------------------
# Test 2: retryable InternalServerError → INTERRUPTED
# -----------------------------------------------------------------
async def test_run_marks_interrupted_on_retryable_internal_server_error():
    mgr = _patched_manager()
    mgr._run_reseed = AsyncMock(
        side_effect=litellm.InternalServerError(
            message="internal", model="m", llm_provider="vllm"
        )
    )

    state = _make_state()
    await mgr._run(state)

    mgr._update_task.assert_called_once()
    call_kwargs = mgr._update_task.call_args
    assert call_kwargs[0][1] == TaskStatus.INTERRUPTED


# -----------------------------------------------------------------
# Test 3: non-retryable error → FAILED (unchanged behaviour)
# -----------------------------------------------------------------
async def test_run_marks_failed_on_non_retryable_error():
    mgr = _patched_manager()
    mgr._run_reseed = AsyncMock(side_effect=ValueError("bad value"))

    state = _make_state()
    await mgr._run(state)

    mgr._update_task.assert_called_once()
    call_kwargs = mgr._update_task.call_args
    assert call_kwargs[0][1] == TaskStatus.FAILED
    assert state.status == TaskStatus.FAILED


# -----------------------------------------------------------------
# Test 4: INTERRUPTED preserves chunks_completed
# -----------------------------------------------------------------
async def test_interrupted_task_preserves_chunks_completed():
    mgr = _patched_manager()
    mgr._run_reseed = AsyncMock(
        side_effect=litellm.Timeout(message="timeout", model="m", llm_provider="vllm")
    )

    state = _make_state(chunks_completed=83, total_rows_processed=4150)
    await mgr._run(state)

    mgr._update_task.assert_called_once()
    _, kwargs = mgr._update_task.call_args
    assert kwargs["chunks_completed"] == 83
    assert kwargs["total_rows_processed"] == 4150


async def test_seed_resume_passes_checkpoint_to_seeder():
    mgr = _patched_manager()
    mgr._run_seed = AsyncMock()
    state = _make_state(operation=OperationType.SEED, chunks_completed=4)

    await mgr._run(state, start_chunk=4)

    mgr._run_seed.assert_awaited_once_with(state, start_chunk=4)
