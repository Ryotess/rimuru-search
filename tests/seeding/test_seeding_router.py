import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.seeding.schemas import OperationType, TaskStatus
from src.seeding.service import SeedTaskManager, TaskState


def _make_task_state(operation=OperationType.SEED, status=TaskStatus.RUNNING):
    return TaskState(
        task_id=uuid.uuid4(),
        operation=operation,
        status=status,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def fresh_manager():
    """Replace the global seed_task_manager with a fresh instance per test."""
    manager = SeedTaskManager()
    with patch("src.seeding.router.seed_task_manager", manager):
        yield manager


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestCreateTask:
    async def test_post_returns_200_with_task_id(self, client, fresh_manager):
        state = _make_task_state()
        with patch.object(
            fresh_manager, "submit", new_callable=AsyncMock, return_value=state
        ):
            resp = await client.post("/v1/seeding/tasks", json={"operation": "SEED"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == str(state.task_id)
        assert data["operation"] == "SEED"
        assert data["status"] == "RUNNING"

    async def test_post_returns_409_when_task_running(self, client, fresh_manager):
        with patch.object(
            fresh_manager,
            "submit",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Task already in progress"),
        ):
            resp = await client.post("/v1/seeding/tasks", json={"operation": "RESEED"})

        assert resp.status_code == 409

    async def test_post_invalid_operation_returns_422(self, client, fresh_manager):
        resp = await client.post("/v1/seeding/tasks", json={"operation": "INVALID"})
        assert resp.status_code == 422

    async def test_post_reseed_with_force_passes_to_submit(self, client, fresh_manager):
        state = _make_task_state(OperationType.RESEED)
        mock_submit = AsyncMock(return_value=state)
        with patch.object(fresh_manager, "submit", mock_submit):
            resp = await client.post(
                "/v1/seeding/tasks", json={"operation": "RESEED", "force": True}
            )

        assert resp.status_code == 200
        mock_submit.assert_awaited_once_with(operation=OperationType.RESEED, force=True)

    async def test_post_reseed_without_force_defaults_false(
        self, client, fresh_manager
    ):
        state = _make_task_state(OperationType.RESEED)
        mock_submit = AsyncMock(return_value=state)
        with patch.object(fresh_manager, "submit", mock_submit):
            resp = await client.post("/v1/seeding/tasks", json={"operation": "RESEED"})

        assert resp.status_code == 200
        mock_submit.assert_awaited_once_with(
            operation=OperationType.RESEED, force=False
        )


class TestGetTask:
    async def test_get_existing_task(self, client, fresh_manager):
        state = _make_task_state()
        with patch.object(
            fresh_manager, "get_task", new_callable=AsyncMock, return_value=state
        ):
            resp = await client.get(f"/v1/seeding/tasks/{state.task_id}")

        assert resp.status_code == 200
        assert resp.json()["task_id"] == str(state.task_id)

    async def test_get_nonexistent_returns_404(self, client, fresh_manager):
        with patch.object(
            fresh_manager, "get_task", new_callable=AsyncMock, return_value=None
        ):
            resp = await client.get(f"/v1/seeding/tasks/{uuid.uuid4()}")

        assert resp.status_code == 404

    async def test_get_invalid_uuid_returns_422(self, client, fresh_manager):
        resp = await client.get("/v1/seeding/tasks/not-a-uuid")
        assert resp.status_code == 422


class TestListTasks:
    async def test_list_returns_all_tasks(self, client, fresh_manager):
        states = [
            _make_task_state(OperationType.SEED),
            _make_task_state(OperationType.RESEED, TaskStatus.COMPLETED),
        ]
        with patch.object(
            fresh_manager, "list_tasks", new_callable=AsyncMock, return_value=states
        ):
            resp = await client.get("/v1/seeding/tasks")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tasks"]) == 2

    async def test_list_returns_empty_when_no_tasks(self, client, fresh_manager):
        with patch.object(
            fresh_manager, "list_tasks", new_callable=AsyncMock, return_value=[]
        ):
            resp = await client.get("/v1/seeding/tasks")

        assert resp.status_code == 200
        assert resp.json()["tasks"] == []
