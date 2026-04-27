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
from collections.abc import AsyncIterable
from collections.abc import AsyncIterator
from collections.abc import Coroutine
from collections.abc import Iterable
from collections.abc import Iterator
from concurrent import futures
import contextlib
import functools
import threading
from typing import Any, Callable, TypeVar

from falcon.errors import CompatibilityError

_T = TypeVar('_T')

_CoroFunc = Callable[[], Coroutine[Any, Any, Any]]

_NO_ASYNC_LOOP = 'no async loop is configured'
_NO_EXECUTOR = 'no executor is configured'


class TaskManager:
    """Coordinate async tasks and sync work across an event loop and executor.

    A :class:`TaskManager` bundles an :mod:`asyncio` event loop together with a
    thread pool (or any other :class:`concurrent.futures.Executor`) and exposes
    helpers for crossing the sync/async boundary in either direction.

    The loop and executor may be supplied by an outer host (e.g., ASGI), or
    spawned on demand via :meth:`start_in_thread`. Methods that need a loop
    fall back to :func:`asyncio.get_running_loop` when :attr:`async_loop` is
    not set; methods that hop threads require :attr:`async_loop` explicitly.
    """

    async_loop: asyncio.AbstractEventLoop | None
    """Event loop used by cross-thread methods.

    When ``None``, methods that can do so fall back to the loop of the
    currently running task.
    """

    executor: futures.Executor | None
    """Executor used to offload synchronous work.

    When ``None``, the loop's default executor is used (see
    :meth:`asyncio.loop.run_in_executor`).
    """

    _futures: set[asyncio.Task[Any]]

    @classmethod
    @contextlib.contextmanager
    def start_in_thread(cls) -> Iterator[TaskManager]:
        """Run a fresh event loop in a background thread.

        Creates a new :class:`TaskManager` whose :attr:`async_loop` runs on a
        dedicated thread, backed by a :class:`~concurrent.futures.ThreadPoolExecutor`
        installed as the loop's default executor. On exit, the loop is
        stopped and the thread is joined.

        The worker thread is always a daemon thread so a forgotten or aborted
        ``with``-block does not hang interpreter shutdown. Callers that need
        in-flight tasks to complete before exit must close the context manager
        explicitly.

        Yields:
            TaskManager: A manager whose loop is running in another thread,
            ready for cross-thread scheduling via :meth:`call_async`,
            :meth:`schedule_async`, and :meth:`iterate_async`.
        """

        def run_loop(loop: asyncio.AbstractEventLoop) -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        manager: TaskManager = cls()
        manager.executor = futures.ThreadPoolExecutor()
        loop = manager.async_loop = asyncio.new_event_loop()
        loop.set_default_executor(manager.executor)

        thread = threading.Thread(target=run_loop, args=(loop,), daemon=True)
        thread.start()

        try:
            yield manager
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join()

    def __init__(self) -> None:
        """Initialize a manager with no loop or executor configured."""
        self.async_loop = None
        self.executor = None

        self._futures = set()

    def _schedule_task(
        self,
        loop: asyncio.AbstractEventLoop,
        coro_func: _CoroFunc,
    ) -> None:
        self._futures.add(future := loop.create_task(coro_func()))
        future.add_done_callback(self._futures.discard)

    def schedule_async(self, coro_func: _CoroFunc) -> None:
        """Schedule a coroutine factory to run on the event loop.

        If :attr:`async_loop` is configured, the coroutine is scheduled
        thread-safely on it; otherwise the currently running loop is used. A
        strong reference to the resulting task is kept until it completes, so
        the caller does not need to retain one.

        Args:
            coro_func: A zero-argument callable returning a coroutine, e.g.,
                a bare ``async def`` function. Bind any arguments with
                :func:`functools.partial` before passing.

        Raises:
            CompatibilityError: No event loop is configured or running.
        """
        if self.async_loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                raise CompatibilityError(_NO_ASYNC_LOOP) from None
            self._schedule_task(loop, coro_func)

        else:  # Assume different thread
            self.async_loop.call_soon_threadsafe(
                self._schedule_task, self.async_loop, coro_func
            )

    def schedule_sync(
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> None:
        """Submit a synchronous callable to the executor.

        The call is fire-and-forget; the resulting :class:`~concurrent.futures.Future`
        is discarded.

        Args:
            func: Synchronous callable to invoke.
            *args: Positional arguments forwarded to ``func``.
            **kwargs: Keyword arguments forwarded to ``func`` (wrapped in
                :func:`functools.partial`, since
                :meth:`~concurrent.futures.Executor.submit` does not accept
                keyword arguments directly).

        Raises:
            CompatibilityError: No executor is configured.
        """
        if self.executor is None:
            raise CompatibilityError(_NO_EXECUTOR)

        if kwargs:
            # NOTE(vytas): Executors don't accept **kwargs.
            self.executor.submit(functools.partial(func, *args, **kwargs))
        else:
            self.executor.submit(func, *args)

    async def call_sync(self, func: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
        """Run a synchronous callable on the executor and await its result.

        Args:
            func: Synchronous callable to invoke.
            *args: Positional arguments forwarded to ``func``.
            **kwargs: Keyword arguments forwarded to ``func``.

        Returns:
            The value returned by ``func``.

        Raises:
            CompatibilityError: No event loop is configured or running.
        """
        try:
            loop = self.async_loop or asyncio.get_running_loop()
        except RuntimeError:
            raise CompatibilityError(_NO_ASYNC_LOOP) from None

        if kwargs:
            # NOTE(vytas): Executors don't accept **kwargs.
            return await loop.run_in_executor(
                self.executor, functools.partial(func, *args, **kwargs)
            )
        return await loop.run_in_executor(self.executor, func, *args)

    def call_async(
        self,
        coro: Callable[..., Coroutine[Any, Any, _T]],
        *args: Any,
        **kwargs: Any,
    ) -> _T:
        """Run a coroutine on the cross-thread loop and block for its result.

        Must be called from a thread other than the one running
        :attr:`async_loop`, otherwise the calling thread will deadlock.

        Args:
            coro: Coroutine function to invoke. Its returned coroutine is
                scheduled via :func:`asyncio.run_coroutine_threadsafe`.
            *args: Positional arguments forwarded to ``coro``.
            **kwargs: Keyword arguments forwarded to ``coro``.

        Returns:
            The value the coroutine resolves to.

        Raises:
            CompatibilityError: :attr:`async_loop` is not configured.
        """
        if self.async_loop is None:
            raise CompatibilityError(_NO_ASYNC_LOOP)

        future = asyncio.run_coroutine_threadsafe(
            coro(*args, **kwargs), self.async_loop
        )
        return future.result()

    async def iterate_sync(self, iterable: Iterable[_T]) -> AsyncIterator[_T]:
        """Iterate a synchronous iterable on the executor.

        Each call to :func:`next` is offloaded to :attr:`executor` so that a
        blocking iterator does not stall the event loop.

        Args:
            iterable: A synchronous iterable to consume.

        Yields:
            Items produced by ``iterable``, one at a time.

        Raises:
            CompatibilityError: No event loop is configured or running.
        """
        try:
            loop = self.async_loop or asyncio.get_running_loop()
        except RuntimeError:
            raise CompatibilityError(_NO_ASYNC_LOOP) from None

        iterator = iter(iterable)
        sentinel: Any = object()

        def _next() -> Any:
            return next(iterator, sentinel)

        while True:
            item = await loop.run_in_executor(self.executor, _next)
            if item is sentinel:
                return
            yield item

    def iterate_async(self, async_iterable: AsyncIterable[_T]) -> Iterator[_T]:
        """Iterate an asynchronous iterable from a synchronous caller.

        Each ``__anext__()`` step is scheduled on :attr:`async_loop` via
        :func:`asyncio.run_coroutine_threadsafe` and the result is awaited
        synchronously. Must be called from a thread other than the one
        running :attr:`async_loop`, otherwise the calling thread will
        deadlock.

        Args:
            async_iterable: An asynchronous iterable to consume.

        Yields:
            Items produced by ``async_iterable``, one at a time.

        Raises:
            CompatibilityError: :attr:`async_loop` is not configured.
        """
        if self.async_loop is None:
            raise CompatibilityError(_NO_ASYNC_LOOP)

        loop = self.async_loop
        iterator = async_iterable.__aiter__()

        async def _anext() -> _T:
            return await iterator.__anext__()

        while True:
            future = asyncio.run_coroutine_threadsafe(_anext(), loop)
            try:
                yield future.result()
            except StopAsyncIteration:
                return
