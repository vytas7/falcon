import re

# import timeit

# RFC 9110 §5.6.2 token characters (method) and RFC 3986 URI characters (target).
# Method: tchar = ALPHA / DIGIT / "!" / "#" / "$" / "%" / "&" / "'" / "*" /
#                 "+" / "-" / "." / "^" / "_" / "`" / "|" / "~"
# Target: unreserved / pct-encoded / sub-delims / ":" / "@" / "/" / "?"
#         (brackets "[" / "]" must be percent-encoded; "#" starts a fragment
#         and must not appear in the request-target sent to the server)
_STATUS_LINE_PATTERN = re.compile(
    rb'^([a-zA-Z0-9!#$%&\'*+\-.^_`|~]+) ([a-zA-Z0-9/%?=&._~*:@!$\'()+,;-]+) HTTP/1\.1$'
)

# RFC 9110 §5.6.2: field-name = token (tchar+)
_FIELD_NAME_ALLOWED_CHARS = (
    b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&'*+-.^_`|~"
)
# RFC 9110 §5.5: field-value = *( SP / HTAB / VCHAR / obs-text )
# VCHAR = %x21-7E, obs-text = %x80-FF
_FIELD_VALUE_ALLOWED_CHARS = (
    b' \t' + bytes(range(0x21, 0x7F)) + bytes(range(0x80, 0x100))
)


def _parse_status_line(line: bytes) -> tuple[bytes, bytes]:
    match = _STATUS_LINE_PATTERN.match(line)
    if match is None:
        raise ValueError('invalid status line')
    return match.groups()  # type: ignore[return-value]


def _parse_headers(data: bytes) -> dict[bytes, bytes]:
    result: dict[bytes, bytes] = {}

    for header in data.split(b'\r\n'):
        if not header:
            break  # blank line signals end of headers section

        name, _, value = header.partition(b':')
        value = value.strip()

        if name.translate(None, _FIELD_NAME_ALLOWED_CHARS):
            raise ValueError('invalid field name')
        if value.translate(None, _FIELD_VALUE_ALLOWED_CHARS):
            raise ValueError('invalid field value')

        if name and value:
            result[name.lower()] = value

    return result


def _parse_headers_block(data: bytes) -> tuple[bytes, bytes, dict]:
    status_line, crlf, headers = data.partition(b'\r\n')

    if not crlf:
        raise ValueError('no HTTP status line found')

    return _parse_status_line(status_line) + (_parse_headers(headers),)


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
