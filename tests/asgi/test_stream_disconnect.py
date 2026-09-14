import asyncio

import pytest

from falcon import testing
from falcon.asgi import App
from falcon.asgi import SSEvent

CHUNKS = [b'chunk %d\n' % i for i in range(10)]

STREAM_KINDS = ('generator', 'file', 'iterator', 'iterator-close')

EXPECTED_CLOSE = {
    'generator': ['finally'],
    'file': ['close'],
    'iterator': ['aclose'],
    'iterator-close': ['close'],
}


class ASGIConnection:
    """Simulated ASGI server connection with fine-grained disconnect control."""

    def __init__(
        self,
        request_events=None,
        disconnect_after=None,
        raise_after=None,
        cancel_after=None,
    ):
        if request_events is None:
            request_events = [{'type': 'http.request', 'body': b''}]

        self.request_events = list(request_events)
        self.disconnect_after = disconnect_after
        self.raise_after = raise_after
        self.cancel_after = cancel_after
        self.task = None

        self.events = []
        self.receive_count = 0
        self.disconnect_delivered = False
        self._disconnected = asyncio.Event()

    @property
    def body_chunks(self):
        return [
            event.get('body', b'')
            for event in self.events
            if event['type'] == 'http.response.body' and event.get('more_body')
        ]

    @property
    def eof_sent(self):
        return bool(self.events) and self.events[-1] == {'type': 'http.response.body'}

    async def receive(self):
        self.receive_count += 1
        if self.request_events:
            return self.request_events.pop(0)

        await self._disconnected.wait()
        self.disconnect_delivered = True
        return {'type': 'http.disconnect'}

    async def send(self, event):
        more_body = event['type'] == 'http.response.body' and event.get('more_body')

        if more_body and self.raise_after is not None:
            if len(self.body_chunks) >= self.raise_after:
                raise ConnectionResetError('the client has disconnected')

        self.events.append(event)

        if more_body and len(self.body_chunks) == self.cancel_after:
            # Simulate a server that cancels the app task upon disconnect.
            self.task.cancel()
            await asyncio.sleep(0)

        if more_body and len(self.body_chunks) == self.disconnect_after:
            self._disconnected.set()

            # Give the disconnect watcher (if any) a chance to run.
            for _ in range(5):
                await asyncio.sleep(0)


class FileLike:
    def __init__(self, owner, chunks):
        self._owner = owner
        self._chunks = list(chunks)

    async def read(self, size):
        if not self._chunks:
            return b''

        self._owner.yielded += 1
        return self._chunks.pop(0)

    async def close(self):
        self._owner.closed.append('close')


class AsyncIteratorWithAclose:
    def __init__(self, owner, chunks):
        self._owner = owner
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration

        self._owner.yielded += 1
        return self._chunks.pop(0)

    async def aclose(self):
        self._owner.closed.append('aclose')


class AsyncIteratorWithCloseAndAclose(AsyncIteratorWithAclose):
    async def close(self):
        self._owner.closed.append('close')


class NonBlockingStream:
    def __init__(self, results):
        self._results = list(results)

    async def read(self, size):
        return self._results.pop(0)


class StreamResource:
    def __init__(self):
        self.callback_called = False
        self.closed = []
        self.request_body = None
        self.yielded = 0

    async def _on_complete(self):
        self.callback_called = True

    def _create_stream(self, kind):
        if kind == 'generator':

            async def generator():
                try:
                    for chunk in CHUNKS:
                        self.yielded += 1
                        yield chunk
                finally:
                    self.closed.append('finally')

            return generator()

        if kind == 'file':
            return FileLike(self, CHUNKS)

        if kind == 'iterator':
            return AsyncIteratorWithAclose(self, CHUNKS)

        return AsyncIteratorWithCloseAndAclose(self, CHUNKS)

    async def on_get(self, req, resp, kind):
        resp.schedule(self._on_complete)
        resp.stream = self._create_stream(kind)

    async def on_post(self, req, resp, kind):
        self.request_body = await req.stream.read()
        await self.on_get(req, resp, kind)

    async def on_put(self, req, resp, kind):
        # The request body is deliberately left unread here.
        await self.on_get(req, resp, kind)


class SSEResource:
    def __init__(self):
        self.callback_called = False
        self.yielded = 0

    async def _on_complete(self):
        self.callback_called = True

    async def on_get(self, req, resp):
        async def emitter():
            for _ in range(10):
                self.yielded += 1
                yield SSEvent(data=b'whassup')

        resp.schedule(self._on_complete)
        resp.sse = emitter()

    on_put = on_get


@pytest.fixture
def resource():
    return StreamResource()


@pytest.fixture
def sse_resource():
    return SSEResource()


@pytest.fixture
def app(resource, sse_resource):
    app = App()
    app.add_route('/stream/{kind}', resource)
    app.add_route('/sse', sse_resource)
    return app


async def simulate(app, connection, path, method='GET', content_length=None):
    scope = testing.create_scope(
        path=path, method=method, content_length=content_length
    )
    await app(scope, connection.receive, connection.send)

    # Let scheduled callbacks run.
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.parametrize('kind', STREAM_KINDS)
async def test_stream_complete(app, resource, kind):
    connection = ASGIConnection()
    await simulate(app, connection, f'/stream/{kind}')

    assert connection.body_chunks == CHUNKS
    assert connection.eof_sent
    assert resource.closed == EXPECTED_CLOSE[kind]
    assert resource.callback_called
    assert not connection.disconnect_delivered


