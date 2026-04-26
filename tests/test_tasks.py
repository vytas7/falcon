import asyncio

from falcon.tasks import TaskManager


def test_loop_in_thread():
    async def record_async():
        data['recorded-async'] = 'value1'

    def record_sync():
        data['recorded-sync'] = 'value2'

    data = {}

    with TaskManager.start_in_thread() as tm:
        tm.schedule_task(record_async)
        tm.schedule_sync_task(record_sync)

        assert tm.call_async(asyncio.sleep, 0.1, 'morning!') == 'morning!'

        assert data == {'recorded-async': 'value1', 'recorded-sync': 'value2'}
