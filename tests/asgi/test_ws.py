import asyncio
from collections import deque
from contextlib import nullcontext
import functools
import os

import pytest

import falcon
from falcon import media
from falcon import testing
from falcon.asgi import App
from falcon.asgi.ws import _WebSocketState as ServerWebSocketState
from falcon.asgi.ws import WebSocket
from falcon.asgi.ws import WebSocketOptions
from falcon.testing.helpers import _WebSocketState as ClientWebSocketState
from falcon.util.deprecation import DeprecatedWarning

try:
    import cbor2
except ImportError:
    cbor2 = None  # type: ignore[assignment]


try:
    import msgpack
except ImportError:
    msgpack = None


try:
    import rapidjson
except ImportError:
    rapidjson = None  # type: ignore[assignment]


# NOTE(kgriffs): We do not use codes defined in the framework because we
#   want to verify that the correct value is being used.
class CloseCode:
    NORMAL = 1000
    SERVER_ERROR = 1011
    FORBIDDEN = 3403
    NOT_FOUND = 3404


class EventType:
    WS_CONNECT = 'websocket.connect'
    WS_ACCEPT = 'websocket.accept'
    WS_RECEIVE = 'websocket.receive'
    WS_SEND = 'websocket.send'
    WS_DISCONNECT = 'websocket.disconnect'
    WS_CLOSE = 'websocket.close'


@pytest.fixture
def conductor():
    app = falcon.asgi.App()
    return testing.ASGIConductor(app)


@pytest.mark.parametrize('path', ['/ws/yes', '/ws/no'])
async def test_ws_not_accepted(path, conductor):
    class SomeResource:
        def __init__(self):
            self.called = False
            self.caught_unsupported_error = False
            self.caught_receive_not_allowed = False
            self.caught_operation_not_allowed = False

        async def on_websocket(self, req, ws, explicit):
            try:
                req.stream
            except falcon.UnsupportedError:
                self.caught_unsupported_error = True

            self.called = True

            try:
                await ws.receive_text()
            except falcon.OperationNotAllowed:
                self.caught_receive_not_allowed = True

            if explicit == 'yes':
                await ws.close()

                # NOTE(kgriffs): This verifies that closing
                #   an already-closed WebSocket is a no-op.
                await ws.close()

                try:
                    await ws.accept()
                except falcon.OperationNotAllowed:
                    self.caught_operation_not_allowed = True

    resource = SomeResource()
    conductor.app.add_route('/ws/{explicit}', resource)

    # NOTE(kgriffs): declaring the 'c' variable is not strictly necessary
    #   because it is just 'conductor', but it probably wastes fewer brain
    #   cycles to just use the same pattern whether or not the conductor
    #   object is pre-instantiated.
    async with conductor as c:
        assert c is conductor

        with pytest.raises(falcon.WebSocketDisconnected) as exc_info:
            async with c.simulate_ws(path):
                pass

        assert resource.called
        assert resource.caught_receive_not_allowed
        assert resource.caught_unsupported_error
        assert exc_info.value.code == CloseCode.FORBIDDEN

        if 'yes' in path:
            assert resource.caught_operation_not_allowed


@pytest.mark.slow
async def test_echo():  # noqa: C901
    consumer_sleep = 0.01
    producer_loop = 10
    producer_sleep_factor = consumer_sleep / (producer_loop / 2)

    class Resource:
        def __init__(self):
            self.caught_operation_not_allowed = False

        async def on_websocket(self, req, ws, p1, p2, injected):
            # NOTE(kgriffs): Normally the receiver task is not started
            #   until the websocket is started. But here we start it
            #   first in order to simulate a potential race condition
            #   that ASGIWebSocketSimulator._emit() guards against,
            #   in case it ever arises due to the way the target ASGI
            #   app may be implemented.
            ws._buffered_receiver.start()

            await asyncio.sleep(0)

            if ws.unaccepted:
                await ws.accept()

            try:
                await ws.accept()
            except falcon.OperationNotAllowed:
                self.caught_operation_not_allowed = True

            if ws.ready:
                await ws.send_text(f'{p1}:{p2}:{req.context.message}:{injected}')

            messages = deque()
            sink_task = asyncio.create_task(self._sink(ws, messages))

            while not sink_task.done():
                if not messages:
                    await asyncio.sleep(0)
                    continue

                try:
                    await ws.send_text(messages.popleft())
                except falcon.WebSocketDisconnected:
                    break

            sink_task.cancel()
            try:
                await sink_task
            except asyncio.CancelledError:
                pass

        async def _sink(self, ws, messages):
            while True:
                # NOTE(kgriffs): Throttle slightly to allow messages to
                #   fill up the buffer.
                await asyncio.sleep(consumer_sleep)

                try:
                    message = await ws.receive_text()
                except falcon.WebSocketDisconnected:
                    break

                if message != 'ignore':
                    messages.append(message)

    class MiddlewareA:
        async def process_resource_ws(self, req, ws, resource, params):
            assert isinstance(resource, Resource)
            assert isinstance(ws, falcon.asgi.WebSocket)
            params['injected'] = '42'

    class MiddlewareB:
        async def process_request_ws(self, req, ws):
            assert isinstance(ws, falcon.asgi.WebSocket)
            req.context.message = 'hello'

    resource = Resource()

    # NOTE(kgriffs): The two methods are split across different middleware
    #   classes so that we can test code paths that check for the existence
    #   of one WebSocket middleware method vs the other, and also so that
    #   we can make sure both the kwarg and the add_middleware() paths
    #   succeed.
    app = App(middleware=MiddlewareA())
    app.add_middleware(MiddlewareB())

    app.add_route('/{p1}/{p2}', resource)

    async with testing.ASGIConductor(app) as c:
        # NOTE(vytas): Using the websocket() alias.
        async with c.websocket('/v1/v2', headers={}) as ws:
            assert (await ws.receive_text()) == 'v1:v2:hello:42'

            for i in range(producer_loop):
                message = (
                    str(i) if i else ''
                )  # Test round-tripping the empty string as well

                for i in range(100):
                    await ws.send_text('ignore')

                # NOTE(kgriffs): For part of the time, cause the buffer on the
                #   server side to fill up, and for the remainder of the time
                #   for the buffer to be empty and wait on the client for
                #   additional messages.
                await asyncio.sleep(i * producer_sleep_factor)

                await ws.send_text(message)
                assert (await ws.receive_text()) == message

            await ws.close()

            assert ws.closed
            assert ws.close_code == CloseCode.NORMAL

    assert resource.caught_operation_not_allowed


