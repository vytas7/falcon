# Copyright 2025 by Vytautas Liuolia.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Task manager."""

import abc
import asyncio
import concurrent
import contextlib
import functools
import threading
from typing import Optional, Set, Callable

from falcon.errors import CompatibilityError


class BaseTaskManager(abc.ABC):
    """Task manager."""

    async_loop: Optional[asyncio.AbstractEventLoop]
    """Async loop."""

    executor: Optional[concurrent.futures.Executor]
    """Executor."""

    _futures: Set[asyncio.Task]

    def __init__(self) -> None:
        self.async_loop = None
        self.executor = None

        self._futures = set()

    @abc.abstractmethod
    def schedule_task(self, callback): ...

    @abc.abstractmethod
    def schedule_sync_task(self, callback): ...

    def _schedule_task(self, callback):
        self._futures.add(future := asyncio.create_task(callback()))
        future.add_done_callback(self._task_done)

    def _task_done(self, future):
        self._futures.discard(future)


class SyncTaskManager(BaseTaskManager):
    def __init__(self):
        super().__init__()
        self.executor = concurrent.futures.ThreadPoolExecutor()

    @classmethod
    @contextlib.contextmanager
    def start_in_thread(cls, daemon: bool = False):
        def run_loop(loop: asyncio.BaseEventLoop) -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        manager = cls()
        loop = manager.async_loop = asyncio.new_event_loop()
        thread = threading.Thread(target=run_loop, args=(loop,), daemon=daemon)
        thread.start()

        try:
            yield manager
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join()

    def schedule_task(self, callback) -> None:
        if self.async_loop is None:
            raise CompatibilityError('async_loop needs to be configured')

        self.async_loop.call_soon_threadsafe(self._schedule_task, callback)

    def schedule_sync_task(self, callback: Callable) -> None:
        if self.executor is None:
            raise CompatibilityError('executor needs to be configured')

        self.executor.submit(callback)

    def call_async(self, coro, *args, **kwargs):
        if self.async_loop is None:
            raise CompatibilityError('async_loop needs to be configured')

        future = asyncio.run_coroutine_threadsafe(
            coro(*args, **kwargs), self.async_loop
        )
        return future.result()


class AsyncTaskManager(BaseTaskManager):
    def __init__(self) -> None:
        super().__init__()

    def schedule_task(self, callback):
        self._schedule_task(callback)

    def schedule_sync_task(self, callback) -> None:
        loop = self.async_loop or asyncio.get_running_loop()
        loop.run_in_executor(self.executor, callback)

    async def call_sync(self, func, *args, **kwargs):
        loop = self.async_loop or asyncio.get_running_loop()
        if kwargs:
            return await loop.run_in_executor(
                self.executor, functools.partial(func, *args, **kwargs)
            )
        return await loop.run_in_executor(self.executor, func, *args)
