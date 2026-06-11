import asyncio
import threading

import pytest

from falcon.errors import CompatibilityError
from falcon.tasks import TaskManager


def test_loop_in_thread():
    async def record_async():
        data['recorded-async'] = 'value1'

    def record_sync():
        data['recorded-sync'] = 'value2'

    data = {}

    with TaskManager.start_in_thread() as tm:
        tm.schedule_async(record_async)
        tm.schedule_sync(record_sync)

        assert tm.call_async(asyncio.sleep, 0.1, 'morning!') == 'morning!'

        assert data == {'recorded-async': 'value1', 'recorded-sync': 'value2'}


async def test_iterate_sync():
    def producer():
        for i in range(5):
            yield i * i

    tm = TaskManager()
    items = [item async for item in tm.iterate_sync(producer())]
    assert items == [0, 1, 4, 9, 16]


async def test_iterate_sync_empty():
    tm = TaskManager()
    items = [item async for item in tm.iterate_sync(iter(()))]
    assert items == []


def test_iterate_async():
    async def producer():
        for i in range(5):
            await asyncio.sleep(0)
            yield i * i

    with TaskManager.start_in_thread() as tm:
        items = list(tm.iterate_async(producer()))

    assert items == [0, 1, 4, 9, 16]


def test_iterate_async_empty():
    async def producer():
        if False:
            yield

    with TaskManager.start_in_thread() as tm:
        items = list(tm.iterate_async(producer()))

    assert items == []


async def test_call_async_deadlock_guard():
    async def noop():
        return 1

    async def producer():
        yield 1

    tm = TaskManager()
    tm.async_loop = asyncio.get_running_loop()

    with pytest.raises(CompatibilityError):
        tm.call_async(noop)
    with pytest.raises(CompatibilityError):
        list(tm.iterate_async(producer()))


async def test_check_not_loop_thread_other_loop():
    # NOTE(vytas): The currently running loop differs from async_loop, so the
    #   deadlock guard must fall through without raising.
    other_loop = asyncio.new_event_loop()
    try:
        tm = TaskManager()
        tm.async_loop = other_loop
        tm._check_not_loop_thread()
    finally:
        other_loop.close()


async def test_schedule_async_running_loop():
    done = asyncio.Event()

    async def work():
        done.set()

    tm = TaskManager()
    tm.schedule_async(work)

    await asyncio.wait_for(done.wait(), timeout=1)


def test_schedule_async_no_loop():
    async def work():
        pass

    tm = TaskManager()
    with pytest.raises(CompatibilityError):
        tm.schedule_async(work)


def test_schedule_sync_no_executor():
    tm = TaskManager()
    with pytest.raises(CompatibilityError):
        tm.schedule_sync(lambda: None)


def test_schedule_sync_kwargs():
    data = {}
    done = threading.Event()

    def record(a, b=None):
        data['a'] = a
        data['b'] = b
        done.set()

    with TaskManager.start_in_thread() as tm:
        tm.schedule_sync(record, 1, b=2)
        assert done.wait(timeout=1)

    assert data == {'a': 1, 'b': 2}


async def test_call_sync():
    def add(a, b=0):
        return a + b

    tm = TaskManager()
    assert await tm.call_sync(add, 3) == 3
    assert await tm.call_sync(add, 3, b=4) == 7


def test_call_sync_no_loop():
    tm = TaskManager()
    coro = tm.call_sync(lambda: 1)
    with pytest.raises(CompatibilityError):
        coro.send(None)


def test_call_async_no_loop():
    async def noop():
        return 1

    tm = TaskManager()
    with pytest.raises(CompatibilityError):
        tm.call_async(noop)


def test_iterate_sync_no_loop():
    tm = TaskManager()
    iterator = tm.iterate_sync(iter((1, 2, 3)))
    with pytest.raises(CompatibilityError):
        iterator.__anext__().send(None)


def test_iterate_async_no_loop():
    async def producer():
        yield 1

    tm = TaskManager()
    with pytest.raises(CompatibilityError):
        list(tm.iterate_async(producer()))