async def test_path_not_found(conductor):
    async with conductor as c:
        with pytest.raises(falcon.WebSocketDisconnected) as exc_info:
            async with c.simulate_ws():
                pass

        assert exc_info.value.code == CloseCode.NOT_FOUND


@pytest.mark.parametrize('clear_error_handlers', [True, False])
async def test_responder_raises_unhandled_error(clear_error_handlers, conductor):
    class SomeResource:
        def __init__(self):
            self.called = False

        async def on_websocket(self, req, ws, generic_error):
            self.called = True

            if generic_error == 'true':
                raise Exception('Oh snap!')

            # NOTE(kgriffs): This may not make a lot of sense to do, but the
            #   framework will try to do something reasonable with it by
            #   rejecting the WebSocket handshake and setting the close code
            #   to 3000 + falcon.util.http_status_to_code(error.status)
            raise falcon.HTTPUnprocessableEntity()

    resource = SomeResource()
    conductor.app.add_route('/{generic_error}', resource)

    if clear_error_handlers:
        # NOTE(kgriffs): This is required in order to cover a certain branch condition.
        conductor.app._error_handlers.clear()

        async with conductor as c:
            with pytest.raises(Exception) as exc_info:
                async with c.simulate_ws('/true'):
                    pass

            assert resource.called
            assert str(exc_info.value) == 'Oh snap!'

            resource.called = False

            with pytest.raises(falcon.HTTPUnprocessableEntity):
                async with c.simulate_ws('/false'):
                    pass

            assert resource.called
    else:
        async with conductor as c:
            with pytest.raises(falcon.WebSocketServerError) as exc_info:
                async with c.simulate_ws('/true'):
                    pass

            assert resource.called
            assert exc_info.value.code == 1011

            resource.called = False

            with pytest.raises(falcon.WebSocketDisconnected) as exc_info:
                async with c.simulate_ws('/false'):
                    pass

            assert resource.called
            assert exc_info.value.code == 3422


@pytest.mark.parametrize('direction', ['send', 'receive'])
@pytest.mark.parametrize('explicit_close_client', [True, False])
@pytest.mark.parametrize('explicit_close_server', [True, False])
async def test_client_disconnect_early(  # noqa: C901
    direction,
    explicit_close_client,
    explicit_close_server,
    conductor,
):
    sample_data = os.urandom(64 * 1024)

    class Resource:
        def __init__(self):
            self.data_received = asyncio.Event()
            self.times_called = 0
            self.data = None
            self.ws_ready = None
            self.ws_state = None
            self.ws_closed = None
            self.ws_client_close_code = None

        async def on_websocket(self, req, ws):
            self.times_called += 1

            await ws.accept()

            while True:
                try:
                    if direction == 'send':
                        await ws.send_data(sample_data)

                        if explicit_close_server:
                            await ws.close(4099)
                    else:
                        self.data = await ws.receive_data()

                        if explicit_close_server:
                            # NOTE(kgriffs): We call ws.receive_data() again here in
                            #   order to test coverage of the logic that handles
                            #   the case of a closed connection while waiting on
                            #   more data.
                            recv_task = asyncio.create_task(ws.receive_data())
                            # Ensure recv_task() has a chance to get ahead
                            await asyncio.sleep(0)
                            ws_close = ws.close(4099)
                            ws_close = asyncio.create_task(ws_close)
                            await asyncio.wait([recv_task, ws_close])

                        self.data_received.set()

                except falcon.WebSocketDisconnected as ex:
                    self.ws_ready = ws.ready
                    self.ws_client_close_code = ex.code
                    self.ws_state = ws._state
                    self.ws_closed = ws.closed
                    break

    resource = Resource()
    conductor.app.add_route('/', resource)

    disconnect_raised = False

    async with conductor as c:
        try:
            async with c.simulate_ws('/') as ws:
                if direction == 'send':
                    received_data = await ws.receive_data()
                    assert received_data == sample_data
                else:
                    await ws.send_data(sample_data)
                    await resource.data_received.wait()
                    assert resource.data == sample_data

                # NOTE(vytas): When testing the case where the server
                #   explicitly closes the connection, try to receive some data
                #   before closing from the client side (and potentially
                #   winning the async race of which side closes first).
                if explicit_close_server:
                    await ws.receive_data()

                if explicit_close_client:
                    await ws.close(4042)

        except falcon.WebSocketDisconnected as ex:
            disconnect_raised = True
            assert explicit_close_server
            assert ex.code == 4099

        if direction == 'send' and explicit_close_server:
            assert disconnect_raised

        code_expected = CloseCode.NORMAL

        if explicit_close_server:
            code_expected = 4099
        elif explicit_close_client:
            code_expected = 4042

        assert resource.ws_client_close_code == code_expected
        assert ws.close_code == code_expected

    assert resource.times_called == 1
    assert resource.ws_state == ServerWebSocketState.CLOSED
    assert resource.ws_closed
    assert resource.ws_ready is False


