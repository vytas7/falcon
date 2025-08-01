from __future__ import annotations

import asyncio
from datetime import datetime
from datetime import timezone
from functools import partial
import io
import os
from pathlib import Path
import re
from typing import Any, ClassVar, IO, Optional, Pattern, Tuple, TYPE_CHECKING, Union

import falcon
from falcon.typing import ReadableIO

if TYPE_CHECKING:
    from falcon import asgi
    from falcon import Request
    from falcon import Response


def _open_file(file_path: Union[str, Path]) -> Tuple[io.BufferedReader, os.stat_result]:
    """Open a file for a static file request and read file stat.

    Args:
        file_path (Union[str, Path]): Path to the file to open.
    Returns:
        tuple: Tuple of (BufferedReader, stat_result).
    """
    fh: Optional[io.BufferedReader] = None
    try:
        fh = io.open(file_path, 'rb')
        st = os.fstat(fh.fileno())
    except IOError:
        if fh is not None:
            fh.close()
        raise falcon.HTTPNotFound()
    return fh, st


def _set_range(
    fh: io.BufferedReader, st: os.stat_result, req_range: Optional[Tuple[int, int]]
) -> Tuple[ReadableIO, int, Optional[Tuple[int, int, int]]]:
    """Process file handle for a ranged request.

    Args:
        fh (io.BufferedReader): file handle of the file.
        st (os.stat_result): fs stat result of the file.
        req_range (Optional[Tuple[int, int]]): Request.range value.
    Returns:
        tuple: Three-member tuple of (stream, content-length, content-range).
            If req_range is ``None`` or ignored, content-range will be
            ``None``; otherwise, the stream will be appropriately seeked and
            possibly bounded, and the content-range will be a tuple of
            (start, end, size).
    """
    size = st.st_size
    if req_range is None:
        return fh, size, None

    start, end = req_range
    if size == 0:
        # NOTE(tipabu): Ignore Range headers for zero-byte files; just serve
        #   the empty body since Content-Range can't be used to express a
        #   zero-byte body.
        return fh, 0, None

    if start < 0 and end == -1:
        # NOTE(tipabu): Special case: only want the last N bytes.
        start = max(start, -size)
        fh.seek(start, os.SEEK_END)
        # NOTE(vytas): Wrap in order to prevent sendfile from being used, as
        #   its implementation was found to be buggy in many popular WSGI
        #   servers for open files with a non-zero offset.
        return _BoundedFile(fh, -start), -start, (size + start, size - 1, size)

    if start >= size:
        fh.close()
        raise falcon.HTTPRangeNotSatisfiable(size)

    fh.seek(start)
    if end == -1:
        # NOTE(vytas): Wrap in order to prevent sendfile from being used, as
        #   its implementation was found to be buggy in many popular WSGI
        #   servers for open files with a non-zero offset.
        length = size - start
        return _BoundedFile(fh, length), length, (start, size - 1, size)

    end = min(end, size - 1)
    length = end - start + 1
    return _BoundedFile(fh, length), length, (start, end, size)


def _is_not_modified(
    req: falcon.Request, current_etag: str, last_modified: datetime
) -> bool:
    """Check whether the requested resource can be served with 304 Not Modified."""

    # NOTE(Cycloctane): RFC 9110 Section 13.1.3: A recipient MUST ignore
    #   If-Modified-Since if the request contains an If-None-Match header
    #   field. See also:
    #   https://www.rfc-editor.org/rfc/rfc9110#section-13.1.3-5
    #   https://www.rfc-editor.org/rfc/rfc9110#section-13.2.2
    if req.if_none_match is not None:
        return (len(req.if_none_match) == 1 and req.if_none_match[0] == '*') or any(
            current_etag == etag for etag in req.if_none_match
        )

    if req.if_modified_since is not None:
        return last_modified <= req.if_modified_since

    return False


class _BoundedFile:
    """Wrap a file to only allow part of it to be read.

    Args:
        fh: The file object to wrap. Should be opened in binary mode,
            and already seeked to an appropriate position. The object must
            expose a ``.close()`` method.
        length (int): Number of bytes that may be read.
    """

    def __init__(self, fh: IO[bytes], length: int) -> None:
        self.fh = fh
        self.close = fh.close
        self.remaining = length

    def read(self, size: Optional[int] = -1) -> bytes:
        """Read the underlying file object, within the specified bounds."""
        if size is None or size < 0:
            size = self.remaining
        else:
            size = min(size, self.remaining)
        data = self.fh.read(size)
        self.remaining -= len(data)
        return data


