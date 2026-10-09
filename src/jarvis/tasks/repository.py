import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from redis import Redis
from redis.exceptions import RedisError

from jarvis.schemas import TaskCreate, TaskResponse, TaskUpdate


class TaskStoreUnavailable(Exception):
    pass


class RedisTaskRepository:
    PREFIX = "jarvis:task:"

    def __init__(self, client: Redis):
        self.client = client

    def create(self, task: TaskCreate) -> TaskResponse:
        now = datetime.now(timezone.utc)
        record = TaskResponse(
            id=uuid4(),
            title=task.title,
            description=task.description,
            status="pending",
            due_at=task.due_at,
            created_at=now,
            updated_at=now,
        )
        self._set(record)
        return record

    def get(self, task_id: UUID) -> TaskResponse | None:
        try:
            raw = self.client.get(f"{self.PREFIX}{task_id}")
        except RedisError as error:
            raise TaskStoreUnavailable("Task storage is unavailable") from error
        if raw is None:
            return None
        return TaskResponse.model_validate_json(raw)

    def list(self) -> list[TaskResponse]:
        try:
            keys = list(self.client.scan_iter(f"{self.PREFIX}*"))
            values = self.client.mget(keys)
        except RedisError as error:
            raise TaskStoreUnavailable("Task storage is unavailable") from error
        records = [TaskResponse.model_validate_json(value) for value in values if value is not None]
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def update(self, task_id: UUID, changes: TaskUpdate) -> TaskResponse | None:
        current = self.get(task_id)
        if current is None:
            return None
        updated = current.model_copy(
            update={**changes.model_dump(exclude_unset=True), "updated_at": datetime.now(timezone.utc)}
        )
        self._set(updated)
        return updated

    def _set(self, task: TaskResponse) -> None:
        try:
            self.client.set(f"{self.PREFIX}{task.id}", json.dumps(task.model_dump(mode="json")))
        except RedisError as error:
            raise TaskStoreUnavailable("Task storage is unavailable") from error
