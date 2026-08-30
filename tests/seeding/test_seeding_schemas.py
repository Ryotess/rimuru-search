import uuid

import pytest
from pydantic import ValidationError

from src.seeding.schemas import (
    OperationType,
    SeedRequest,
    TaskResponse,
    TaskStatus,
)


class TestOperationType:
    def test_seed_value(self):
        assert OperationType.SEED == "SEED"

    def test_reseed_value(self):
        assert OperationType.RESEED == "RESEED"


class TestTaskStatus:
    def test_pending_value(self):
        assert TaskStatus.PENDING == "PENDING"

    def test_running_value(self):
        assert TaskStatus.RUNNING == "RUNNING"

    def test_completed_value(self):
        assert TaskStatus.COMPLETED == "COMPLETED"

    def test_failed_value(self):
        assert TaskStatus.FAILED == "FAILED"

    def test_interrupted_value(self):
        assert TaskStatus.INTERRUPTED == "INTERRUPTED"


class TestSeedRequest:
    def test_valid_seed_request(self):
        req = SeedRequest(operation=OperationType.SEED)
        assert req.operation == OperationType.SEED

    def test_valid_reseed_request(self):
        req = SeedRequest(operation=OperationType.RESEED)
        assert req.operation == OperationType.RESEED

    def test_missing_operation_raises(self):
        with pytest.raises(ValidationError):
            SeedRequest()

    def test_force_defaults_to_false(self):
        req = SeedRequest(operation=OperationType.RESEED)
        assert req.force is False

    def test_force_can_be_set_true(self):
        req = SeedRequest(operation=OperationType.RESEED, force=True)
        assert req.force is True


class TestTaskResponse:
    def test_minimal_task_response(self):
        task_id = uuid.uuid4()
        resp = TaskResponse(
            task_id=task_id,
            operation=OperationType.SEED,
            status=TaskStatus.PENDING,
            created_at="2026-04-07T10:00:00Z",
        )
        assert resp.task_id == task_id
        assert resp.completed_at is None
        assert resp.progress is None
        assert resp.error is None