@pytest.mark.parametrize('custom_text', [True, False])
@pytest.mark.parametrize('custom_data', [True, False])
@pytest.mark.skipif(msgpack is None, reason='msgpack is required for this test')
async def test_media(custom_text, custom_data, conductor):  # NOQA: C901
    # TODO(kgriffs): Refactor to reduce McCabe score

    sample_doc = {
        'answer': 42,
        'runes': b'\xe1\x9a\xa0\xe1\x9b\x87\xe1\x9a\xbb'.decode(),
        'ascii': 'hello world',
    }

    sample_doc_bin = sample_doc.copy()
    sample_doc_bin['bits'] = os.urandom(32)
    sample_doc_bin['array'] = [0, 1, 2]

    class Resource:
        def __init__(self):
            self.finished = asyncio.Event()
            self.docs_received = []
            self.deserialize_error_count = 0

        async def on_websocket(self, req, ws):
            try:
                await ws.accept()

                await ws.send_media(sample_doc)
                self.docs_received.append(await ws.receive_media())
                await ws.send_media(sample_doc, falcon.WebSocketPayloadType.TEXT)
                self.docs_received.append(await ws.receive_media())

                await ws.send_media(sample_doc_bin, falcon.WebSocketPayloadType.BINARY)
                self.docs_received.append(await ws.receive_media())

                for __ in range(3):
                    try:
                        await ws.receive_media()
                    except ValueError:
                        self.deserialize_error_count += 1
            finally:
                self.finished.set()

    app = conductor.app

    resource = Resource()
    app.add_route('/', resource)

    if custom_text:
        if rapidjson is None:
            pytest.skip('rapidjson is required for this test')

        # Let's say we want to use a faster JSON library. You could also use this
        #   pattern to add serialization support for custom types that aren't
        #   normally JSON-serializable out of the box.
        class RapidJSONHandler(media.TextBaseHandlerWS):
            def serialize(self, media: object) -> str:
                return rapidjson.dumps(media, ensure_ascii=False)

            # The raw TEXT payload will be passed as a Unicode string
            def deserialize(self, payload: str) -> object:
                return rapidjson.loads(payload)

        app.ws_options.media_handlers[falcon.WebSocketPayloadType.TEXT] = (
            RapidJSONHandler()
        )

    if custom_data:
        if cbor2 is None:
            pytest.skip('cbor2 is required for this test')

        class CBORHandler(media.BinaryBaseHandlerWS):
            def serialize(self, media: object) -> bytes:
                return cbor2.dumps(media)

            # The raw BINARY payload will be passed as a byte string
            def deserialize(self, payload: bytes) -> object:
                return cbor2.loads(payload)

        app.ws_options.media_handlers[falcon.WebSocketPayloadType.BINARY] = (
            CBORHandler()
        )

    async with conductor as c:
        async with c.simulate_ws() as ws:
            for __ in range(2):
                doc = await ws.receive_json()
                await ws.send_json(doc)

            if custom_data:
                data = await ws.receive_data()
                cbor2.loads(data)  # NOTE(kgriffs): Validate serialization format
                await ws.send_data(data)
            else:
                doc = await ws.receive_msgpack()
                await ws.send_msgpack(doc)

            # NOTE(kgriffs): The first one will work, but we include it to
            #    ensure we aren't getting any false-positives.
            await ws.send_text('"DEADBEEF"')
            await ws.send_text('DEADBEEF')
            await ws.send_data(b'\xde\xad\xbe\xef')

            await resource.finished.wait()

    assert resource.deserialize_error_count == 2

    assert len(resource.docs_received) == 3
    assert resource.docs_received[0] == sample_doc

    expected = [sample_doc, sample_doc, sample_doc_bin]
    for doc, doc_expected in zip(resource.docs_received, expected):
        assert doc == doc_expected


@pytest.mark.parametrize('sample_data', [b'123', b'', b'\xe1\x9a\xa0\xe1', b'\0'])
async def test_send_receive_data(sample_data, conductor):
    class Resource:
        def __init__(self):
            self.error_count = 0

        async def on_websocket(self, req, ws):
            await ws.accept()

            await ws.send_data(await ws.receive_data())
            await ws.send_data(bytearray(await ws.receive_data()))
            await ws.send_data(memoryview(await ws.receive_data()))

            for c in (ws.receive_data, ws.receive_media):
                for __ in range(2):
                    try:
                        await c()
                    except falcon.PayloadTypeError:
                        self.error_count += 1

    resource = Resource()
    conductor.app.add_route('/', resource)

    async with conductor as c:
        async with c.simulate_ws() as ws:
            await ws.send_data(sample_data)
            await ws.send_data(bytearray(sample_data))
            await ws.send_data(memoryview(sample_data))

            for __ in range(2):
                ws._collected_client_events.append({'type': EventType.WS_RECEIVE})
                ws._collected_client_events.append(
                    {'type': EventType.WS_RECEIVE, 'bytes': None}
                )

            for __ in range(3):
                assert (await ws.receive_data()) == sample_data

    assert resource.error_count == 4


