# Copyright 2025-2026 by Vytautas Liuolia.
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

from __future__ import annotations

import asyncio
from concurrent import futures
import contextlib
import functools
import threading
from typing import Any

from falcon.errors import CompatibilityError


class TaskManager:
    """Task manager."""

    async_loop: asyncio.AbstractEventLoop | None
    """Async loop."""

    executor: futures.Executor | None
    """Executor."""

    _futures: set[asyncio.Task[Any]]

    @classmethod
    @contextlib.contextmanager
    def start_in_thread(cls, daemon: bool = False) -> Any:
        def run_loop(loop: asyncio.BaseEventLoop) -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        manager: TaskManager = cls()
        manager.executor = futures.ThreadPoolExecutor()
        loop = manager.async_loop = asyncio.new_event_loop()
        loop.set_default_executor(manager.executor)

        thread = threading.Thread(target=run_loop, args=(loop,), daemon=daemon)
        thread.start()

        try:
            yield manager
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join()

    def __init__(self) -> None:
        self.async_loop = None
        self.executor = None

        self._futures = set()

    def _schedule_task(self, loop, coro_func) -> None:
        self._futures.add(future := loop.create_task(coro_func()))
        future.add_done_callback(self._futures.discard)

    def schedule_task(self, coro_func: Any) -> None:
        if self.async_loop is None:
            # TODO: Reraise nicer error
            loop = asyncio.get_running_loop()
            self._schedule_task(loop, coro_func)

        else:  # Assume different thread
            self.async_loop.call_soon_threadsafe(
                self._schedule_task, self.async_loop, coro_func
            )

    def schedule_sync_task(self, func: Any, *args, **kwargs) -> None:
        if self.executor is None:
            raise RuntimeError('No executor is configured... TODO better msg')

        if kwargs:
            # NOTe(vytas): Executors don't accept **kwargs.
            self.executor.submit(functools.partial(func, *args, **kwargs))
        else:
            self.executor.submit(func, *args)

    async def call_sync(self, func: Any, *args, **kwargs) -> Any:
        try:
            loop = self.async_loop or asyncio.get_running_loop()
        except RuntimeError:
            raise RuntimeError('No async loop is configured... TODO better msg')

        if kwargs:
            # NOTe(vytas): Executors don't accept **kwargs.
            return await loop.run_in_executor(
                self.executor, functools.partial(func, *args, **kwargs)
            )
        return await loop.run_in_executor(self.executor, func, *args)

    def call_async(self, coro, *args, **kwargs) -> Any:
        if self.async_loop is None:
            raise CompatibilityError('async_loop needs to be configured')

        future = asyncio.run_coroutine_threadsafe(
            coro(*args, **kwargs), self.async_loop
        )
        return future.result()
