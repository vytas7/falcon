import pytest

from falcon._protocols import _http11

SINGLE_REQUESTS = (
    ('simple GET', b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n'),
    (
        'GET with single query param',
        b'GET /search?q=falcon HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'GET with multiple query params',
        b'GET /api/items?sort=asc&page=2&limit=25 HTTP/1.1\r\n'
        b'Host: api.example.com\r\n\r\n',
    ),
    (
        'GET with percent-encoded path segment',
        b'GET /path/with%20spaces/and%2Fslash HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'GET with percent-encoded query value',
        b'GET /search?q=hello%20world&lang=en HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'GET with path containing dots, underscores, and hyphens',
        b'GET /v1/my_resource/some-id/file.json HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'GET with tilde and sub-delimiters in path',
        b'GET /~user/profile HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'DELETE with path',
        b'DELETE /api/v2/items/42 HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'HEAD request',
        b'HEAD /resource HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'OPTIONS asterisk-form',
        b'OPTIONS * HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'OPTIONS with path',
        b'OPTIONS /api/v1/ HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'POST with body',
        b'POST /submit HTTP/1.1\r\n'
        b'Host: localhost\r\n'
        b'Content-Type: application/x-www-form-urlencoded\r\n'
        b'Content-Length: 19\r\n'
        b'\r\n'
        b'username=alice&x=42',
    ),
    (
        'PUT with JSON body',
        b'PUT /api/items/7 HTTP/1.1\r\n'
        b'Host: localhost\r\n'
        b'Content-Type: application/json\r\n'
        b'Content-Length: 16\r\n'
        b'\r\n'
        b'{"name": "thing"}',
    ),
    (
        'PATCH with body',
        b'PATCH /api/items/7 HTTP/1.1\r\n'
        b'Host: localhost\r\n'
        b'Content-Type: application/merge-patch+json\r\n'
        b'Content-Length: 15\r\n'
        b'\r\n'
        b'{"active": true}',
    ),
    (
        'POST with empty body (Content-Length: 0)',
        b'POST /api/items HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\n\r\n',
    ),
)

BAD_REQUESTS = (
    (
        'invalid request line (too many spaces #1)',
        b'GET  /  HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'invalid request line (too many spaces #2)',
        b'GET /  HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    # Invalid HTTP verbs (RFC 9110 §9.1 / §5.6.2 token rules)
    (
        'method contains "(" (delimiter, forbidden in token)',
        b'GE(T / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'method contains ")" (delimiter, forbidden in token)',
        b'GE)T / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'method contains ":" (delimiter, forbidden in token)',
        b'GE:T / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'method contains "/" (delimiter, forbidden in token)',
        b'GE/T / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'method contains "@" (delimiter, forbidden in token)',
        b'GE@T / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'method contains "[" (delimiter, forbidden in token)',
        b'GE[T / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'method contains "\\" (delimiter, forbidden in token)',
        b'GE\\T / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'method contains "{" (delimiter, forbidden in token)',
        b'GE{T / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'method contains "<" (delimiter, forbidden in token)',
        b'GE<T / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'method contains "," (delimiter, forbidden in token)',
        b'GE,T / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'method contains "?" (delimiter, forbidden in token)',
        b'GE?T / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'method contains NUL (control character, forbidden in token)',
        b'GE\x00T / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'method contains DEL (control character, forbidden in token)',
        b'GE\x7fT / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'method contains tab (whitespace, forbidden in token)',
        b'GE\tT / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'empty method',
        b' / HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    # Invalid request targets
    (
        'unencoded space in request target',
        b'GET /path with spaces HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'unencoded "[" in request target (must be percent-encoded)',
        b'GET /path[0] HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'unencoded "]" in request target (must be percent-encoded)',
        b'GET /path]0[ HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'NUL byte in request target',
        b'GET /path\x00here HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'tab in request target',
        b'GET /path\there HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'fragment identifier in request target (client must not send #fragment)',
        b'GET /path#section HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    # Invalid request line structure
    (
        'tab used as separator instead of SP',
        b'GET\t/\tHTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'missing request target (only method and version)',
        b'GET HTTP/1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'missing HTTP version',
        b'GET /\r\nHost: localhost\r\n\r\n',
    ),
    (
        'malformed HTTP version: missing version numbers',
        b'GET / HTTP/\r\nHost: localhost\r\n\r\n',
    ),
    (
        'malformed HTTP version: non-numeric minor version',
        b'GET / HTTP/1.X\r\nHost: localhost\r\n\r\n',
    ),
    (
        'malformed HTTP version: extra version component',
        b'GET / HTTP/1.1.1\r\nHost: localhost\r\n\r\n',
    ),
    (
        'malformed HTTP version: no dot separator',
        b'GET / HTTP/11\r\nHost: localhost\r\n\r\n',
    ),
    (
        'malformed HTTP version: wrong scheme',
        b'GET / HTTPS/1.1\r\nHost: localhost\r\n\r\n',
    ),
    # Invalid header field names (RFC 9110 §5.1 / §5.6.2 token rules)
    (
        'header name contains space (whitespace, forbidden in token)',
        b'GET / HTTP/1.1\r\nContent Type: text/html\r\n\r\n',
    ),
    (
        'header name contains NUL (control character, forbidden in token)',
        b'GET / HTTP/1.1\r\nContent\x00Type: text/html\r\n\r\n',
    ),
    (
        'header name contains DEL (control character, forbidden in token)',
        b'GET / HTTP/1.1\r\nContent\x7fType: text/html\r\n\r\n',
    ),
    (
        'header name contains "(" (delimiter, forbidden in token)',
        b'GET / HTTP/1.1\r\n(Bad-Header): value\r\n\r\n',
    ),
    # Invalid header field values (RFC 9110 §5.5)
    (
        'header value contains NUL byte',
        b'GET / HTTP/1.1\r\nContent-Type: text/\x00html\r\n\r\n',
    ),
    (
        'header value contains DEL byte',
        b'GET / HTTP/1.1\r\nContent-Type: text/\x7fhtml\r\n\r\n',
    ),
    (
        'header value contains bare CR',
        b'GET / HTTP/1.1\r\nContent-Type: text/\rhtml\r\n\r\n',
    ),
    (
        'header value contains bare LF',
        b'GET / HTTP/1.1\r\nContent-Type: text/\nhtml\r\n\r\n',
    ),
)

UNSUPPORTED_HTTP_VERSION_REQUESTS = (
    (
        'HTTP/2 is not supported (yet)',
        b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n',
    ),
    ('HTTP/1.0', b'GET /index.html HTTP/1.0\r\n\r\n'),
    ('HTTP/0.9', b'GET /index.html HTTP/0.9\r\n\r\n'),
    ('HTTP/1.2 (hypothetical)', b'GET / HTTP/1.2\r\nHost: localhost\r\n\r\n'),
    (
        'HTTP/3.0 (QUIC-based, not HTTP/1.1)',
        b'GET / HTTP/3.0\r\nHost: localhost\r\n\r\n',
    ),
)


@pytest.mark.parametrize(
    'data',
    [tc[1] for tc in SINGLE_REQUESTS],
    ids=[tc[0] for tc in SINGLE_REQUESTS],
)
def test_simple_request(data):
    headers_block, _, _ = data.partition(b'\r\n\r\n')
    _http11._parse_headers_block(data)


@pytest.mark.parametrize(
    'data', [tc[1] for tc in BAD_REQUESTS], ids=[tc[0] for tc in BAD_REQUESTS]
)
def test_bad_request(data):
    headers_block, _, _ = data.partition(b'\r\n\r\n')

    with pytest.raises(ValueError):
        _http11._parse_headers_block(data)


@pytest.mark.parametrize(
    'data',
    [tc[1] for tc in UNSUPPORTED_HTTP_VERSION_REQUESTS],
    ids=[tc[0] for tc in UNSUPPORTED_HTTP_VERSION_REQUESTS],
)
def test_unsupported_http_version(data):
    headers_block, _, _ = data.partition(b'\r\n\r\n')

    with pytest.raises(ValueError):
        _http11._parse_headers_block(data)