@pytest.mark.parametrize(
    'subprotocols',
    [
        ['SIS508'],
        ('DEADBEEF', 'SIS508'),
        [],
        None,
    ],
)
async def test_subprotocol(subprotocols, conductor):
    class Resource:
        def __init__(self):
            self.test_complete = asyncio.Event()

        async def on_websocket(self, req, ws):
            subs = ws.subprotocols
            assert isinstance(subs, tuple)

            selected = subs[0] if subs else None
            await ws.accept(subprotocol=selected)

            await self.test_complete.wait()

    resource = Resource()
    conductor.app.add_route('/', resource)

    async with conductor as c:
        async with c.simulate_ws(subprotocols=subprotocols) as ws:
            try:
                if not subprotocols:
                    assert ws.subprotocol is None
                else:
                    assert ws.subprotocol == subprotocols[0]
            finally:
                resource.test_complete.set()


@pytest.mark.parametrize(
    'headers',
    [
        None,
        [],
        iter([]),
        iter([iter(['X-Name', 'Value']), ('NAME', 'Value'), ('NAME', 'Value')]),
        (['X-Name', 'Value'], ('NAME', 'Value'), ('NAME', 'Value')),
        {'NAME': 'value'},
        {'NAME': 'value', 'NameToo': 'ValueToo'},
    ],
)
async def test_accept_with_headers(headers, conductor):
    class Resource:
        def __init__(self):
            self.test_complete = asyncio.Event()

        async def on_websocket(self, req, ws):
            await ws.accept(headers=headers)
            await self.test_complete.wait()

    resource = Resource()
    conductor.app.add_route('/', resource)

    async with conductor as c:
        async with c.simulate_ws() as ws:
            try:
                if not headers:
                    assert ws.headers is None
                else:
                    headers_in = headers
                    if isinstance(headers, dict):
                        headers_in = headers.items()

                    for (name_in, value_in), (name_out, value_out) in zip(
                        headers_in, ws.headers
                    ):
                        name_out = name_out.decode()
                        value_out = value_out.decode()

                        assert name_out.islower()
                        assert name_in.lower() == name_out
                        assert value_in == value_out

            finally:
                resource.test_complete.set()


@pytest.mark.parametrize(
    'headers',
    [
        [['sec-websocket-protocol', 'SIS508']],
        [['non-ascii', b'\xe1\x9a\xa0\xe1\x9b\x87\xe1\x9a\xbb'.decode()]],
        {b'\xe1\x9a\xa0\xe1\x9b\x87\xe1\x9a\xbb'.decode(): 'non-ascii'},
    ],
)
async def test_accept_with_bad_headers(headers, conductor):
    class Resource:
        def __init__(self):
            self.raised_error = None

        async def on_websocket(self, req, ws):
            try:
                assert ws.supports_accept_headers
                await ws.accept(headers=headers)
            except Exception as ex:
                self.raised_error = ex

    resource = Resource()
    conductor.app.add_route('/', resource)

    async with conductor as c:
        try:
            async with c.simulate_ws():
                pass
        except falcon.WebSocketDisconnected:
            pass

    assert isinstance(resource.raised_error, ValueError)


async def test_accept_with_headers_not_supported(conductor):
    class Resource:
        def __init__(self):
            self.raised_error = None

        async def on_websocket(self, req, ws):
            try:
                assert not ws.supports_accept_headers
                await ws.accept(headers={'name': 'value'})
            except Exception as ex:
                self.raised_error = ex

    resource = Resource()
    conductor.app.add_route('/', resource)

    async with conductor as c:
        try:
            async with c.simulate_ws(spec_version='2.0'):
                pass
        except falcon.WebSocketDisconnected:
            pass

    assert isinstance(resource.raised_error, falcon.OperationNotAllowed)


async def test_missing_ws_handler(conductor):
    class Resource:
        async def on_get(self, req, resp):
            pass

    conductor.app.add_route('/', Resource())

    async with conductor as c:
        with pytest.raises(falcon.WebSocketHandlerNotFound):
            async with c.simulate_ws():
                pass


async def test_unexpected_param(conductor):
    class Resource:
        async def on_websocket(self, req, ws):
            pass

    conductor.app.add_route('/{id}', Resource())

    async with conductor as c:
        with pytest.raises(falcon.WebSocketServerError):
            async with c.simulate_ws('/DEADBEEF'):
                pass


@pytest.mark.parametrize(
    'subprotocol',
    [
        b'DEADBEEF',
        ['SIS508'],
        [],
        tuple(),
        {},
        'OK',  # control
    ],
)
async def test_subprotocol_bad_type(subprotocol, conductor):
    class Resource:
        def __init__(self):
            self.test_complete = asyncio.Event()

        async def on_websocket(self, req, ws):
            await ws.accept(subprotocol=subprotocol)

    resource = Resource()
    conductor.app.add_route('/', resource)

    async with conductor as c:
        if isinstance(subprotocol, str):
            async with c.simulate_ws():
                pass
        else:
            with pytest.raises(falcon.WebSocketServerError):
                async with c.simulate_ws():
                    pass


