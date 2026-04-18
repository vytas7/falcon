from __future__ import annotations

from typing import Any

from falcon.otel import _semconv


def attrs_from_wsgi_environ(environ: dict[str, Any]) -> dict[str, Any]:
    """Extract pre-routing OTEL HTTP span attributes from a WSGI environ."""
    attrs: dict[str, Any] = {}

    method = environ.get('REQUEST_METHOD')
    if method is not None:
        attrs[_semconv.HTTP_REQUEST_METHOD] = method

    path = environ.get('PATH_INFO') or '/'
    attrs[_semconv.URL_PATH] = path

    query = environ.get('QUERY_STRING')
    if query:
        attrs[_semconv.URL_QUERY] = query

    scheme = environ.get('wsgi.url_scheme')
    if scheme is not None:
        attrs[_semconv.URL_SCHEME] = scheme

    server_name = environ.get('SERVER_NAME')
    if server_name:
        attrs[_semconv.SERVER_ADDRESS] = server_name

    server_port = environ.get('SERVER_PORT')
    if server_port:
        try:
            attrs[_semconv.SERVER_PORT] = int(server_port)
        except (TypeError, ValueError):
            pass

    client_addr = environ.get('REMOTE_ADDR')
    if client_addr:
        attrs[_semconv.CLIENT_ADDRESS] = client_addr

    user_agent = environ.get('HTTP_USER_AGENT')
    if user_agent:
        attrs[_semconv.USER_AGENT_ORIGINAL] = user_agent

    proto = environ.get('SERVER_PROTOCOL')
    if proto and proto.startswith('HTTP/'):
        attrs[_semconv.NETWORK_PROTOCOL_VERSION] = proto[5:]

    return attrs


def attrs_from_asgi_scope(scope: dict[str, Any]) -> dict[str, Any]:
    """Extract pre-routing OTEL HTTP span attributes from an ASGI scope."""
    attrs: dict[str, Any] = {}

    method = scope.get('method')
    if method is not None:
        attrs[_semconv.HTTP_REQUEST_METHOD] = method

    attrs[_semconv.URL_PATH] = scope.get('path') or '/'

    query = scope.get('query_string') or b''
    if query:
        attrs[_semconv.URL_QUERY] = (
            query.decode('latin-1') if isinstance(query, (bytes, bytearray)) else query
        )

    scheme = scope.get('scheme')
    if scheme is not None:
        attrs[_semconv.URL_SCHEME] = scheme

    server = scope.get('server')
    if server:
        host, port = server
        if host:
            attrs[_semconv.SERVER_ADDRESS] = host
        if port is not None:
            attrs[_semconv.SERVER_PORT] = port

    client = scope.get('client')
    if client:
        host, port = client
        if host:
            attrs[_semconv.CLIENT_ADDRESS] = host
        if port is not None:
            attrs[_semconv.CLIENT_PORT] = port

    http_version = scope.get('http_version')
    if http_version:
        attrs[_semconv.NETWORK_PROTOCOL_VERSION] = http_version

    for raw_name, raw_value in scope.get('headers') or ():
        if raw_name == b'user-agent':
            try:
                attrs[_semconv.USER_AGENT_ORIGINAL] = raw_value.decode('latin-1')
            except AttributeError:
                attrs[_semconv.USER_AGENT_ORIGINAL] = raw_value
            break

    return attrs


class WSGICarrierGetter:
    """Duck-typed OTEL ``Getter`` for a WSGI environ carrier.

    Implements ``.get(carrier, key)`` and ``.keys(carrier)`` so that
    ``opentelemetry.propagate.extract`` can read HTTP headers out of the
    ``HTTP_*`` entries of a WSGI environ dict.
    """

    def get(self, carrier: dict[str, Any], key: str) -> list[str] | None:
        env_key = 'HTTP_' + key.upper().replace('-', '_')
        value = carrier.get(env_key)
        if value is None:
            return None
        return [value]

    def keys(self, carrier: dict[str, Any]) -> list[str]:
        return [
            name[5:].replace('_', '-').lower()
            for name in carrier
            if name.startswith('HTTP_')
        ]


class ASGICarrierGetter:
    """Duck-typed OTEL ``Getter`` for an ASGI scope carrier."""

    def get(self, carrier: dict[str, Any], key: str) -> list[str] | None:
        target = key.lower().encode('latin-1')
        found = [
            raw_value.decode('latin-1')
            for raw_name, raw_value in carrier.get('headers') or ()
            if raw_name.lower() == target
        ]
        return found or None

    def keys(self, carrier: dict[str, Any]) -> list[str]:
        return [
            raw_name.decode('latin-1') for raw_name, _ in carrier.get('headers') or ()
        ]
