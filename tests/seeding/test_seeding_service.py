import asyncio
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.seeding.schemas import OperationType, TaskStatus
from src.seeding.service import SeedTaskManager


@pytest.fixture
def manager():
    return SeedTaskManager()


@contextmanager
def patch_infra(manager, *, lock_acquired=True):
    """Patch DB/Redis calls and store mocks as manager._mock_* for post-context assertions."""
    mock_acquire = AsyncMock(return_value=lock_acquired)
    mock_release = AsyncMock()
    mock_insert = AsyncMock()
    mock_update = AsyncMock()
    mock_find = AsyncMock(return_value=None)
    with (
        patch.object(manager, "_acquire_lock", mock_acquire),
        patch.object(manager, "_release_lock", mock_release),
        patch.object(manager, "_insert_task", mock_insert),
        patch.object(manager, "_update_task", mock_update),
        patch.object(manager, "_find_interrupted_task", mock_find),
    ):
        manager._mock_acquire = mock_acquire
        manager._mock_release = mock_release
        manager._mock_insert = mock_insert
        manager._mock_update = mock_update
        manager._mock_find = mock_find
        yield


class TestSubmit:
    async def test_submit_returns_running_task_state(self, manager):
        with (
            patch_infra(manager),
            patch.object(manager, "_run", new_callable=AsyncMock),
        ):
            state = await manager.submit(OperationType.SEED)

        assert isinstance(state.task_id, UUID)
        assert state.operation == OperationType.SEED
        assert state.status == TaskStatus.RUNNING

    async def test_submit_acquires_redis_lock(self, manager):
        with (
            patch_infra(manager),
            patch.object(manager, "_run", new_callable=AsyncMock),
        ):
            await manager.submit(OperationType.SEED)

        manager._mock_acquire.assert_awaited_once()

    async def test_submit_inserts_db_record(self, manager):
        with (
            patch_infra(manager),
            patch.object(manager, "_run", new_callable=AsyncMock),
        ):
            state = await manager.submit(OperationType.SEED)

        manager._mock_insert.assert_awaited_once_with(state.task_id, OperationType.SEED)

    async def test_submit_raises_when_task_already_running(self, manager):
        never_done = asyncio.Future()

        async def fake_run(state, start_chunk=0):
            await never_done

        with patch_infra(manager), patch.object(manager, "_run", side_effect=fake_run):
            await manager.submit(OperationType.SEED)
            await asyncio.sleep(0.01)

            with pytest.raises(RuntimeError, match="already in progress"):
                await manager.submit(OperationType.RESEED)

        never_done.cancel()

    async def test_submit_raises_when_lock_unavailable(self, manager):
        with (
            patch_infra(manager, lock_acquired=False),
            pytest.raises(RuntimeError, match="Another instance"),
        ):
            await manager.submit(OperationType.SEED)

    async def test_submit_releases_lock_if_db_insert_fails(self, manager):
        with (
            patch.object(manager, "_acquire_lock", AsyncMock(return_value=True)),
            patch.object(manager, "_release_lock", AsyncMock()) as mock_release,
            patch.object(
                manager, "_find_interrupted_task", AsyncMock(return_value=None)
            ),
            patch.object(
                manager, "_insert_task", AsyncMock(side_effect=RuntimeError("DB error"))
            ),
            patch.object(manager, "_update_task", AsyncMock()),
        ):
            mock_release = manager._release_lock  # grab before patch exits
            with pytest.raises(RuntimeError, match="DB error"):
                await manager.submit(OperationType.SEED)
            mock_release.assert_awaited_once()


