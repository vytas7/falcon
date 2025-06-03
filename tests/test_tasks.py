import asyncio
import functools

import pytest
from falcon.tasks import SyncTaskManager
from falcon.errors import CompatibilityError


@pytest.fixture()
def sync_manager():
    with SyncTaskManager.start_in_thread() as manager:
        yield manager


async def async_task(name):
    await asyncio.sleep(2.0)
    print(f'From async task: hello, {name}!')
    await asyncio.sleep(1.0)


def test_sync_manager(sync_manager):
    sync_manager.schedule_task(functools.partial(async_task, 'Foo'))

    assert sync_manager.call_async(asyncio.sleep, 5.0, 1337) == 1337


def test_needs_async_loop():
    async def coro():
        pass

    manager = SyncTaskManager()

    with pytest.raises(CompatibilityError):
        manager.schedule_task(coro)

    with pytest.raises(CompatibilityError):
        manager.call_async(coro)
