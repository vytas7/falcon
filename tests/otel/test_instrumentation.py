"""PoC tests for falcon.otel.Instrumentation.

App wiring is not yet part of Falcon core; for now we wrap the app with a
middleware-style callable so the tests can exercise ``instrument_wsgi`` /
``instrument_asgi`` through the real request path.
"""

from opentelemetry.trace import SpanKind
import pytest

import falcon
import falcon.asgi
from falcon.otel import _semconv
from falcon.otel import Instrumentation
import falcon.testing

TRACEPARENT = '00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01'
UPSTREAM_TRACE_ID = '0af7651916cd43dd8448eb211c80319c'


class Widgets:
    def on_get(self, req, resp, widget_id):
        resp.media = {'id': widget_id}

    def on_post(self, req, resp):
        resp.status = falcon.HTTP_201
        resp.media = {'ok': True}


class AsyncWidgets:
    async def on_get(self, req, resp, widget_id):
        resp.media = {'id': widget_id}

    async def on_post(self, req, resp):
        resp.status = falcon.HTTP_201
        resp.media = {'ok': True}


def _wsgi_wrap(app, instrumentation):
    def middleware(environ, start_response):
        with instrumentation.instrument_wsgi(environ):
            return app(environ, start_response)

    return middleware


def _asgi_wrap(app, instrumentation):
    async def middleware(scope, receive, send):
        if scope.get('type') != 'http':
            await app(scope, receive, send)
            return
        with instrumentation.instrument_asgi(scope):
            await app(scope, receive, send)

    return middleware


@pytest.fixture
def wsgi_client():
    app = falcon.App()
    app.add_route('/widgets/{widget_id:int}', Widgets())
    app.add_route('/widgets', Widgets())
    return falcon.testing.TestClient(_wsgi_wrap(app, Instrumentation()))


@pytest.fixture
def asgi_client():
    app = falcon.asgi.App()
    app.add_route('/widgets/{widget_id:int}', AsyncWidgets())
    app.add_route('/widgets', AsyncWidgets())
    return falcon.testing.TestClient(_asgi_wrap(app, Instrumentation()))


def test_wsgi_server_span(span_exporter, wsgi_client):
    response = wsgi_client.simulate_get('/widgets/42')
    assert response.status_code == 200

    (span,) = span_exporter.get_finished_spans()
    assert span.kind is SpanKind.SERVER
    assert span.parent is None
    assert span.attributes[_semconv.HTTP_REQUEST_METHOD] == 'GET'
    assert span.attributes[_semconv.URL_PATH] == '/widgets/42'
    assert span.attributes[_semconv.URL_SCHEME] == 'http'


def test_wsgi_propagates_incoming_traceparent(span_exporter, wsgi_client):
    response = wsgi_client.simulate_get(
        '/widgets/1', headers={'traceparent': TRACEPARENT}
    )
    assert response.status_code == 200

    (span,) = span_exporter.get_finished_spans()
    assert format(span.context.trace_id, '032x') == UPSTREAM_TRACE_ID
    assert span.parent is not None
    assert format(span.parent.trace_id, '032x') == UPSTREAM_TRACE_ID


def test_asgi_server_span(span_exporter, asgi_client):
    response = asgi_client.simulate_post('/widgets', json={'x': 1})
    assert response.status_code == 201

    (span,) = span_exporter.get_finished_spans()
    assert span.kind is SpanKind.SERVER
    assert span.attributes[_semconv.HTTP_REQUEST_METHOD] == 'POST'
    assert span.attributes[_semconv.URL_PATH] == '/widgets'


def test_asgi_propagates_incoming_traceparent(span_exporter, asgi_client):
    response = asgi_client.simulate_get(
        '/widgets/7', headers={'traceparent': TRACEPARENT}
    )
    assert response.status_code == 200

    (span,) = span_exporter.get_finished_spans()
    assert format(span.context.trace_id, '032x') == UPSTREAM_TRACE_ID