class TestTaskLifecycle:
    async def test_successful_task_writes_completed_to_db(self, manager):
        async def fake_run_seed(state, start_chunk=0):
            pass

        with (
            patch_infra(manager),
            patch.object(manager, "_run_seed", side_effect=fake_run_seed),
        ):
            state = await manager.submit(OperationType.SEED)
            await asyncio.sleep(0.1)

            assert state.status == TaskStatus.COMPLETED
            assert state.completed_at is not None
            completed_calls = [
                c
                for c in manager._mock_update.await_args_list
                if c.args[1] == TaskStatus.COMPLETED
            ]
            assert len(completed_calls) == 1

    async def test_failed_task_writes_failed_with_error(self, manager):
        async def failing_seed(state, start_chunk=0):
            raise ValueError("embedding service unavailable")

        with (
            patch_infra(manager),
            patch.object(manager, "_run_seed", side_effect=failing_seed),
        ):
            state = await manager.submit(OperationType.SEED)
            await asyncio.sleep(0.1)

            assert state.status == TaskStatus.FAILED
            assert "embedding service unavailable" in state.error
            failed_calls = [
                c
                for c in manager._mock_update.await_args_list
                if c.args[1] == TaskStatus.FAILED
            ]
            assert len(failed_calls) == 1

    async def test_failed_task_releases_lock(self, manager):
        async def failing_seed(state, start_chunk=0):
            raise ValueError("fail")

        with (
            patch_infra(manager),
            patch.object(manager, "_run_seed", side_effect=failing_seed),
        ):
            await manager.submit(OperationType.SEED)
            await asyncio.sleep(0.1)
            manager._mock_release.assert_awaited()


class TestCancelRunning:
    async def test_cancel_writes_interrupted_to_db(self, manager):
        never_done = asyncio.Future()

        async def fake_run_reseed(state, start_chunk=0):
            state.chunks_completed = 7
            await never_done

        with (
            patch_infra(manager),
            patch.object(
                manager, "_find_interrupted_task", AsyncMock(return_value=None)
            ),
            patch.object(manager, "_run_reseed", side_effect=fake_run_reseed),
        ):
            state = await manager.submit(OperationType.RESEED)
            await asyncio.sleep(0.01)
            await manager.cancel_running()

            assert state.status == TaskStatus.INTERRUPTED
            interrupted_calls = [
                c
                for c in manager._mock_update.await_args_list
                if c.args[1] == TaskStatus.INTERRUPTED
            ]
            assert len(interrupted_calls) == 1
            assert interrupted_calls[0].kwargs["chunks_completed"] == 7

    async def test_cancel_releases_lock(self, manager):
        never_done = asyncio.Future()

        async def fake_run_reseed(state, start_chunk=0):
            await never_done

        with (
            patch_infra(manager),
            patch.object(
                manager, "_find_interrupted_task", AsyncMock(return_value=None)
            ),
            patch.object(manager, "_run_reseed", side_effect=fake_run_reseed),
        ):
            await manager.submit(OperationType.RESEED)
            await asyncio.sleep(0.01)
            await manager.cancel_running()
            manager._mock_release.assert_awaited()

    async def test_cancel_sets_completed_at(self, manager):
        never_done = asyncio.Future()

        async def fake_run_reseed(state, start_chunk=0):
            state.chunks_completed = 3
            await never_done

        with (
            patch_infra(manager),
            patch.object(
                manager, "_find_interrupted_task", AsyncMock(return_value=None)
            ),
            patch.object(manager, "_run_reseed", side_effect=fake_run_reseed),
        ):
            state = await manager.submit(OperationType.RESEED)
            await asyncio.sleep(0.01)
            await manager.cancel_running()

            assert state.completed_at is not None
            interrupted_calls = [
                c
                for c in manager._mock_update.await_args_list
                if c.args[1] == TaskStatus.INTERRUPTED
            ]
            assert len(interrupted_calls) == 1
            assert interrupted_calls[0].kwargs["completed_at"] is not None

    async def test_cancel_no_op_when_nothing_running(self, manager):
        with patch_infra(manager):
            await manager.cancel_running()
        manager._mock_update.assert_not_awaited()