async def test_send_receive_wrong_type(conductor):
    class Resource:
        def __init__(self):
            self.error_count = 0

        async def on_websocket(self, req, ws):
            await ws.accept()

            try:
                await ws.receive_data()
            except falcon.PayloadTypeError:
                self.error_count += 1

            try:
                await ws.receive_text()
            except falcon.PayloadTypeError:
                self.error_count += 1

            try:
                await ws.send_text(b'')
            except TypeError:
                self.error_count += 1

            try:
                await ws.send_data('')
            except TypeError:
                self.error_count += 1

            await ws.send_text('text')
            await ws.send_data(b'data')

    resource = Resource()
    conductor.app.add_route('/', resource)

    async with conductor as c:
        async with c.simulate_ws() as ws:
            with pytest.raises(TypeError):
                await ws.send_text(b'')

            with pytest.raises(TypeError):
                await ws.send_data('')

            await ws.send_text('text')
            await ws.send_data(b'data')

            with pytest.raises(falcon.PayloadTypeError):
                await ws.receive_data()

            with pytest.raises(falcon.PayloadTypeError):
                await ws.receive_text()

    assert resource.error_count == 4


@pytest.mark.parametrize(
    'options_code',
    [999, 100, 0, -1, 1004, 1005, 1006, 1015, 1016, 1017, 1050, 1099, 'NaN'],
)
async def test_client_disconnect_uncaught_error(options_code, conductor):
    class Resource:
        def __init__(self):
            self.disconnected = False

        async def on_websocket(self, req, ws):
            await ws.accept()
            while True:
                try:
                    await ws.receive_text()
                except falcon.WebSocketDisconnected:
                    self.disconnected = True
                    raise

    resource = Resource()
    conductor.app.add_route('/', resource)
    conductor.app.ws_options.error_close_code = options_code

    async with conductor as c:
        try:
            async with c.simulate_ws('/') as ws:
                await ws.send_text('hello')
        except ValueError:
            assert options_code == 'NaN'

    assert resource.disconnected
    assert ws.close_code == CloseCode.NORMAL


def test_mw_methods_must_be_coroutines():
    class MiddlewareA:
        def process_resource_ws(self, req, ws, resource, params):
            pass

    class MiddlewareB:
        def process_request_ws(self, req, ws):
            pass

    app = App()

    for mw in [MiddlewareA(), MiddlewareB()]:
        with pytest.raises(falcon.CompatibilityError):
            app.add_middleware(mw)

        with pytest.raises(falcon.CompatibilityError):
            App(middleware=mw)


@pytest.mark.parametrize('version', ['1.9', '20.5', '3.0', '3.1'])
async def test_bad_spec_version(version, conductor):
    async with conductor as c:
        with pytest.raises(falcon.UnsupportedScopeError):
            async with c.simulate_ws('/', spec_version=version):
                pass


@pytest.mark.parametrize('version', ['1.0', '1'])
async def test_bad_http_version(version, conductor):
    async with conductor as c:
        with pytest.raises(falcon.UnsupportedError):
            async with c.simulate_ws('/', http_version=version):
                pass


@pytest.mark.parametrize('version', ['2.1', '2.3', '2.10.3'])
async def test_bad_first_event(version):
    app = App()

    scope = testing.create_scope_ws(spec_version=version)

    ws = testing.ASGIWebSocketSimulator()
    wrapped_emit = ws._emit

    async def _emit():
        if ws._state == ClientWebSocketState.CONNECT:
            ws._state = ClientWebSocketState.HANDSHAKE
            return {'type': EventType.WS_SEND}

        return await wrapped_emit(ws)

    ws._emit = _emit

    # NOTE(kgriffs): If there is a bad first event, the framework should
    #   just bail out early and close the request...
    await app(scope, ws._emit, ws._collect)

    assert ws.closed
    assert ws.close_code == CloseCode.SERVER_ERROR
    if version != '2.1':
        assert ws.close_reason == 'Internal Server Error'
    else:
        assert ws.close_reason == ''


async def test_missing_http_version():
    app = App()

    scope = testing.create_scope_ws()
    del scope['http_version']

    ws = testing.ASGIWebSocketSimulator()

    # NOTE(kgriffs): As long as this does not raise, we know the http
    #   version defaulted OK.
    await app(scope, ws._emit, ws._collect)


async def test_missing_spec_version():
    app = App()

    scope = testing.create_scope_ws()
    del scope['asgi']['spec_version']

    ws = testing.ASGIWebSocketSimulator()

    # NOTE(kgriffs): As long as this does not raise, we know the spec
    #   version defaulted OK.
    await app(scope, ws._emit, ws._collect)


