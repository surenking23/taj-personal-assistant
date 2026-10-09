from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from jarvis.schemas import TaskCreate, TaskUpdate
from jarvis.tasks.repository import RedisTaskRepository, TaskStoreUnavailable


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.fail = False

    def set(self, key, value):
        self._check()
        self.values[key] = value

    def get(self, key):
        self._check()
        return self.values.get(key)

    def scan_iter(self, pattern):
        self._check()
        return iter(key for key in self.values if key.startswith(pattern.removesuffix("*")))

    def mget(self, keys):
        self._check()
        return [self.values.get(key) for key in keys]

    def _check(self):
        if self.fail:
            raise RedisConnectionError("Redis unavailable")


def test_redis_task_repository_round_trip():
    repository = RedisTaskRepository(FakeRedis())
    created = repository.create(TaskCreate(title="Prepare interview notes"))

    assert repository.get(created.id) == created
    assert repository.list() == [created]

    updated = repository.update(created.id, TaskUpdate(status="done"))
    assert updated is not None
    assert updated.status == "done"
    assert repository.get(created.id) == updated
    assert repository.update(uuid4(), TaskUpdate(status="done")) is None


def test_redis_failures_are_reported():
    client = FakeRedis()
    client.fail = True
    repository = RedisTaskRepository(client)

    with pytest.raises(TaskStoreUnavailable, match="unavailable"):
        repository.list()
