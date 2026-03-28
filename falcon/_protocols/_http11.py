import re
# import timeit

_STATUS_LINE_PATTERN = re.compile(rb'^([a-zA-Z0-9]+) ([\?a-zA-Z0-9=/-]+) HTTP/1.1$')


def _parse_status_line(line: bytes) -> tuple[bytes, bytes]:
    match = _STATUS_LINE_PATTERN.match(line)
    if match is None:
        raise ValueError('invalid status line')
    return match.groups()  # type: ignore[return-value]


def _parse_headers(data: bytes) -> dict[bytes, bytes]:
    result: dict[bytes, bytes] = {}

    for header in data.split(b'\r\n'):
        name, _, value = header.partition(b':')
        value = value.strip()
        if name and value:
            result[name.lower()] = value

    return result


class _HTTP11Protocol:
    def __init__(self) -> None:
        self._stage = 0
        self._until = '\r\n'
        self._find_start = 0
        self._buffer = bytearray()

        self.output: list[bytes] = []

    def receive(self, data: bytes) -> list:
        self._buffer.extend(data)

        pos = self._buffer.find(self._until, self._find_start)
        if pos < 0:
            self._find_start = max(0, len(self._buffer) - len(self._until))
            return []

        data = self._buffer[:pos]
        self._buffer = self._buffer[pos + len(self._until) :]


# def test_perf() -> None:
#     print(
#         timeit.repeat(lambda: _parse_status_line(b'GET /a/b?q=1 HTTP/1.1')))


def test_line() -> None:
    print(_parse_status_line(b'GET /a/b?q=1 HTTP/1.1'))
    print(_parse_status_line(b'DELETE /a/b/ccc HTTP/1.1'))
    # print(_parse_status_line(b'PATH * HTTP/2'))


def test_headers() -> None:
    print(
        _parse_headers(
            b'Accept: */*\r\n'
            b'Connection: keep-alive\r\n'
            b'Host: localhost\r\n'
            b'User-Agent: test/1.3.3.7'
        )
    )