async def test_translate_webserver_error(conductor):
    class Resource:
        def __init__(self):
            self.error_count = 0
            self.test_complete = asyncio.Event()

        async def on_websocket(self, req, ws):
            await ws.accept()

            async def raise_disconnect(event):
                raise Exception('Disconnected with code = 1000 (OK)')

            async def raise_io_error(event, cause=''):
                class ConnectionClosed(RuntimeError):
                    pass

                class ClientDisconnected(OSError):
                    pass

                if cause:
                    raise ClientDisconnected() from ConnectionClosed(cause)
                raise ClientDisconnected()

            async def raise_protocol_mismatch(event):
                raise Exception('protocol accepted must be from the list')

            async def raise_other(event):
                raise RuntimeError()

            # TODO(vytas): It would be nice to somehow refactor this test not
            #   to operate on the private members of WebSocket.
            #   But, OTOH, it is quite useful as it is.
            _asgi_send = ws._asgi_send
            _original_state = ws._state

            ws._asgi_send = raise_other
            ws._state = _original_state
            try:
                await ws.send_data(b'123')
            except Exception:
                self.error_count += 1

            ws._asgi_send = raise_protocol_mismatch
            ws._state = _original_state
            try:
                await ws.send_data(b'123')
            except ValueError:
                self.error_count += 1

            ws._asgi_send = raise_disconnect
            ws._state = _original_state
            try:
                await ws.send_data(b'123')
            except falcon.WebSocketDisconnected:
                self.error_count += 1

            ws._asgi_send = raise_io_error
            ws._state = _original_state
            try:
                await ws.send_data(b'123')
            except falcon.WebSocketDisconnected:
                self.error_count += 1

            ws._asgi_send = functools.partial(raise_io_error, cause='bork3d pipe')
            ws._state = _original_state
            try:
                await ws.send_data(b'123')
            except falcon.WebSocketDisconnected:
                self.error_count += 1

            ws._asgi_send = functools.partial(raise_io_error, cause='received 1001')
            ws._state = _original_state
            try:
                await ws.send_data(b'123')
            except falcon.WebSocketDisconnected:
                self.error_count += 1
            assert ws._close_code == 1001

            ws._asgi_send = _asgi_send
            ws._state = _original_state

            self.test_complete.set()

    resource = Resource()
    conductor.app.add_route('/', resource)

    async with conductor as c:
        async with c.simulate_ws():
            await resource.test_complete.wait()

    assert resource.error_count == 6


def test_ws_base_not_implemented():
    th = media.TextBaseHandlerWS()

    with pytest.raises(NotImplementedError):
        th.serialize({})

    with pytest.raises(NotImplementedError):
        th.deserialize('')

    bh = media.BinaryBaseHandlerWS()

    with pytest.raises(NotImplementedError):
        bh.serialize({})

    with pytest.raises(NotImplementedError):
        bh.deserialize(b'')


@pytest.mark.slow
async def test_ws_context_timeout(conductor):
    class Resource:
        async def on_websocket(self, req, ws):
            await asyncio.sleep(5.1)  # Anything longer than 5 is sufficient

    conductor.app.add_route('/', Resource())

    async with conductor as c:
        with pytest.raises(asyncio.TimeoutError):
            async with c.simulate_ws():
                pass


async def test_ws_simulator_client_require_accepted(conductor):
    class Resource:
        async def on_websocket(self, req, ws):
            await asyncio.sleep(5.1)  # Anything longer than 5 is sufficient

    conductor.app.add_route('/', Resource())

    async with conductor as c:
        context = c.simulate_ws()
        ws = context._ws

        assert not ws.ready

        m = 'not yet been accepted'
        with pytest.raises(falcon.OperationNotAllowed, match=m):
            await ws.receive_text()


async def test_ws_simulator_collect_edge_cases(conductor):
    class Resource:
        pass

    conductor.app.add_route('/', Resource())

    async with conductor as c:
        context = c.simulate_ws(spec_version='2.3')
        ws = context._ws

        m = 'must receive the first websocket.connect'
        with pytest.raises(falcon.OperationNotAllowed, match=m):
            await ws._collect({'type': 'test'})

        event = await ws._emit()
        assert event['type'] == EventType.WS_CONNECT

        m = 'before sending any other event types'
        with pytest.raises(falcon.OperationNotAllowed, match=m):
            await ws._collect({'type': EventType.WS_SEND})

        await ws.close()

        # NOTE(vytas): The collector should start raising an instance of
        #   OSError from now on per the ASGI WS spec ver 2.4+.
        for __ in range(10):
            with pytest.raises(OSError):
                await ws._collect({'type': EventType.WS_SEND})

        assert not ws._collected_server_events

        event = await ws._emit()
        assert event['type'] == EventType.WS_DISCONNECT

        m = 'websocket.disconnect event has already been emitted'
        with pytest.raises(falcon.OperationNotAllowed, match=m):
            event = await ws._emit()


@pytest.mark.slow
async def test_ws_responder_never_ready(conductor, monkeypatch):
    async def noop_close(obj, code=None):
        pass

    class SleepyResource:
        async def on_websocket(self, req, ws):
            for i in range(10):
                await asyncio.sleep(0.001)

    conductor.app.add_route('/', SleepyResource())

    # NOTE(vytas): It seems that it is hard to impossible to hit the second
    #   `await ready_waiter` of the _WSContextManager on CPython 3.12 due to
    #   different async code optimizations, so we mock away WebSocket.close.
    monkeypatch.setattr(WebSocket, 'close', noop_close)

    # NOTE(vytas): Shorten the timeout so that we do not wait for 5 seconds.
    monkeypatch.setattr(
        testing.ASGIWebSocketSimulator, '_DEFAULT_WAIT_READY_TIMEOUT', 0.5
    )

    async with conductor as c:
        with pytest.raises(asyncio.TimeoutError):
            async with c.simulate_ws():
                pass


@pytest.mark.skipif(msgpack, reason='test requires msgpack lib to be missing')
def test_msgpack_missing():
    options = WebSocketOptions()
    handler = options.media_handlers[falcon.WebSocketPayloadType.BINARY]

    with pytest.raises(RuntimeError):
        handler.serialize({})

    with pytest.raises(RuntimeError):
        handler.deserialize(b'{}')