class StaticRoute:
    """Represents a static route.

    Args:
        prefix (str): The path prefix to match for this route. If the
            path in the requested URI starts with this string, the remainder
            of the path will be appended to the source directory to
            determine the file to serve. This is done in a secure manner
            to prevent an attacker from requesting a file outside the
            specified directory.

            Note that static routes are matched in LIFO order, and are only
            attempted after checking dynamic routes and sinks.

        directory (Union[str, pathlib.Path]): The source directory from which to
            serve files. Must be an absolute path.
        downloadable (bool): Set to ``True`` to include a
            Content-Disposition header in the response. The "filename"
            directive is simply set to the name of the requested file.
        fallback_filename (str): Fallback filename used when the requested file
            is not found. Can be a relative path inside the prefix folder or
            any valid absolute path.

            Note:
                If the fallback file is served instead of the requested file,
                the response Content-Type header, as well as the
                Content-Disposition header (provided it was requested with the
                `downloadable` parameter described above), are derived from the
                fallback filename, as opposed to the requested filename.
    """

    # NOTE(kgriffs): Don't allow control characters and reserved chars
    _DISALLOWED_CHARS_PATTERN: ClassVar[Pattern[str]] = re.compile(
        '[\x00-\x1f\x80-\x9f\ufffd~?<>:*|\'"]'
    )

    # NOTE(vytas): Match the behavior of the underlying os.path.normpath.
    _DISALLOWED_NORMALIZED_PREFIXES: ClassVar[Tuple[str, ...]] = (
        '..' + os.path.sep,
        os.path.sep,
    )

    # NOTE(kgriffs): If somehow an executable code exploit is triggerable, this
    # minimizes how much can be included in the payload.
    _MAX_NON_PREFIXED_LEN: ClassVar[int] = 512

    def __init__(
        self,
        prefix: str,
        directory: Union[str, Path],
        downloadable: bool = False,
        fallback_filename: Optional[str] = None,
    ) -> None:
        if not prefix.startswith('/'):
            raise ValueError("prefix must start with '/'")

        self._directory = os.path.normpath(directory)
        if not os.path.isabs(self._directory):
            raise ValueError('directory must be an absolute path')

        if fallback_filename is None:
            self._fallback_filename = None
        else:
            self._fallback_filename = os.path.normpath(
                os.path.join(self._directory, fallback_filename)
            )
            if not os.path.isfile(self._fallback_filename):
                raise ValueError('fallback_filename is not a file')

        # NOTE(kgriffs): Ensure it ends with a path separator to ensure
        # we only match on the complete segment. Don't raise an error
        # because most people won't expect to have to append a slash.
        if not prefix.endswith('/'):
            prefix += '/'

        self._prefix = prefix
        self._downloadable = downloadable

    def match(self, path: str) -> bool:
        """Check whether the given path matches this route."""
        if self._fallback_filename is None:
            return path.startswith(self._prefix)
        return path.startswith(self._prefix) or path == self._prefix[:-1]

    def __call__(self, req: Request, resp: Response, **kw: Any) -> None:
        """Resource responder for this route."""
        assert not kw
        if req.method == 'OPTIONS':
            # it's likely a CORS request. Set the allow header to the appropriate value.
            resp.set_header('Allow', 'GET')
            resp.set_header('Content-Length', '0')
            return

        without_prefix = req.path[len(self._prefix) :]

        # NOTE(kgriffs): Check surrounding whitespace and strip trailing
        # periods, which are illegal on windows
        # NOTE(CaselIT): An empty filename is allowed when fallback_filename is provided
        if (
            not (without_prefix or self._fallback_filename is not None)
            or without_prefix.strip().rstrip('.') != without_prefix
            or self._DISALLOWED_CHARS_PATTERN.search(without_prefix)
            or '\\' in without_prefix
            or '//' in without_prefix
            or len(without_prefix) > self._MAX_NON_PREFIXED_LEN
        ):
            raise falcon.HTTPNotFound()

        normalized = os.path.normpath(without_prefix)

        if normalized.startswith(self._DISALLOWED_NORMALIZED_PREFIXES):
            raise falcon.HTTPNotFound()

        file_path = os.path.join(self._directory, normalized)

        # NOTE(kgriffs): Final sanity-check just to be safe. This check
        # should never succeed, but this should guard against us having
        # overlooked something.
        if '..' in file_path or not file_path.startswith(self._directory):
            raise falcon.HTTPNotFound()

        if self._fallback_filename is None:
            fh, st = _open_file(file_path)
        else:
            try:
                fh, st = _open_file(file_path)
            except falcon.HTTPNotFound:
                fh, st = _open_file(self._fallback_filename)
                file_path = self._fallback_filename

        etag = f'{int(st.st_mtime):x}-{st.st_size:x}'
        resp.etag = etag

        last_modified = datetime.fromtimestamp(st.st_mtime, timezone.utc)
        # NOTE(vytas): Strip the microsecond part because that is not reflected
        #   in HTTP date, and when the client passes a previous value via
        #   If-Modified-Since, it will look as if our copy is ostensibly newer.
        last_modified = last_modified.replace(microsecond=0)
        resp.last_modified = last_modified

        if _is_not_modified(req, etag, last_modified):
            fh.close()
            resp.status = falcon.HTTP_304
            return

        req_range = req.range if req.range_unit == 'bytes' else None
        try:
            stream, length, content_range = _set_range(fh, st, req_range)
        except IOError:
            fh.close()
            raise falcon.HTTPNotFound()

        resp.set_stream(stream, length)
        suffix = os.path.splitext(file_path)[1]
        resp.content_type = resp.options.static_media_types.get(
            suffix, 'application/octet-stream'
        )
        resp.accept_ranges = 'bytes'

        if self._downloadable:
            resp.downloadable_as = os.path.basename(file_path)
        if content_range:
            resp.status = falcon.HTTP_206
            resp.content_range = content_range


class StaticRouteAsync(StaticRoute):
    """Subclass of StaticRoute with modifications to support ASGI apps."""

    async def __call__(  # type: ignore[override]
        self,
        req: asgi.Request,
        resp: asgi.Response,
        ws: Optional[asgi.WebSocket] = None,
        **kw: Any,
    ) -> None:
        if ws is not None:
            raise falcon.HTTPBadRequest()

        super().__call__(req, resp, **kw)
        if resp.stream is not None:  # None when in an option request
            # NOTE(kgriffs): Fixup resp.stream so that it is non-blocking
            resp.stream = _AsyncFileReader(resp.stream)  # type: ignore[assignment,arg-type]


class _AsyncFileReader:
    """Adapts a standard file I/O object so that reads are non-blocking."""

    def __init__(self, file: IO[bytes]) -> None:
        self._file = file
        self._loop = asyncio.get_running_loop()

    async def read(self, size: int = -1) -> bytes:
        return await self._loop.run_in_executor(None, partial(self._file.read, size))

    async def close(self) -> None:
        await self._loop.run_in_executor(None, self._file.close)