@pytest.mark.parametrize('kind', STREAM_KINDS)
async def test_stream_client_disconnects(app, resource, kind):
    connection = ASGIConnection(disconnect_after=3)
    await simulate(app, connection, f'/stream/{kind}')

    assert connection.disconnect_delivered
    assert connection.body_chunks == CHUNKS[:3]
    assert not connection.eof_sent
    assert resource.yielded == 3
    assert resource.closed == EXPECTED_CLOSE[kind]
    assert resource.callback_called


@pytest.mark.parametrize('kind', STREAM_KINDS)
async def test_stream_send_raises_oserror(app, resource, kind):
    connection = ASGIConnection(raise_after=3)
    await simulate(app, connection, f'/stream/{kind}')

    assert connection.body_chunks == CHUNKS[:3]
    assert not connection.eof_sent
    # The fourth chunk was produced, but it could not be sent.
    assert resource.yielded == 4
    assert resource.closed == EXPECTED_CLOSE[kind]
    assert resource.callback_called


@pytest.mark.parametrize('kind', STREAM_KINDS)
async def test_stream_request_body_pending(app, resource, kind):
    connection = ASGIConnection(
        request_events=[{'type': 'http.request', 'body': b'Hello', 'more_body': True}],
        disconnect_after=3,
    )
    await simulate(app, connection, f'/stream/{kind}', method='PUT')

    # No watcher is started since the app might still want to read the
    # rest of the request body.
    assert connection.receive_count == 1
    assert connection.body_chunks == CHUNKS
    assert connection.eof_sent
    assert resource.closed == EXPECTED_CLOSE[kind]
    assert resource.callback_called


async def test_stream_request_body_read(app, resource):
    connection = ASGIConnection(
        request_events=[
            {'type': 'http.request', 'body': b'Hello, ', 'more_body': True},
            {'type': 'http.request', 'body': b'World!', 'more_body': True},
            {'type': 'http.request', 'body': b''},
        ],
        disconnect_after=3,
    )
    await simulate(
        app, connection, '/stream/generator', method='POST', content_length=13
    )

    assert resource.request_body == b'Hello, World!'
    # The watcher has received the trailing empty http.request event,
    # followed by http.disconnect.
    assert connection.receive_count == 4
    assert connection.disconnect_delivered
    assert connection.body_chunks == CHUNKS[:3]
    assert not connection.eof_sent
    assert resource.closed == ['finally']


async def test_stream_read_returns_none():
    class NonBlockingResource:
        async def on_get(self, req, resp):
            resp.stream = NonBlockingStream([b'Hello', None, b', World!', b''])

    app = App()
    app.add_route('/', NonBlockingResource())

    connection = ASGIConnection()
    await simulate(app, connection, '/')

    assert connection.body_chunks == [b'Hello', b'', b', World!']
    assert connection.eof_sent


async def test_sse_client_disconnects(app, sse_resource):
    connection = ASGIConnection(disconnect_after=3)
    await simulate(app, connection, '/sse')

    assert connection.disconnect_delivered
    assert connection.body_chunks == [b'data: whassup\n\n'] * 3
    assert not connection.eof_sent
    assert sse_resource.yielded == 3
    assert sse_resource.callback_called


async def test_sse_request_body_pending(app, sse_resource):
    connection = ASGIConnection(
        request_events=[{'type': 'http.request', 'body': b'Hello', 'more_body': True}],
        disconnect_after=3,
    )
    await simulate(app, connection, '/sse', method='PUT')

    # SSE always watches for disconnects, regardless of the request body.
    assert connection.disconnect_delivered
    assert connection.body_chunks == [b'data: whassup\n\n'] * 3
    assert not connection.eof_sent


async def test_sse_send_raises_oserror(app, sse_resource):
    connection = ASGIConnection(raise_after=3)
    await simulate(app, connection, '/sse')

    assert connection.body_chunks == [b'data: whassup\n\n'] * 3
    assert not connection.eof_sent
    assert sse_resource.yielded == 4
    assert sse_resource.callback_called


async def simulate_task(app, connection, path):
    scope = testing.create_scope(path=path)
    connection.task = asyncio.create_task(
        app(scope, connection.receive, connection.send)
    )
    await connection.task


@pytest.mark.parametrize('kind', STREAM_KINDS)
async def test_stream_server_cancels_app(app, resource, kind):
    connection = ASGIConnection(cancel_after=3)

    with pytest.raises(asyncio.CancelledError):
        await simulate_task(app, connection, f'/stream/{kind}')

    assert connection.body_chunks == CHUNKS[:3]
    assert not connection.eof_sent
    assert resource.closed == EXPECTED_CLOSE[kind]


async def test_sse_server_cancels_app(app, sse_resource):
    connection = ASGIConnection(cancel_after=3)

    with pytest.raises(asyncio.CancelledError):
        await simulate_task(app, connection, '/sse')

    assert connection.body_chunks == [b'data: whassup\n\n'] * 3
    assert not connection.eof_sent


@pytest.mark.parametrize('sse', [False, True])
async def test_server_cancels_app_during_cleanup(sse):
    connection = ASGIConnection()

    async def emitter():
        yield SSEvent(data=b'whassup') if sse else b'whassup'

        # Cancel the app task right when it is cleaning up the disconnect
        # watcher; the cancellation must not be swallowed.
        asyncio.get_running_loop().call_soon(connection.task.cancel)

    class EmitterResource:
        async def on_get(self, req, resp):
            if sse:
                resp.sse = emitter()
            else:
                resp.stream = emitter()

    app = App()
    app.add_route('/', EmitterResource())

    with pytest.raises(asyncio.CancelledError):
        await simulate_task(app, connection, '/')

    assert len(connection.body_chunks) == 1
    assert not connection.eof_sent