@pytest.mark.parametrize('reason', ['Client closing connection', '', None])
async def test_client_close_with_reason(reason, conductor):
    class Resource:
        def __init__(self):
            pass

        async def on_websocket(self, req, ws):
            await ws.accept()
            while True:
                try:
                    await ws.receive_data()

                except falcon.WebSocketDisconnected:
                    break

    resource = Resource()
    conductor.app.add_route('/', resource)

    async with conductor as c:
        async with c.simulate_ws('/', spec_version='2.3') as ws:
            await ws.close(4099, reason)

    assert ws.close_code == 4099
    if reason:
        assert ws.close_reason == reason
    else:
        assert ws.close_reason == ''


@pytest.mark.parametrize('reason', ['PEBCAK', 'wow such reason', '', None])
async def test_close_with_reason_no_cm(conductor, reason):
    class Resource:
        async def on_websocket(self, req, ws):
            await ws.accept()
            text = await ws.receive_text()
            await ws.send_text(text.upper())
            await ws.close(4001, reason)

    resource = Resource()
    conductor.app.add_route('/', resource)

    # NOTE(vytas): Here we don't use the async context manager pattern in order
    #   to collect coverage under CPython 3.11. It doesn't seem to help though.
    context = conductor.simulate_ws(spec_version='2.4')
    ws = context._ws

    await ws.wait_ready()
    await ws.send_text('Hello, World!')
    received = await ws.receive_text()
    assert received == 'HELLO, WORLD!'

    with pytest.raises(falcon.WebSocketDisconnected):
        await ws.receive_text()

    assert ws.close_reason == (reason or '')


@pytest.mark.parametrize('reason', ['PEBCAK', 'wow such reason', '', None])
@pytest.mark.parametrize('spec_version', ['2.2', '2.3', '2.4'])
async def test_close_with_reason(conductor, reason, spec_version):
    class Resource:
        async def on_websocket(self, req, ws):
            await ws.accept()
            await ws.close(3400, reason)

    resource = Resource()
    conductor.app.add_route('/', resource)

    async with conductor as c:
        async with c.simulate_ws('/', spec_version=spec_version) as ws:
            # Make sure the responder has a chance to reach the close() statement
            for _ in range(3):
                await asyncio.sleep(0)
            assert ws.closed
            assert ws.close_code == 3400

    assert ws.close_code == 3400
    if spec_version == '2.2':
        assert ws.close_reason == ''
    else:
        assert ws.close_reason == reason or 'Bad Request'


@pytest.mark.parametrize('no_default', [True, False])
@pytest.mark.parametrize(
    'code,expected',
    [
        (None, 'Normal Closure'),
        (1011, 'Internal Server Error'),
        (3405, 'Method Not Allowed'),
        (3701, ''),
        (3702, 'Emacs'),
        (4042, ''),
        (4099, 'wow such reason'),
    ],
)
async def test_reason_mapping(no_default, code, expected, conductor):
    class Resource:
        def __init__(self):
            pass

        async def on_websocket(self, req, ws):
            await ws.accept()
            await ws.close(code)

    resource = Resource()
    conductor.app.add_route('/', resource)
    if no_default:
        conductor.app.ws_options.default_close_reasons = {}
    else:
        # NOTE(vytas): Although it would be fun, we opt not to provide reasons
        #   for 7xx errors by default.
        conductor.app.ws_options.default_close_reasons[3702] = 'Emacs'
        conductor.app.ws_options.default_close_reasons[4099] = 'wow such reason'

    async with conductor as c:
        with pytest.raises(falcon.WebSocketDisconnected):
            async with c.simulate_ws('/', spec_version='2.10.3') as ws:
                await ws.receive_data()

    if code:
        assert ws.close_code == code
    else:
        assert ws.close_code == CloseCode.NORMAL

    if no_default:
        assert ws.close_reason == ''
    else:
        assert ws.close_reason == expected


@pytest.mark.parametrize('status', [200, 500, 422, 400])
@pytest.mark.parametrize('thing', [falcon.HTTPStatus, falcon.HTTPError])
@pytest.mark.parametrize('accept', [True, False])
async def test_ws_http_error_or_status_response(conductor, status, thing, accept):
    class Resource:
        async def on_websocket(self, req, ws):
            if accept:
                await ws.accept()
            raise thing(status)

    conductor.app.add_route('/', Resource())
    exp_code = 3000 + status

    async with conductor as c:
        if accept:
            async with c.simulate_ws() as ws:
                # Make sure the responder has a chance to reach the raise point
                for _ in range(3):
                    await asyncio.sleep(0)
                assert ws.closed
                assert ws.close_code == exp_code
        else:
            with pytest.raises(falcon.WebSocketDisconnected) as err:
                async with c.simulate_ws():
                    pass
            assert err.value.code == exp_code


@pytest.mark.parametrize('status', [200, 500, 422, 400])
@pytest.mark.parametrize(
    'thing',
    [
        falcon.HTTPStatus,
        falcon.HTTPError,
    ],
)
@pytest.mark.parametrize('place', ['request', 'resource'])
async def test_ws_http_error_or_status_middleware(conductor, status, thing, place):
    called = False

    class Resource:
        async def on_websocket(self, req, ws):
            nonlocal called
            called = True

    class Middleware:
        async def process_request_ws(self, req, ws):
            if place == 'request':
                raise thing(status)

        async def process_resource_ws(self, req, ws, res, params):
            if place == 'resource':
                raise thing(status)

    conductor.app.add_route('/', Resource())
    conductor.app.add_middleware(Middleware())
    exp_code = 3000 + status

    async with conductor as c:
        with pytest.raises(falcon.WebSocketDisconnected) as err:
            async with c.simulate_ws():
                pass
        assert err.value.code == exp_code
    assert not called