class TestSubmitResume:
    def _mock_find_interrupted(self, manager, result):
        """Patch _find_interrupted_task to return a fixed result."""
        return patch.object(
            manager, "_find_interrupted_task", AsyncMock(return_value=result)
        )

    async def test_reseed_resumes_interrupted_task(self, manager):
        task_id = uuid.uuid4()
        interrupted = (task_id, 5, 500)

        with (
            patch_infra(manager),
            self._mock_find_interrupted(manager, interrupted),
            patch.object(manager, "_run", new_callable=AsyncMock),
        ):
            state = await manager.submit(OperationType.RESEED)

        assert state.task_id == task_id
        assert state.status == TaskStatus.RUNNING
        assert state.chunks_completed == 5
        assert state.total_rows_processed == 500
        manager._mock_insert.assert_not_awaited()
        manager._mock_update.assert_awaited_once_with(task_id, TaskStatus.RUNNING)

    async def test_reseed_no_interrupted_creates_new_task(self, manager):
        with (
            patch_infra(manager),
            self._mock_find_interrupted(manager, None),
            patch.object(manager, "_run", new_callable=AsyncMock),
        ):
            state = await manager.submit(OperationType.RESEED)

        assert state.status == TaskStatus.RUNNING
        manager._mock_insert.assert_awaited_once()

    async def test_seed_checks_for_an_interrupted_task(self, manager):
        with (
            patch_infra(manager),
            patch.object(manager, "_run", new_callable=AsyncMock),
        ):
            await manager.submit(OperationType.SEED)

        manager._mock_find.assert_awaited_once_with(OperationType.SEED)

    async def test_reseed_resume_lock_failure(self, manager):
        task_id = uuid.uuid4()
        interrupted = (task_id, 5, 500)

        with (
            patch_infra(manager, lock_acquired=False),
            self._mock_find_interrupted(manager, interrupted),
            pytest.raises(RuntimeError, match="Another instance"),
        ):
            await manager.submit(OperationType.RESEED)

        manager._mock_update.assert_not_awaited()

    async def test_reseed_resume_passes_start_chunk_to_run(self, manager):
        task_id = uuid.uuid4()
        interrupted = (task_id, 7, 700)
        mock_run = AsyncMock()

        with (
            patch_infra(manager),
            self._mock_find_interrupted(manager, interrupted),
            patch.object(manager, "_run", mock_run),
        ):
            await manager.submit(OperationType.RESEED)
            await asyncio.sleep(0.01)

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["start_chunk"] == 7

    async def test_force_reseed_creates_new_task_despite_interrupted(self, manager):
        task_id = uuid.uuid4()
        interrupted = (task_id, 5, 500)

        with (
            patch_infra(manager),
            self._mock_find_interrupted(manager, interrupted),
            patch.object(manager, "_run", new_callable=AsyncMock),
        ):
            state = await manager.submit(OperationType.RESEED, force=True)

        assert state.task_id != task_id
        manager._mock_insert.assert_awaited_once()
        # Old task should be marked CANCELLED
        cancel_calls = [
            c
            for c in manager._mock_update.await_args_list
            if c.args == (task_id, TaskStatus.CANCELLED)
        ]
        assert len(cancel_calls) == 1

    async def test_force_reseed_no_interrupted_creates_normally(self, manager):
        with (
            patch_infra(manager),
            self._mock_find_interrupted(manager, None),
            patch.object(manager, "_run", new_callable=AsyncMock),
        ):
            state = await manager.submit(OperationType.RESEED, force=True)

        assert state.status == TaskStatus.RUNNING
        manager._mock_insert.assert_awaited_once()


class TestGetTask:
    async def test_returns_in_memory_state_for_current_task(self, manager):
        with (
            patch_infra(manager),
            patch.object(manager, "_run", new_callable=AsyncMock),
        ):
            state = await manager.submit(OperationType.SEED)

        result = await manager.get_task(state.task_id)
        assert result is state

    async def test_returns_none_for_unknown_uuid(self, manager):
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.seeding.service.task_manager.SessionLocal", return_value=mock_ctx
        ):
            result = await manager.get_task(uuid.uuid4())

        assert result is None

    async def test_reads_from_db_for_completed_task(self, manager):
        task_id = uuid.uuid4()
        mock_row = MagicMock()
        mock_row.id = task_id
        mock_row.operation = "RESEED"
        mock_row.status = "COMPLETED"
        mock_row.created_at = datetime.now(UTC)
        mock_row.completed_at = datetime.now(UTC)
        mock_row.progress = "done"
        mock_row.total_rows_processed = 1000
        mock_row.chunks_completed = 10
        mock_row.error = None

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.seeding.service.task_manager.SessionLocal", return_value=mock_ctx
        ):
            result = await manager.get_task(task_id)

        assert result is not None
        assert result.task_id == task_id
        assert result.status == TaskStatus.COMPLETED
        assert result.chunks_completed == 10
