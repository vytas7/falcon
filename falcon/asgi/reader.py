# Copyright 2019-2025 by Vytautas Liuolia.
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

"""Buffered ASGI stream reader."""

from __future__ import annotations

import io
from typing import AsyncIterator, List, NoReturn, Optional, Protocol, Union

from falcon.errors import DelimiterError
from falcon.errors import OperationNotAllowed
from falcon.typing import AsyncReadableIO

DEFAULT_CHUNK_SIZE = 8192
"""Default minimum chunk size for :class:`BufferedReader` (8 KiB)."""

_MAX_JOIN_CHUNKS = 1024


class BufferedReader:
    """File-like input object wrapping asynchronous iterator over bytes.

    This class implements coroutine functions for asynchronous reading or
    iteration, but otherwise provides an interface similar to that defined by
    :class:`io.IOBase`.
    """

    __slots__ = [
        '_buffer',
        '_buffer_len',
        '_buffer_pos',
        '_chunk_size',
        '_consumed',
        '_exhausted',
        '_iteration_started',
        '_max_join_size',
        '_source',
    ]

    _buffer: bytes
    _buffer_len: int
    _buffer_pos: int
    _chunk_size: int
    _consumed: int
    _exhausted: bool
    _iteration_started: bool
    _max_join_size: int
    _source: AsyncIterator[bytes]

    def __init__(
        self,
        source: Union[AsyncReadableIO, AsyncIterator[bytes]],
        chunk_size: Optional[int] = None,
    ):
        self._source = self._iter_normalized(source)
        self._chunk_size = chunk_size or DEFAULT_CHUNK_SIZE
        self._max_join_size = self._chunk_size * _MAX_JOIN_CHUNKS

        self._buffer = b''
        self._buffer_len = 0
        self._buffer_pos = 0
        self._consumed = 0
        self._exhausted = False
        self._iteration_started = False

    async def _iter_normalized(
        self, source: Union[AsyncReadableIO, AsyncIterator[bytes]]
    ) -> AsyncIterator[bytes]:
        chunk = b''
        chunk_size = self._chunk_size

        async for item in source:
            chunk_len = len(chunk)
            if chunk_len >= chunk_size:
                self._consumed += chunk_len
                yield chunk
                chunk = item
                continue

            chunk += item

        if chunk:
            self._consumed += len(chunk)
            yield chunk

        self._exhausted = True

    async def _iter_with_buffer(self, size_hint: int = 0) -> AsyncIterator[bytes]:
        if self._buffer_len > self._buffer_pos:
            if 0 < size_hint < self._buffer_len - self._buffer_pos:
                buffer_pos = self._buffer_pos
                self._buffer_pos += size_hint
                yield self._buffer[buffer_pos : self._buffer_pos]

            buffer_pos = self._buffer_pos
            self._buffer_pos = self._buffer_len
            yield self._buffer[buffer_pos : self._buffer_len]

        async for chunk in self._source:
            yield chunk

    async def _iter_delimited(
        self, delimiter: bytes, size_hint: int = 0
    ) -> AsyncIterator[bytes]:
        delimiter_len_1 = len(delimiter) - 1
        if not 0 <= delimiter_len_1 < self._chunk_size:
            raise ValueError('delimiter length must be within [1, chunk_size]')

        if self._buffer_len > self._buffer_pos:
            pos = self._buffer.find(delimiter, self._buffer_pos)
            if pos == 0:
                return
            if pos > 0:
                if 0 < size_hint < pos - self._buffer_pos:
                    buffer_pos = self._buffer_pos
                    self._buffer_pos += size_hint
                    yield self._buffer[buffer_pos : self._buffer_pos]
                buffer_pos = self._buffer_pos
                self._buffer_pos = pos
                yield self._buffer[buffer_pos:pos]
                return

            if 0 < size_hint < (self._buffer_len - self._buffer_pos - delimiter_len_1):
                buffer_pos = self._buffer_pos
                self._buffer_pos += size_hint
                yield self._buffer[buffer_pos : self._buffer_pos]

        if self._buffer_pos > 0:
            self._trim_buffer()

        async for chunk in self._source:
            offset = self._buffer_len - delimiter_len_1
            if offset > 0:
                fragment = self._buffer[offset:] + chunk[:delimiter_len_1]
                pos = fragment.find(delimiter)
                if pos < 0:
                    output = self._buffer
                    self._buffer = chunk
                    self._buffer_len = len(chunk)
                    yield output
                else:
                    self._buffer += chunk
                    self._buffer_len += len(chunk)
                    self._buffer_pos = offset + pos
                    # PERF(vytas): local1 + local2 is faster than self._attr
                    #   (still true on CPython 3.8)
                    yield self._buffer[: offset + pos]
                    return
            elif self._buffer:
                self._buffer += chunk
                self._buffer_len += len(chunk)
            else:
                self._buffer = chunk
                self._buffer_len = len(chunk)

            pos = self._buffer.find(delimiter)
            if pos >= 0:  # pragma: no py39,py310 cover
                if pos > 0:
                    self._buffer_pos = pos
                    yield self._buffer[:pos]
                return

        yield self._buffer

    async def _consume_delimiter(self, delimiter: bytes) -> None:
        delimiter_len = len(delimiter)
        if await self.peek(delimiter_len) != delimiter:
            raise DelimiterError('expected delimiter missing')
        self._buffer_pos += delimiter_len

    def _prepend_buffer(self, chunk: bytes) -> None:
        if self._buffer_len > self._buffer_pos:
            self._buffer = chunk + self._buffer[self._buffer_pos :]
            self._buffer_len = len(self._buffer)
        else:
            self._buffer = chunk
            self._buffer_len = len(chunk)

        self._buffer_pos = 0

    def _trim_buffer(self) -> None:
        self._buffer = self._buffer[self._buffer_pos :]
        self._buffer_len -= self._buffer_pos
        self._buffer_pos = 0

    async def _read_from(
        self, source: AsyncIterator[bytes], size: Optional[int] = -1
    ) -> bytes:
        if size == -1 or size is None:
            result_bytes = io.BytesIO()
            async for chunk in source:
                result_bytes.write(chunk)
            return result_bytes.getvalue()

        if size <= 0:
            return b''

        remaining = size

        if size <= self._max_join_size:
            result: List[bytes] = []
            async for chunk in source:
                chunk_len = len(chunk)
                if remaining < chunk_len:
                    result.append(chunk[:remaining])
                    self._prepend_buffer(chunk[remaining:])
                    break

                result.append(chunk)
                remaining -= chunk_len
                if remaining == 0:  # pragma: no py39,py310 cover
                    break

            # PERF(vytas) Don't join unless necessary.
            return (
                result[0] if len(result) == 1 else b''.join(result)
            )  # pragma: no py314 cover

        # NOTE(vytas): size > self._max_join_size
        result_bytes = io.BytesIO()
        async for chunk in source:
            chunk_len = len(chunk)
            if remaining < chunk_len:
                result_bytes.write(chunk[:remaining])
                self._prepend_buffer(chunk[remaining:])
                break

            result_bytes.write(chunk)
            remaining -= chunk_len
            if remaining == 0:  # pragma: no py39,py310 cover
                break

        return result_bytes.getvalue()

    def delimit(self, delimiter: bytes) -> BufferedReader:  # TODO: should se self
        return type(self)(self._iter_delimited(delimiter), chunk_size=self._chunk_size)

    # -------------------------------------------------------------------------
    # Asynchronous IO interface.
    # -------------------------------------------------------------------------

    def __aiter__(self) -> AsyncIterator[bytes]:
        if self._iteration_started:
            raise OperationNotAllowed('This stream is already being iterated over.')

        self._iteration_started = True

        # PERF(vytas): Do not wrap unless needed.
        if self._buffer_len > self._buffer_pos:
            return self._iter_with_buffer()
        return self._source

    async def exhaust(self) -> None:
        await self.pipe()

    async def peek(self, size: int = -1) -> bytes:
        if size < 0 or size > self._chunk_size:
            size = self._chunk_size

        if self._buffer_pos > 0:
            self._trim_buffer()

        if self._buffer_len < size:
            async for chunk in self._source:
                self._buffer += chunk
                self._buffer_len = len(self._buffer)
                if self._buffer_len >= size:  # pragma: no py39,py310 cover
                    break

        return self._buffer[:size]  # pragma: no py314 cover

    async def pipe(self, destination: Optional[AsyncWritableIO] = None) -> None:
        async for chunk in self._iter_with_buffer():
            if destination is not None:
                await destination.write(chunk)

    async def pipe_until(
        self,
        delimiter: bytes,
        destination: Optional[AsyncWritableIO] = None,
        consume_delimiter: bool = False,
    ) -> None:
        async for chunk in self._iter_delimited(delimiter):
            if destination is not None:
                await destination.write(chunk)

        if consume_delimiter:
            await self._consume_delimiter(delimiter)

    async def read(self, size: Optional[int] = -1) -> bytes:
        return await self._read_from(self._iter_with_buffer(size_hint=size or 0), size)

    async def readall(self) -> bytes:
        """Read and return all remaining data in the request body.

        Warning:
            Only use this method when you can be certain that you have
            enough free memory for the entire request body, and that you
            have configured your web server to limit request bodies to a
            reasonable size (to guard against malicious requests).

        Returns:
            bytes: The request body data, or ``b''`` if the body is empty or
            has already been consumed.
        """
        return await self._read_from(self._iter_with_buffer())

    async def read_until(
        self, delimiter: bytes, size: int = -1, consume_delimiter: bool = False
    ) -> bytes:
        result = await self._read_from(
            self._iter_delimited(delimiter, size_hint=size or 0), size
        )

        if consume_delimiter:
            await self._consume_delimiter(delimiter)

        return result

    # -------------------------------------------------------------------------
    # These methods are included to improve compatibility with Python's
    #   standard "file-like" IO interface.
    # -------------------------------------------------------------------------

    # TODO(vytas): Implement the same close() machinery as in asgi.stream?
    # def close(self):
    #     pass

    @property
    def eof(self) -> bool:
        """Whether the stream is at EOF."""
        return self._exhausted and self._buffer_len == self._buffer_pos

    def fileno(self) -> NoReturn:
        """Raise an instance of OSError since a file descriptor is not used."""
        raise OSError('This IO object does not use a file descriptor')

    def isatty(self) -> bool:
        """Return ``False`` always."""
        return False

    def readable(self) -> bool:
        """Return ``True`` always."""
        return True

    def seekable(self) -> bool:
        """Return ``False`` always."""
        return False

    def writable(self) -> bool:
        """Return ``False`` always."""
        return False

    def tell(self) -> int:
        """Return the number of bytes read from the stream so far."""
        return self._consumed - (self._buffer_len - self._buffer_pos)


class AsyncWritableIO(Protocol):
    async def write(self, data: bytes, /) -> None: ...
