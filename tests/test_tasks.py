import asyncio

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
            yield  # pragma: no cover

    with TaskManager.start_in_thread() as tm:
        items = list(tm.iterate_async(producer()))

    assert items == []