class FooBarError(Exception):
    pass


@pytest.mark.parametrize('status', [200, 500, 422, 400])
@pytest.mark.parametrize('thing', [falcon.HTTPStatus, falcon.HTTPError])
@pytest.mark.parametrize(
    'place', ['request', 'resource', 'ws_before_accept', 'ws_after_accept']
)
@pytest.mark.parametrize('handler_has_ws', [True, False])
async def test_ws_http_error_or_status_error_handler(
    conductor, status, thing, place, handler_has_ws
):
    class Resource:
        async def on_websocket(self, req, ws):
            if place == 'ws_before_accept':
                raise FooBarError
            await ws.accept()
            if place == 'ws_after_accept':
                raise FooBarError

    class Middleware:
        async def process_request_ws(self, req, ws):
            if place == 'request':
                raise FooBarError

        async def process_resource_ws(self, req, ws, res, params):
            if place == 'resource':
                raise FooBarError

    if handler_has_ws:

        async def handle_foobar(req, resp, ex, param, ws=None):
            raise thing(status)

    else:

        async def handle_foobar(req, resp, ex, param):  # type: ignore[misc]
            raise thing(status)

    conductor.app.add_route('/', Resource())
    conductor.app.add_middleware(Middleware())
    conductor.app.add_error_handler(FooBarError, handle_foobar)
    exp_code = 3000 + status

    async with conductor as c:
        if place == 'ws_after_accept':
            async with c.simulate_ws() as ws:
                # Make sure the responder has a chance to reach the raise point
                for _ in range(3):
                    await asyncio.sleep(0)
                assert ws.closed
                assert ws.close_code == exp_code
        else:
            with pytest.raises(falcon.WebSocketDisconnected) as err:
                async with c.simulate_ws():
                    pass
            assert err.value.code == exp_code


@pytest.mark.parametrize('max_receive_queue', [0, 1, 4, 7, 17])
async def test_max_receive_queue_sizes(conductor, max_receive_queue):
    class Chat:
        async def on_websocket(self, req, ws, user):
            await ws.accept()

            broadcast = [
                '[Guest123] ping',
                '[John F. Barbaz] Hi everyone.',
                f'Hello, {user}!',
            ]

            while True:
                await ws.send_text(broadcast.pop())

                msg = await ws.receive_text()
                if msg == '/quit':
                    await ws.send_text('Bye!')
                    await ws.close(reason='Received /quit')
                    break
                else:
                    await ws.send_text(f'[{user}] {msg}')

    conductor.app.ws_options.max_receive_queue = max_receive_queue
    conductor.app.add_route('/chat/{user}', Chat())

    received = []
    messages = ['/quit', 'I have to leave this test soon.', 'Hello!']

    async with conductor as c:
        async with c.simulate_ws('/chat/foobarer') as ws:
            while messages:
                received.append(await ws.receive_text())

                await ws.send_text(messages.pop())
                received.append(await ws.receive_text())

    assert len(received) == 6


@pytest.mark.parametrize('sink', ['no-ws-arg', 'with-ws-arg', 'unhashable-obj'])
async def test_sinks(conductor, sink):
    async def say_hello(req, resp_or_ws, name):
        greeting = f'Hello, {name}!'
        if req.is_websocket:
            await resp_or_ws.accept()
            await resp_or_ws.send_text(greeting)

            await resp_or_ws.receive_text()  # Receive /bye
        else:
            resp_or_ws.content_type = falcon.MEDIA_TEXT
            resp_or_ws.text = greeting

    async def sink_no_ws_arg(req, resp_or_ws, name):
        assert resp_or_ws is not None
        await say_hello(req, resp_or_ws, name)

    async def sink_with_ws_arg(req, resp, name, ws=None):
        if ws:
            assert resp is None
            await say_hello(req, ws, name)
        else:
            assert resp is not None
            await say_hello(req, resp, name)

    class Unhashable(list):
        async def __call__(self, req, resp, name, ws=None):
            await sink_with_ws_arg(req, resp, name, ws=ws)

    sinks = {
        'no-ws-arg': sink_no_ws_arg,
        'with-ws-arg': sink_with_ws_arg,
        'unhashable-obj': Unhashable(),
    }
    conductor.app.add_sink(sinks[sink], r'/ws/(?P<name>\w+)')

    async with conductor as c:
        resp = await c.simulate_get('/ws/World')
        assert resp.status_code == 200
        assert resp.text == 'Hello, World!'

        expectation = (
            pytest.warns(DeprecatedWarning) if sink == 'no-ws-arg' else nullcontext()
        )
        with expectation:
            async with c.simulate_ws('/ws/World') as ws:
                assert await ws.receive_text() == 'Hello, World!'
                await ws.send_text('/bye')


async def test_static_route(conductor, tmp_path):
    conductor.app.add_static_route('/static', tmp_path)

    async with conductor as c:
        with pytest.raises(falcon.WebSocketDisconnected) as exc_info:
            async with c.simulate_ws('/static/report.json'):
                pass

        assert exc_info.value.code == 3400
