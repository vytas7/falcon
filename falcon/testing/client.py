# Copyright 2016 by Rackspace Hosting, Inc.
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

"""WSGI test client utilities.

This package includes utilities for simulating HTTP requests against a
WSGI callable, without having to stand up a WSGI server.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from http.cookies import Morsel
import inspect
import json as json_module
import time
from typing import (
    Any,
    Awaitable,
    Callable,
    cast,
    Coroutine,
    Dict,
    Iterable,
    List,
    Literal,
    Mapping,
    Optional,
    overload,
    Sequence,
    TextIO,
    Tuple,
    TYPE_CHECKING,
    TypeVar,
    Union,
)
import warnings
import wsgiref.validate

from falcon._typing import CookieArg
from falcon._typing import HeaderArg
from falcon._typing import HeaderIter
from falcon._typing import HeaderMapping
from falcon.asgi_spec import AsgiEvent
from falcon.asgi_spec import ScopeType
from falcon.constants import COMBINED_METHODS
from falcon.constants import MEDIA_JSON
from falcon.errors import CompatibilityError
from falcon.testing import helpers
from falcon.testing.srmock import StartResponseMock
from falcon.typing import Headers
from falcon.util import async_to_sync
from falcon.util import CaseInsensitiveDict
from falcon.util import code_to_http_status
from falcon.util import http_cookies
from falcon.util import http_date_to_dt
from falcon.util import to_query_str

if TYPE_CHECKING:
    import falcon
    from falcon import asgi

warnings.filterwarnings(
    'error',
    ('Unknown REQUEST_METHOD: ' + "'({})'".format('|'.join(COMBINED_METHODS))),
    wsgiref.validate.WSGIWarning,
    '',
    0,
)

_T = TypeVar('_T', bound=Callable[..., Any])


def _simulate_method_alias(
    method: _T, version_added: str = '3.1', replace_name: Optional[str] = None
) -> _T:
    def alias(client: Any, *args: Any, **kwargs: Any) -> Any:
        return method(client, *args, **kwargs)

    async def async_alias(client: Any, *args: Any, **kwargs: Any) -> Any:
        return await method(client, *args, **kwargs)

    alias = async_alias if inspect.iscoroutinefunction(method) else alias

    assert method.__doc__
    alias.__doc__ = method.__doc__ + '\n        .. versionadded:: {}\n'.format(
        version_added
    )
    if replace_name:
        alias.__doc__ = alias.__doc__.replace(method.__name__, replace_name)
        alias.__name__ = replace_name
    else:
        alias.__name__ = method.__name__.partition('simulate_')[-1]

    return cast(_T, alias)


class Cookie:
    """Represents a cookie returned by a simulated request.

    Args:
        morsel: A ``Morsel`` object from which to derive the cookie data.
    """

    _expires: Optional[str]
    _path: str
    _domain: str
    _max_age: Optional[str]
    _secure: Optional[str]
    _httponly: Optional[str]
    _samesite: Optional[str]
    _partitioned: Optional[str]

    def __init__(self, morsel: Morsel) -> None:
        self._name = morsel.key
        self._value = morsel.value

        for name in (
            'expires',
            'path',
            'domain',
            'max_age',
            'secure',
            'httponly',
            'samesite',
            'partitioned',
        ):
            value = morsel[name.replace('_', '-')] or None
            setattr(self, '_' + name, value)

    @property
    def name(self) -> str:
        """The cookie's name."""
        return self._name

    @property
    def value(self) -> str:
        """The value of the cookie."""
        return self._value

    @property
    def expires(self) -> Optional[dt.datetime]:
        """Expiration timestamp for the cookie, or ``None`` if not specified.

        .. versionchanged:: 4.0
            This property now returns timezone-aware
            :class:`~datetime.datetime` objects (or ``None``).
        """
        if self._expires:
            return http_date_to_dt(self._expires, obs_date=True)

        return None

    @property
    def path(self) -> str:
        """The path prefix to which this cookie is restricted.

        An empty string if not specified.
        """
        return self._path

    @property
    def domain(self) -> str:
        """The domain to which this cookie is restricted.

        An empty string if not specified.
        """
        return self._domain

    @property
    def max_age(self) -> Optional[int]:
        """The lifetime of the cookie in seconds, or ``None`` if not specified."""
        return int(self._max_age) if self._max_age else None

    @property
    def secure(self) -> bool:
        """Whether or not the cookie may only only be transmitted
        from the client via HTTPS.
        """  # noqa: D205
        return bool(self._secure)

    @property
    def http_only(self) -> bool:
        """Whether or not the cookie will be visible from JavaScript in the client."""
        return bool(self._httponly)

    @property
    def same_site(self) -> Optional[str]:
        """Specifies whether cookies are send in cross-site requests.

        Possible values are 'Lax', 'Strict' and 'None'. ``None`` if not specified.
        """
        return self._samesite if self._samesite else None

    @property
    def partitioned(self) -> bool:
        """Indicates if the cookie has the ``Partitioned`` flag set."""
        return bool(self._partitioned)


class _ResultBase:
    """Base class for the result of a simulated request.

    Args:
        status (str): An HTTP status string, including status code and
            reason string
        headers (list): A list of (header_name, header_value) tuples,
            per PEP-3333
    """

    def __init__(self, status: str, headers: HeaderIter) -> None:
        self._status = status
        self._status_code = int(status[:3])
        self._headers = CaseInsensitiveDict(headers)

        cookies = http_cookies.SimpleCookie()
        for name, value in headers:
            if name.lower() == 'set-cookie':
                cookies.load(value)

        self._cookies = dict(
            (morsel.key, Cookie(morsel)) for morsel in cookies.values()
        )

        self._encoding = helpers.get_encoding_from_headers(self._headers)

    @property
    def status(self) -> str:
        """HTTP status string given in the response."""
        return self._status

    @property
    def status_code(self) -> int:
        """The code portion of the HTTP status string."""
        return self._status_code

    @property
    def headers(self) -> Headers:
        """A case-insensitive dictionary containing all the headers in the response,
        except for cookies, which may be accessed via the `cookies` attribute.

        Note:

            Multiple instances of a header in the response are
            currently not supported; it is unspecified which value
            will "win" and be represented in `headers`.
        """  # noqa: D205
        return self._headers  # type: ignore[return-value]

    @property
    def cookies(self) -> Dict[str, Cookie]:
        """A dictionary of :class:`falcon.testing.Cookie` values parsed from
        the response, by name.

        The cookies dictionary can be used directly in subsequent requests::

            client = testing.TestClient(app)
            response_one = client.simulate_get('/')
            response_two = client.simulate_post('/', cookies=response_one.cookies)
        """  # noqa: D205
        return self._cookies

    @property
    def encoding(self) -> Optional[str]:
        """Text encoding of the response body.

        Returns ``None`` if the encoding can not be determined.
        """
        return self._encoding

    @property
    def content_type(self) -> Optional[str]:
        """Return the ``Content-Type`` header or ``None`` if missing."""
        return self.headers.get('Content-Type')


class ResultBodyStream:
    """Simple forward-only reader for a streamed test result body.

    Args:
        chunks (list): Reference to a list of body chunks that may
            continue to be appended to as more body events are
            collected.
    """

    def __init__(self, chunks: Sequence[bytes]) -> None:
        self._chunks = chunks
        self._chunk_pos = 0

    async def read(self) -> bytes:
        """Read any data that has been collected since the last call.

        Returns:
            bytes: data that has been collected since the last call,
            or an empty byte string if no additional data is available.
        """

        # NOTE(kgriffs): Yield to other tasks to give them a chance to
        #   send us more body chunks if any are available.
        #
        #   https://bugs.python.org/issue34476
        #
        await asyncio.sleep(0)

        if self._chunk_pos >= len(self._chunks):
            return b''

        data = b''.join(self._chunks[self._chunk_pos :])
        self._chunk_pos = len(self._chunks)

        return data


class Result(_ResultBase):
    """Encapsulates the result of a simulated request.

    Args:
        iterable (iterable): An iterable that yields zero or more
            bytestrings, per PEP-3333
        status (str): An HTTP status string, including status code and
            reason string
        headers (list): A list of (header_name, header_value) tuples,
            per PEP-3333
    """

    def __init__(
        self, iterable: Iterable[bytes], status: str, headers: HeaderIter
    ) -> None:
        super().__init__(status, headers)

        self._text: Optional[str] = None
        self._content = b''.join(iterable)

    @property
    def content(self) -> bytes:
        """Raw response body, or an ``b''`` if the response body was empty."""
        return self._content

    @property
    def text(self) -> str:
        """Decoded response body of type ``str``.

        If the content type does not specify an encoding, UTF-8 is assumed.
        """
        if self._text is None:
            if not self.content:
                self._text = ''
            else:
                if self.encoding is None:
                    encoding = 'UTF-8'
                else:
                    encoding = self.encoding

                self._text = self.content.decode(encoding)

        return self._text

    @property
    def json(self) -> Any:
        """Deserialized JSON body.

        Will be ``None`` if the body has no content to deserialize.
        Otherwise, raises an error if the response is not valid JSON.
        """
        if not self.text:
            return None

        return json_module.loads(self.text)

    def __repr__(self) -> str:
        repr_result = ' '.join(filter(None, self._prepare_repr_args()))

        return 'Result<{}>'.format(repr_result)

    def __rich__(self) -> str:
        status, content_type, content = self._prepare_repr_args()

        status_color: str

        for prefix, color in (
            ('1', 'blue'),
            ('2', 'green'),
            ('3', 'magenta'),
            ('4', 'red'),
            ('5', 'red'),
        ):
            if status.startswith(prefix):
                status_color = color

        result_template = (
            '[bold]Result[/]<[bold {}]{}[/] [italic yellow]{}[/] [grey50]{}[/]>'
        )

        return result_template.format(status_color, status, content_type, content)

    def _prepare_repr_args(self) -> List[str]:
        content_type = self.content_type or ''

        if len(self.content) > 40:
            content = self.content[:20] + b'...' + self.content[-20:]
        else:
            content = self.content

        repr_args = [self.status, content_type, str(content)]

        return repr_args


class StreamedResult(_ResultBase):
    """Encapsulates the streamed result of an ASGI request.

    Args:
        body_chunks (list): A list of body chunks. This list may be
            appended to after a result object has been instantiated.
        status (str): An HTTP status string, including status code and
            reason string
        headers (list): A list of (header_name, header_value) tuples,
            per PEP-3333
        task (asyncio.Task): The scheduled simulated request which may or
            may not have already finished. :meth:`~.finalize`
            will await the task before returning.
        req_event_emitter (~falcon.testing.ASGIRequestEventEmitter): A reference
            to the event emitter used to simulate events sent to the ASGI
            application via its receive() method.
            :meth:`~.finalize` will cause the event emitter to
            simulate an ``'http.disconnect'`` event before returning.
    """

    def __init__(
        self,
        body_chunks: Sequence[bytes],
        status: str,
        headers: HeaderIter,
        task: asyncio.Task,
        req_event_emitter: helpers.ASGIRequestEventEmitter,
    ):
        super().__init__(status, headers)

        self._task = task
        self._stream = ResultBodyStream(body_chunks)
        self._req_event_emitter = req_event_emitter

    @property
    def stream(self) -> ResultBodyStream:
        """Raw response body, as a byte stream."""
        return self._stream

    async def finalize(self) -> None:
        """Finalize the encapsulated simulated request.

        This method causes the request event emitter to begin emitting
        ``'http.disconnect'`` events and then awaits the completion of the
        asyncio task that is running the simulated ASGI request.
        """
        self._req_event_emitter.disconnect()
        await self._task


# NOTE(kgriffs): The default of asgi_disconnect_ttl was chosen to be
#   relatively long (5 minutes) to help testers notice when something
#   appears to be "hanging", which might indicates that the app is
#   not handling the reception of events correctly.
def simulate_request(
    app: Callable[..., Any],  # accept any asgi/wsgi app
    method: str = 'GET',
    path: str = '/',
    query_string: Optional[str] = None,
    headers: Optional[HeaderArg] = None,
    content_type: Optional[str] = None,
    body: Optional[Union[str, bytes]] = None,
    json: Optional[Any] = None,
    file_wrapper: Optional[Callable[..., Any]] = None,
    wsgierrors: Optional[TextIO] = None,
    params: Optional[Mapping[str, Any]] = None,
    params_csv: bool = False,
    protocol: str = 'http',
    host: str = helpers.DEFAULT_HOST,
    remote_addr: Optional[str] = None,
    extras: Optional[Mapping[str, Any]] = None,
    http_version: str = '1.1',
    port: Optional[int] = None,
    root_path: Optional[str] = None,
    cookies: Optional[CookieArg] = None,
    asgi_chunk_size: int = 4096,
    asgi_disconnect_ttl: int = 300,
) -> Result:
    """Simulate a request to a WSGI or ASGI application.

    Performs a request against a WSGI or ASGI application. In the case of
    WSGI, uses :any:`wsgiref.validate` to ensure the response is valid.

    Note:
        In the case of an ASGI request, this method will simulate the entire
        app lifecycle in a single shot, including lifespan and client
        disconnect events. In order to simulate multiple interleaved
        requests, or to test a streaming endpoint (such as one that emits
        server-sent events), :class:`~falcon.testing.ASGIConductor` can be
        used to more precisely control the app lifecycle.

    Keyword Args:
        app (callable): The WSGI or ASGI application to call
        method (str): An HTTP method to use in the request
            (default: 'GET')
        path (str): The URL path to request (default: '/').

            Note:
                The path may contain a query string. However, neither
                `query_string` nor `params` may be specified in this case.

        root_path (str): The initial portion of the request URL's "path" that
            corresponds to the application object, so that the application
            knows its virtual "location". This defaults to the empty string,
            indicating that the application corresponds to the "root" of the
            server.
        protocol: The protocol to use for the URL scheme
            (default: 'http')
        port (int): The TCP port to simulate. Defaults to
            the standard port used by the given scheme (i.e., 80 for 'http'
            and 443 for 'https'). A string may also be passed, as long as
            it can be parsed as an int.
        params (dict): A dictionary of query string parameters,
            where each key is a parameter name, and each value is
            either a ``str`` or something that can be converted
            into a ``str``, or a list of such values. If a ``list``,
            the value will be converted to a comma-delimited string
            of values (e.g., 'thing=1,2,3').
        params_csv (bool): Set to ``True`` to encode list values
            in query string params as comma-separated values
            (e.g., 'thing=1,2,3'). Otherwise, parameters will be encoded by
            specifying multiple instances of the parameter
            (e.g., 'thing=1&thing=2&thing=3'). Defaults to ``False``.
        query_string (str): A raw query string to include in the
            request (default: ``None``). If specified, overrides
            `params`.
        content_type (str): The value to use for the Content-Type header in
            the request. If specified, this value will take precedence over
            any value set for the Content-Type header in the
            `headers` keyword argument. The ``falcon`` module provides a number
            of :ref:`constants for common media types <media_type_constants>`.
        headers (dict): Extra headers as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of strings provides the name and value
            for an HTTP header. If desired, multiple header values may be
            combined into a single (*name*, *value*) pair by joining the values
            with a comma when the header in question supports the list
            format (see also RFC 7230 and RFC 7231). Header names are not
            case-sensitive.

            Note:
                If a User-Agent header is not provided, it will default to::

                    f'falcon-client/{falcon.__version__}'

        body (str): The body of the request (default ''). The value will be
            encoded as UTF-8 in the WSGI environ. Alternatively, a byte string
            may be passed, in which case it will be used as-is.
        json(JSON serializable): A JSON document to serialize as the
            body of the request (default: ``None``). If specified,
            overrides `body` and sets the Content-Type header to
            ``'application/json'``, overriding any value specified by either
            the `content_type` or `headers` arguments.
        file_wrapper (callable): Callable that returns an iterable,
            to be used as the value for *wsgi.file_wrapper* in the
            WSGI environ (default: ``None``). This can be used to test
            high-performance file transmission when `resp.stream` is
            set to a file-like object.
        host(str): A string to use for the hostname part of the fully
            qualified request URL (default: 'falconframework.org')
        remote_addr (str): A string to use as the remote IP address for the
            request (default: '127.0.0.1'). For WSGI, this corresponds to
            the 'REMOTE_ADDR' environ variable. For ASGI, this corresponds
            to the IP address used for the 'client' field in the connection
            scope.
        http_version (str): The HTTP version to simulate. Must be either
            '2', '2.0', 1.1', '1.0', or '1' (default '1.1'). If set to '1.0',
            the Host header will not be added to the scope.
        wsgierrors (io): The stream to use as *wsgierrors* in the WSGI
            environ (default ``sys.stderr``)
        asgi_chunk_size (int): The maximum number of bytes that will be
            sent to the ASGI app in a single ``'http.request'`` event (default
            4096).
        asgi_disconnect_ttl (int): The maximum number of seconds to wait
            since the request was initiated, before emitting an
            ``'http.disconnect'`` event when the app calls the
            receive() function (default 300).
        extras (dict): Additional values to add to the WSGI
            ``environ`` dictionary or the ASGI scope for the request
            (default: ``None``)
        cookies (dict): Cookies as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of items provides the name and value
            for the 'Set-Cookie' header.

    Returns:
        :class:`~.Result`: The result of the request
    """

    if _is_asgi_app(app):
        return async_to_sync(  # type: ignore[return-value]
            _simulate_request_asgi,
            app,
            method=method,
            path=path,
            query_string=query_string,
            headers=headers,
            content_type=content_type,
            body=body,
            json=json,
            params=params,
            params_csv=params_csv,
            protocol=protocol,
            host=host,
            remote_addr=remote_addr,
            extras=extras,
            http_version=http_version,
            port=port,
            root_path=root_path,
            asgi_chunk_size=asgi_chunk_size,
            asgi_disconnect_ttl=asgi_disconnect_ttl,
            cookies=cookies,
        )

    path, query_string, headers, body, extras = _prepare_sim_args(
        path,
        query_string,
        params,
        params_csv,
        content_type,
        headers,
        body,
        json,
        extras,
    )

    env = helpers.create_environ(
        method=method,
        scheme=protocol,
        path=path,
        query_string=(query_string or ''),
        headers=headers,
        body=body or b'',
        file_wrapper=file_wrapper,
        host=host,
        remote_addr=remote_addr,
        wsgierrors=wsgierrors,
        http_version=http_version,
        port=port,
        root_path=root_path,
        cookies=cookies,
    )

    if 'REQUEST_METHOD' in extras and extras['REQUEST_METHOD'] != method:
        # NOTE(vytas): Even given the duct tape nature of overriding
        # arbitrary environ variables, changing the method can potentially
        # be very confusing, particularly when using specialized
        # simulate_get/post/patch etc methods.
        raise ValueError(
            'WSGI environ extras may not override the request method. '
            'Please use the method parameter.'
        )

    env.update(extras)

    srmock = StartResponseMock()
    validator = wsgiref.validate.validator(app)

    iterable = validator(env, srmock)

    data = helpers.closed_wsgi_iterable(iterable)
    assert srmock.status is not None and srmock.headers is not None
    return Result(data, srmock.status, srmock.headers)


@overload
async def _simulate_request_asgi(
    app: Callable[..., Coroutine[Any, Any, Any]],
    method: str = ...,
    path: str = ...,
    query_string: Optional[str] = ...,
    headers: Optional[HeaderArg] = ...,
    content_type: Optional[str] = ...,
    body: Optional[Union[str, bytes]] = ...,
    json: Optional[Any] = ...,
    params: Optional[Mapping[str, Any]] = ...,
    params_csv: bool = ...,
    protocol: str = ...,
    host: str = ...,
    remote_addr: Optional[str] = ...,
    extras: Optional[Mapping[str, Any]] = ...,
    http_version: str = ...,
    port: Optional[int] = ...,
    root_path: Optional[str] = ...,
    asgi_chunk_size: int = ...,
    asgi_disconnect_ttl: int = ...,
    cookies: Optional[CookieArg] = ...,
    _one_shot: Literal[False] = ...,
    _stream_result: Literal[True] = ...,
) -> StreamedResult: ...


@overload
async def _simulate_request_asgi(
    app: Callable[..., Coroutine[Any, Any, Any]],
    method: str = ...,
    path: str = ...,
    query_string: Optional[str] = ...,
    headers: Optional[HeaderArg] = ...,
    content_type: Optional[str] = ...,
    body: Optional[Union[str, bytes]] = ...,
    json: Optional[Any] = ...,
    params: Optional[Mapping[str, Any]] = ...,
    params_csv: bool = ...,
    protocol: str = ...,
    host: str = ...,
    remote_addr: Optional[str] = ...,
    extras: Optional[Mapping[str, Any]] = ...,
    http_version: str = ...,
    port: Optional[int] = ...,
    root_path: Optional[str] = ...,
    asgi_chunk_size: int = ...,
    asgi_disconnect_ttl: int = ...,
    cookies: Optional[CookieArg] = ...,
    _one_shot: Literal[True] = ...,
    _stream_result: bool = ...,
) -> Result: ...


# NOTE(kgriffs): The default of asgi_disconnect_ttl was chosen to be
#   relatively long (5 minutes) to help testers notice when something
#   appears to be "hanging", which might indicates that the app is
#   not handling the reception of events correctly.
async def _simulate_request_asgi(
    app: Callable[..., Coroutine[Any, Any, Any]],  # accept any asgi app
    method: str = 'GET',
    path: str = '/',
    query_string: Optional[str] = None,
    headers: Optional[HeaderArg] = None,
    content_type: Optional[str] = None,
    body: Optional[Union[str, bytes]] = None,
    json: Optional[Any] = None,
    params: Optional[Mapping[str, Any]] = None,
    params_csv: bool = False,
    protocol: str = 'http',
    host: str = helpers.DEFAULT_HOST,
    remote_addr: Optional[str] = None,
    extras: Optional[Mapping[str, Any]] = None,
    http_version: str = '1.1',
    port: Optional[int] = None,
    root_path: Optional[str] = None,
    asgi_chunk_size: int = 4096,
    asgi_disconnect_ttl: int = 300,
    cookies: Optional[CookieArg] = None,
    # NOTE(kgriffs): These are undocumented because they are only
    #   meant to be used internally by the framework (i.e., they are
    #   not part of the public interface.) In case we ever expose
    #   simulate_request_asgi() as part of the public interface, we
    #   don't want these kwargs to be documented.
    _one_shot: bool = True,
    _stream_result: bool = False,
) -> Union[Result, StreamedResult]:
    """Simulate a request to an ASGI application.

    Keyword Args:
        app (callable): The WSGI or ASGI application to call
        method (str): An HTTP method to use in the request
            (default: 'GET')
        path (str): The URL path to request (default: '/').

            Note:
                The path may contain a query string. However, neither
                `query_string` nor `params` may be specified in this case.

        root_path (str): The initial portion of the request URL's "path" that
            corresponds to the application object, so that the application
            knows its virtual "location". This defaults to the empty string,
            indicating that the application corresponds to the "root" of the
            server.
        protocol: The protocol to use for the URL scheme
            (default: 'http')
        port (int): The TCP port to simulate. Defaults to
            the standard port used by the given scheme (i.e., 80 for 'http'
            and 443 for 'https'). A string may also be passed, as long as
            it can be parsed as an int.
        params (dict): A dictionary of query string parameters,
            where each key is a parameter name, and each value is
            either a ``str`` or something that can be converted
            into a ``str``, or a list of such values. If a ``list``,
            the value will be converted to a comma-delimited string
            of values (e.g., 'thing=1,2,3').
        params_csv (bool): Set to ``False`` to encode list values
            in query string params by specifying multiple instances
            of the parameter (e.g., 'thing=1&thing=2&thing=3').
            Otherwise, parameters will be encoded as comma-separated
            values (e.g., 'thing=1,2,3'). Defaults to ``True``.
        query_string (str): A raw query string to include in the
            request (default: ``None``). If specified, overrides
            `params`.
        content_type (str): The value to use for the Content-Type header in
            the request. If specified, this value will take precedence over
            any value set for the Content-Type header in the
            `headers` keyword argument. The ``falcon`` module provides a number
            of :ref:`constants for common media types <media_type_constants>`.
        headers (dict): Extra headers as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of strings provides the name and value
            for an HTTP header. If desired, multiple header values may be
            combined into a single (*name*, *value*) pair by joining the values
            with a comma when the header in question supports the list
            format (see also RFC 7230 and RFC 7231). Header names are not
            case-sensitive.

            Note:
                If a User-Agent header is not provided, it will default to::

                    f'falcon-client/{falcon.__version__}'

        body (str): The body of the request (default ''). The value will be
            encoded as UTF-8 in the WSGI environ. Alternatively, a byte string
            may be passed, in which case it will be used as-is.
        json(JSON serializable): A JSON document to serialize as the
            body of the request (default: ``None``). If specified,
            overrides `body` and sets the Content-Type header to
            ``'application/json'``, overriding any value specified by either
            the `content_type` or `headers` arguments.
        host(str): A string to use for the hostname part of the fully
            qualified request URL (default: 'falconframework.org')
        remote_addr (str): A string to use as the remote IP address for the
            request (default: '127.0.0.1'). For WSGI, this corresponds to
            the 'REMOTE_ADDR' environ variable. For ASGI, this corresponds
            to the IP address used for the 'client' field in the connection
            scope.
        http_version (str): The HTTP version to simulate. Must be either
            '2', '2.0', 1.1', '1.0', or '1' (default '1.1'). If set to '1.0',
            the Host header will not be added to the scope.
        asgi_chunk_size (int): The maximum number of bytes that will be
            sent to the ASGI app in a single ``'http.request'`` event (default
            4096).
        asgi_disconnect_ttl (int): The maximum number of seconds to wait
            since the request was initiated, before emitting an
            ``'http.disconnect'`` event when the app calls the
            receive() function (default 300).
        extras (dict): Additional values to add to the WSGI
            ``environ`` dictionary or the ASGI scope for the request
            (default: ``None``)
        cookies (dict): Cookies as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of items provides the name and value
            for the 'Set-Cookie' header.

    Returns:
        :class:`~.Result`: The result of the request
    """

    path, query_string, headers, body, extras = _prepare_sim_args(
        path,
        query_string,
        params,
        params_csv,
        content_type,
        headers,
        body,
        json,
        extras,
    )

    # ---------------------------------------------------------------------
    # NOTE(kgriffs): 'http' scope
    # ---------------------------------------------------------------------
    content_length = None

    if body is not None:
        if isinstance(body, str):
            body = body.encode()

        content_length = len(body)

    http_scope = helpers.create_scope(
        path=path,
        query_string=query_string,
        method=method,
        headers=headers,
        host=host,
        scheme=protocol,
        port=port,
        http_version=http_version,
        remote_addr=remote_addr,
        root_path=root_path,
        content_length=content_length,
        cookies=cookies,
    )

    if 'method' in extras and extras['method'] != method.upper():
        raise ValueError(
            'ASGI scope extras may not override the request method. '
            'Please use the method parameter.'
        )

    http_scope.update(extras)
    # ---------------------------------------------------------------------

    if asgi_disconnect_ttl == 0:  # Special case
        disconnect_at = 0.0
    else:
        disconnect_at = time.time() + max(0, asgi_disconnect_ttl)

    req_event_emitter = helpers.ASGIRequestEventEmitter(
        (body or b''),
        chunk_size=asgi_chunk_size,
        disconnect_at=disconnect_at,
    )

    resp_event_collector = helpers.ASGIResponseEventCollector()

    if not _one_shot:
        task_req = asyncio.create_task(
            app(http_scope, req_event_emitter, resp_event_collector)
        )

        if _stream_result:
            # NOTE(kgriffs): Wait until the response has been started and give
            #   the task a chance to progress. Otherwise, we won't have a
            #   status or headers to pass to StreamedResult.
            while not resp_event_collector.status:
                await asyncio.sleep(0)

            return StreamedResult(
                resp_event_collector.body_chunks,
                code_to_http_status(resp_event_collector.status),
                resp_event_collector.headers,
                task_req,
                req_event_emitter,
            )

        req_event_emitter.disconnect()
        await task_req
        return Result(
            resp_event_collector.body_chunks,
            code_to_http_status(resp_event_collector.status),
            resp_event_collector.headers,
        )

    # ---------------------------------------------------------------------
    # NOTE(kgriffs): 'lifespan' scope
    # ---------------------------------------------------------------------
    lifespan_scope = {
        'type': ScopeType.LIFESPAN,
        'asgi': {
            'version': '3.0',
            'spec_version': '2.0',
        },
    }

    shutting_down = asyncio.Condition()
    lifespan_event_emitter = helpers.ASGILifespanEventEmitter(shutting_down)
    lifespan_event_collector = helpers.ASGIResponseEventCollector()
    # ---------------------------------------------------------------------

    async def conductor() -> None:
        # NOTE(kgriffs): We assume this is a Falcon ASGI app, which supports
        #   the lifespan protocol and thus we do not need to catch
        #   exceptions that would signify no lifespan protocol support.
        task_lifespan = asyncio.create_task(
            app(lifespan_scope, lifespan_event_emitter, lifespan_event_collector)
        )

        await _wait_for_startup(lifespan_event_collector.events)

        task_req = asyncio.create_task(
            app(http_scope, req_event_emitter, resp_event_collector)
        )
        req_event_emitter.disconnect()
        await task_req

        # NOTE(kgriffs): Notify lifespan_event_emitter that it is OK
        #   to proceed.
        async with shutting_down:
            shutting_down.notify()

        await _wait_for_shutdown(lifespan_event_collector.events)
        await task_lifespan

    await conductor()

    if resp_event_collector.status is None:
        # NOTE(kgriffs): An immediate disconnect was simulated, and so
        #   the app could not return a status.
        raise ConnectionError('An immediate disconnect was simulated.')

    return Result(
        resp_event_collector.body_chunks,
        code_to_http_status(resp_event_collector.status),
        resp_event_collector.headers,
    )


class ASGIConductor:
    """Test conductor for ASGI apps.

    This class provides more control over the lifecycle of a simulated
    request as compared to :class:`~.TestClient`. In addition, the conductor's
    asynchronous interface affords interleaved requests and the testing of
    streaming protocols such as
    :attr:`Server-Sent Events (SSE) <falcon.asgi.Response.sse>`
    and :ref:`WebSocket <ws>`.

    :class:`~.ASGIConductor` is implemented as a context manager. Upon
    entering and exiting the context, the appropriate ASGI lifespan events
    will be simulated.

    Within the context, HTTP requests can be simulated using an interface
    that is similar to :class:`~.TestClient`, except that all ``simulate_*()``
    methods are coroutines::

        async with testing.ASGIConductor(some_app) as conductor:
            async def post_events():
                for i in range(100):
                    await conductor.simulate_post('/events', json={'id': i}):
                    await asyncio.sleep(0.01)

            async def get_events_sse():
                # Here, we will get only some of the single server-sent events
                # because the non-streaming method is "single-shot". In other
                # words, simulate_get() will emit a client disconnect event
                # into the app before returning.
                result = await conductor.simulate_get('/events')

                # Alternatively, we can use simulate_get_stream() as a context
                # manager to perform a series of reads on the result body that
                # are interleaved with the execution of the post_events()
                # coroutine.
                async with conductor.simulate_get_stream('/events') as sr:
                    while some_condition:
                        # Read next body chunk that was received (if any).
                        chunk = await sr.stream.read()

                        if chunk:
                            # TODO: Do something with the chunk
                            pass

                    # Exiting the context causes the request event emitter to
                    # begin emitting ``'http.disconnect'`` events and then awaits
                    # the completion of the asyncio task that is running the
                    # simulated ASGI request.

            asyncio.gather(post_events(), get_events_sse())

    Note:
        Because the :class:`~.ASGIConductor` interface uses coroutines,
        it cannot be used directly with synchronous testing frameworks such as
        pytest.

        As a workaround, the test can be adapted by wrapping it in
        an inline async function and then invoking it via
        :meth:`falcon.async_to_sync` or decorating the test function
        with :meth:`falcon.runs_sync`.

        Alternatively, you can try searching PyPI to see if an async plugin is
        available for your testing framework of choice. For example, the
        ``pytest-asyncio`` plugin is available for ``pytest`` users.

    Similar to the :class:`TestClient`, :class:`ASGIConductor` also exposes
    convenience aliases without the ``simulate_`` prefix. Just as with a
    typical asynchronous HTTP client, it is possible to simply invoke::

        await conductor.get('/messages')
        await conductor.request('LOCK', '/files/first')

    Args:
        app (callable): An ASGI application to target when simulating
            requests.

    Keyword Arguments:
        headers (dict): Default headers to set on every request (default
            ``None``). These defaults may be overridden by passing values
            for the same headers to one of the ``simulate_*()`` methods.
    """

    # NOTE(caseit): while any asgi app is accept, type this as a falcon
    # asgi app for user convenience
    app: asgi.App
    """The app that this client instance was configured to use."""

    def __init__(
        self,
        app: Callable[..., Any],  # accept any asgi app
        headers: Optional[HeaderMapping] = None,
    ):
        if not _is_asgi_app(app):
            raise CompatibilityError('ASGIConductor may only be used with an ASGI app')

        self.app = app  # type: ignore[assignment]
        self._default_headers = headers

        self._shutting_down = asyncio.Condition()
        self._lifespan_event_collector = helpers.ASGIResponseEventCollector()
        self._lifespan_task: Optional[asyncio.Task] = None

    async def __aenter__(self) -> ASGIConductor:
        lifespan_scope = {
            'type': ScopeType.LIFESPAN,
            'asgi': {
                'version': '3.0',
                'spec_version': '2.0',
            },
        }

        lifespan_event_emitter = helpers.ASGILifespanEventEmitter(self._shutting_down)

        # NOTE(kgriffs): We assume this is a Falcon ASGI app, which supports
        #   the lifespan protocol and thus we do not need to catch
        #   exceptions that would signify no lifespan protocol support.
        self._lifespan_task = asyncio.create_task(
            self.app(
                lifespan_scope, lifespan_event_emitter, self._lifespan_event_collector
            )
        )

        await _wait_for_startup(self._lifespan_event_collector.events)

        return self

    async def __aexit__(self, ex_type: Any, ex: Any, tb: Any) -> bool:
        if ex_type:
            return False

        # NOTE(kgriffs): Notify lifespan_event_emitter that it is OK
        #   to proceed.
        async with self._shutting_down:
            self._shutting_down.notify()

        await _wait_for_shutdown(self._lifespan_event_collector.events)
        assert self._lifespan_task is not None
        await self._lifespan_task

        return True

    async def simulate_get(self, path: str = '/', **kwargs: Any) -> Result:
        """Simulate a GET request to an ASGI application.

        (See also: :meth:`falcon.testing.simulate_get`)
        """
        return await self.simulate_request('GET', path, **kwargs)

    def simulate_get_stream(
        self, path: str = '/', **kwargs: Any
    ) -> _AsyncContextManager:
        """Simulate a GET request to an ASGI application with a streamed response.

        (See also: :meth:`falcon.testing.simulate_get` for a list of
        supported keyword arguments.)

        This method returns an async context manager that can be used to obtain
        a managed :class:`~.StreamedResult` instance. Exiting the context
        will automatically finalize the result object, causing the request
        event emitter to begin emitting ``'http.disconnect'`` events and then
        await the completion of the task that is running the simulated ASGI
        request.

        In the following example, a series of streamed body chunks are read
        from the response::

            async with conductor.simulate_get_stream('/events') as sr:
                while some_condition:
                    # Read next body chunk that was received (if any).
                    chunk = await sr.stream.read()

                    if chunk:
                        # TODO: Do something with the chunk. For example,
                        #   a series of server-sent events could be validated
                        #   by concatenating the chunks and splitting on
                        #   double-newlines to obtain individual events.
                        pass

        """

        kwargs['_stream_result'] = True

        return _AsyncContextManager(self.simulate_request('GET', path, **kwargs))

    def simulate_ws(self, path: str = '/', **kwargs: Any) -> _WSContextManager:
        """Simulate a WebSocket connection to an ASGI application.

        All keyword arguments are passed through to
        :meth:`falcon.testing.create_scope_ws`.

        This method returns an async context manager that can be used to obtain
        a managed :class:`falcon.testing.ASGIWebSocketSimulator` instance.
        Exiting the context will simulate a close on the WebSocket (if not
        already closed) and await the completion of the task that is
        running the simulated ASGI request.

        In the following example, a series of WebSocket TEXT events are
        received from the ASGI app::

            async with conductor.simulate_ws('/events') as ws:
                while some_condition:
                    message = await ws.receive_text()

        """

        scope = helpers.create_scope_ws(path=path, **kwargs)
        ws = helpers.ASGIWebSocketSimulator()

        task_req = asyncio.create_task(self.app(scope, ws._emit, ws._collect))

        return _WSContextManager(ws, task_req)

    async def simulate_head(self, path: str = '/', **kwargs: Any) -> Result:
        """Simulate a HEAD request to an ASGI application.

        (See also: :meth:`falcon.testing.simulate_head`)
        """
        return await self.simulate_request('HEAD', path, **kwargs)

    async def simulate_post(self, path: str = '/', **kwargs: Any) -> Result:
        """Simulate a POST request to an ASGI application.

        (See also: :meth:`falcon.testing.simulate_post`)
        """
        return await self.simulate_request('POST', path, **kwargs)

    async def simulate_put(self, path: str = '/', **kwargs: Any) -> Result:
        """Simulate a PUT request to an ASGI application.

        (See also: :meth:`falcon.testing.simulate_put`)
        """
        return await self.simulate_request('PUT', path, **kwargs)

    async def simulate_options(self, path: str = '/', **kwargs: Any) -> Result:
        """Simulate an OPTIONS request to an ASGI application.

        (See also: :meth:`falcon.testing.simulate_options`)
        """
        return await self.simulate_request('OPTIONS', path, **kwargs)

    async def simulate_patch(self, path: str = '/', **kwargs: Any) -> Result:
        """Simulate a PATCH request to an ASGI application.

        (See also: :meth:`falcon.testing.simulate_patch`)
        """
        return await self.simulate_request('PATCH', path, **kwargs)

    async def simulate_delete(self, path: str = '/', **kwargs: Any) -> Result:
        """Simulate a DELETE request to an ASGI application.

        (See also: :meth:`falcon.testing.simulate_delete`)
        """
        return await self.simulate_request('DELETE', path, **kwargs)

    @overload
    async def simulate_request(
        self, *args: Any, _stream_result: Literal[True], **kwargs: Any
    ) -> StreamedResult: ...

    @overload
    async def simulate_request(self, *args: Any, **kwargs: Any) -> Result: ...

    async def simulate_request(
        self, *args: Any, **kwargs: Any
    ) -> Union[Result, StreamedResult]:
        """Simulate a request to an ASGI application.

        Wraps :meth:`falcon.testing.simulate_request` to perform an
        ASGI request directly against ``self.app``. Equivalent to::

            falcon.testing.simulate_request(self.app, *args, **kwargs)
        """

        if self._default_headers:
            # NOTE(kgriffs): Handle the case in which headers is explicitly
            # set to None.
            additional_headers = kwargs.get('headers') or {}

            merged_headers = dict(self._default_headers)
            merged_headers.update(additional_headers)

            kwargs['headers'] = merged_headers

        # NOTE(kgriffs): The conductor takes care of startup/shutdown
        kwargs['_one_shot'] = False

        return await _simulate_request_asgi(self.app, *args, **kwargs)

    delete = _simulate_method_alias(simulate_delete)
    get = _simulate_method_alias(simulate_get)
    get_stream = _simulate_method_alias(simulate_get_stream, replace_name='get_stream')
    head = _simulate_method_alias(simulate_head)
    options = _simulate_method_alias(simulate_options)
    patch = _simulate_method_alias(simulate_patch)
    post = _simulate_method_alias(simulate_post)
    put = _simulate_method_alias(simulate_put)
    request = _simulate_method_alias(simulate_request)
    websocket = _simulate_method_alias(simulate_ws, replace_name='websocket')


def simulate_get(app: Callable[..., Any], path: str, **kwargs: Any) -> Result:
    """Simulate a GET request to a WSGI or ASGI application.

    Equivalent to::

         simulate_request(app, 'GET', path, **kwargs)

    Note:
        In the case of an ASGI request, this method will simulate the entire
        app lifecycle in a single shot, including lifespan and client
        disconnect events. In order to simulate multiple interleaved
        requests, or to test a streaming endpoint (such as one that emits
        server-sent events), :class:`~falcon.testing.ASGIConductor` can be
        used to more precisely control the app lifecycle.

    Args:
        app (callable): The application to call
        path (str): The URL path to request

            Note:
                The path may contain a query string. However, neither
                `query_string` nor `params` may be specified in this case.

    Keyword Args:
        root_path (str): The initial portion of the request URL's "path" that
            corresponds to the application object, so that the application
            knows its virtual "location". This defaults to the empty string,
            indicating that the application corresponds to the "root" of the
            server.
        protocol: The protocol to use for the URL scheme
            (default: 'http')
        port (int): The TCP port to simulate. Defaults to
            the standard port used by the given scheme (i.e., 80 for 'http'
            and 443 for 'https'). A string may also be passed, as long as
            it can be parsed as an int.
        params (dict): A dictionary of query string parameters,
            where each key is a parameter name, and each value is
            either a ``str`` or something that can be converted
            into a ``str``, or a list of such values. If a ``list``,
            the value will be converted to a comma-delimited string
            of values (e.g., 'thing=1,2,3').
        params_csv (bool): Set to ``True`` to encode list values
            in query string params as comma-separated values
            (e.g., 'thing=1,2,3'). Otherwise, parameters will be encoded by
            specifying multiple instances of the parameter
            (e.g., 'thing=1&thing=2&thing=3'). Defaults to ``False``.
        query_string (str): A raw query string to include in the
            request (default: ``None``). If specified, overrides
            `params`.
        headers (dict): Extra headers as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of strings provides the name and value
            for an HTTP header. If desired, multiple header values may be
            combined into a single (*name*, *value*) pair by joining the values
            with a comma when the header in question supports the list
            format (see also RFC 7230 and RFC 7231). Header names are not
            case-sensitive.

            Note:
                If a User-Agent header is not provided, it will default to::

                    f'falcon-client/{falcon.__version__}'

        file_wrapper (callable): Callable that returns an iterable,
            to be used as the value for *wsgi.file_wrapper* in the
            WSGI environ (default: ``None``). This can be used to test
            high-performance file transmission when `resp.stream` is
            set to a file-like object.
        host(str): A string to use for the hostname part of the fully
            qualified request URL (default: 'falconframework.org')
        remote_addr (str): A string to use as the remote IP address for the
            request (default: '127.0.0.1'). For WSGI, this corresponds to
            the 'REMOTE_ADDR' environ variable. For ASGI, this corresponds
            to the IP address used for the 'client' field in the connection
            scope.
        http_version (str): The HTTP version to simulate. Must be either
            '2', '2.0', 1.1', '1.0', or '1' (default '1.1'). If set to '1.0',
            the Host header will not be added to the scope.
        wsgierrors (io): The stream to use as *wsgierrors* in the WSGI
            environ (default ``sys.stderr``)
        asgi_chunk_size (int): The maximum number of bytes that will be
            sent to the ASGI app in a single ``'http.request'`` event (default
            4096).
        asgi_disconnect_ttl (int): The maximum number of seconds to wait
            since the request was initiated, before emitting an
            ``'http.disconnect'`` event when the app calls the
            receive() function (default 300). Set to ``0`` to simulate an
            immediate disconnection without first emitting ``'http.request'``.
        extras (dict): Additional values to add to the WSGI
            ``environ`` dictionary or the ASGI scope for the request
            (default: ``None``)
        cookies (dict): Cookies as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of items provides the name and value
            for the 'Set-Cookie' header.

    Returns:
        :class:`~.Result`: The result of the request
    """

    return simulate_request(app, 'GET', path, **kwargs)


def simulate_head(app: Callable[..., Any], path: str, **kwargs: Any) -> Result:
    """Simulate a HEAD request to a WSGI or ASGI application.

    Equivalent to::

         simulate_request(app, 'HEAD', path, **kwargs)

    Note:
        In the case of an ASGI request, this method will simulate the entire
        app lifecycle in a single shot, including lifespan and client
        disconnect events. In order to simulate multiple interleaved
        requests, or to test a streaming endpoint (such as one that emits
        server-sent events), :class:`~falcon.testing.ASGIConductor` can be
        used to more precisely control the app lifecycle.

    Args:
        app (callable): The application to call
        path (str): The URL path to request

            Note:
                The path may contain a query string. However, neither
                `query_string` nor `params` may be specified in this case.

    Keyword Args:
        root_path (str): The initial portion of the request URL's "path" that
            corresponds to the application object, so that the application
            knows its virtual "location". This defaults to the empty string,
            indicating that the application corresponds to the "root" of the
            server.
        protocol: The protocol to use for the URL scheme
            (default: 'http')
        port (int): The TCP port to simulate. Defaults to
            the standard port used by the given scheme (i.e., 80 for 'http'
            and 443 for 'https'). A string may also be passed, as long as
            it can be parsed as an int.
        params (dict): A dictionary of query string parameters,
            where each key is a parameter name, and each value is
            either a ``str`` or something that can be converted
            into a ``str``, or a list of such values. If a ``list``,
            the value will be converted to a comma-delimited string
            of values (e.g., 'thing=1,2,3').
        params_csv (bool): Set to ``True`` to encode list values
            in query string params as comma-separated values
            (e.g., 'thing=1,2,3'). Otherwise, parameters will be encoded by
            specifying multiple instances of the parameter
            (e.g., 'thing=1&thing=2&thing=3'). Defaults to ``False``.
        query_string (str): A raw query string to include in the
            request (default: ``None``). If specified, overrides
            `params`.
        headers (dict): Extra headers as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of strings provides the name and value
            for an HTTP header. If desired, multiple header values may be
            combined into a single (*name*, *value*) pair by joining the values
            with a comma when the header in question supports the list
            format (see also RFC 7230 and RFC 7231). Header names are not
            case-sensitive.

            Note:
                If a User-Agent header is not provided, it will default to::

                    f'falcon-client/{falcon.__version__}'

        host(str): A string to use for the hostname part of the fully
            qualified request URL (default: 'falconframework.org')
        remote_addr (str): A string to use as the remote IP address for the
            request (default: '127.0.0.1'). For WSGI, this corresponds to
            the 'REMOTE_ADDR' environ variable. For ASGI, this corresponds
            to the IP address used for the 'client' field in the connection
            scope.
        http_version (str): The HTTP version to simulate. Must be either
            '2', '2.0', 1.1', '1.0', or '1' (default '1.1'). If set to '1.0',
            the Host header will not be added to the scope.
        wsgierrors (io): The stream to use as *wsgierrors* in the WSGI
            environ (default ``sys.stderr``)
        asgi_chunk_size (int): The maximum number of bytes that will be
            sent to the ASGI app in a single ``'http.request'`` event (default
            4096).
        asgi_disconnect_ttl (int): The maximum number of seconds to wait
            since the request was initiated, before emitting an
            ``'http.disconnect'`` event when the app calls the
            receive() function (default 300). Set to ``0`` to simulate an
            immediate disconnection without first emitting ``'http.request'``.
        extras (dict): Additional values to add to the WSGI
            ``environ`` dictionary or the ASGI scope for the request
            (default: ``None``)
        cookies (dict): Cookies as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of items provides the name and value
            for the 'Set-Cookie' header.

    Returns:
        :class:`~.Result`: The result of the request
    """
    return simulate_request(app, 'HEAD', path, **kwargs)


def simulate_post(app: Callable[..., Any], path: str, **kwargs: Any) -> Result:
    """Simulate a POST request to a WSGI or ASGI application.

    Equivalent to::

         simulate_request(app, 'POST', path, **kwargs)

    Note:
        In the case of an ASGI request, this method will simulate the entire
        app lifecycle in a single shot, including lifespan and client
        disconnect events. In order to simulate multiple interleaved
        requests, or to test a streaming endpoint (such as one that emits
        server-sent events), :class:`~falcon.testing.ASGIConductor` can be
        used to more precisely control the app lifecycle.

    Args:
        app (callable): The application to call
        path (str): The URL path to request

    Keyword Args:
        root_path (str): The initial portion of the request URL's "path" that
            corresponds to the application object, so that the application
            knows its virtual "location". This defaults to the empty string,
            indicating that the application corresponds to the "root" of the
            server.
        protocol: The protocol to use for the URL scheme
            (default: 'http')
        port (int): The TCP port to simulate. Defaults to
            the standard port used by the given scheme (i.e., 80 for 'http'
            and 443 for 'https'). A string may also be passed, as long as
            it can be parsed as an int.
        params (dict): A dictionary of query string parameters,
            where each key is a parameter name, and each value is
            either a ``str`` or something that can be converted
            into a ``str``, or a list of such values. If a ``list``,
            the value will be converted to a comma-delimited string
            of values (e.g., 'thing=1,2,3').
        params_csv (bool): Set to ``True`` to encode list values
            in query string params as comma-separated values
            (e.g., 'thing=1,2,3'). Otherwise, parameters will be encoded by
            specifying multiple instances of the parameter
            (e.g., 'thing=1&thing=2&thing=3'). Defaults to ``False``.
        query_string (str): A raw query string to include in the
            request (default: ``None``). If specified, overrides
            `params`.
        content_type (str): The value to use for the Content-Type header in
            the request. If specified, this value will take precedence over
            any value set for the Content-Type header in the
            `headers` keyword argument. The ``falcon`` module provides a number
            of :ref:`constants for common media types <media_type_constants>`.
        headers (dict): Extra headers as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of strings provides the name and value
            for an HTTP header. If desired, multiple header values may be
            combined into a single (*name*, *value*) pair by joining the values
            with a comma when the header in question supports the list
            format (see also RFC 7230 and RFC 7231). Header names are not
            case-sensitive.

            Note:
                If a User-Agent header is not provided, it will default to::

                    f'falcon-client/{falcon.__version__}'

        body (str): The body of the request (default ''). The value will be
            encoded as UTF-8 in the WSGI environ. Alternatively, a byte string
            may be passed, in which case it will be used as-is.
        json(JSON serializable): A JSON document to serialize as the
            body of the request (default: ``None``). If specified,
            overrides `body` and sets the Content-Type header to
            ``'application/json'``, overriding any value specified by either
            the `content_type` or `headers` arguments.
        file_wrapper (callable): Callable that returns an iterable,
            to be used as the value for *wsgi.file_wrapper* in the
            WSGI environ (default: ``None``). This can be used to test
            high-performance file transmission when `resp.stream` is
            set to a file-like object.
        host(str): A string to use for the hostname part of the fully
            qualified request URL (default: 'falconframework.org')
        remote_addr (str): A string to use as the remote IP address for the
            request (default: '127.0.0.1'). For WSGI, this corresponds to
            the 'REMOTE_ADDR' environ variable. For ASGI, this corresponds
            to the IP address used for the 'client' field in the connection
            scope.
        http_version (str): The HTTP version to simulate. Must be either
            '2', '2.0', 1.1', '1.0', or '1' (default '1.1'). If set to '1.0',
            the Host header will not be added to the scope.
        wsgierrors (io): The stream to use as *wsgierrors* in the WSGI
            environ (default ``sys.stderr``)
        asgi_chunk_size (int): The maximum number of bytes that will be
            sent to the ASGI app in a single ``'http.request'`` event (default
            4096).
        asgi_disconnect_ttl (int): The maximum number of seconds to wait
            since the request was initiated, before emitting an
            ``'http.disconnect'`` event when the app calls the
            receive() function (default 300). Set to ``0`` to simulate an
            immediate disconnection without first emitting ``'http.request'``.
        extras (dict): Additional values to add to the WSGI
            ``environ`` dictionary or the ASGI scope for the request
            (default: ``None``)
        cookies (dict): Cookies as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of items provides the name and value
            for the 'Set-Cookie' header.

    Returns:
        :class:`~.Result`: The result of the request
    """
    return simulate_request(app, 'POST', path, **kwargs)


def simulate_put(app: Callable[..., Any], path: str, **kwargs: Any) -> Result:
    """Simulate a PUT request to a WSGI or ASGI application.

    Equivalent to::

         simulate_request(app, 'PUT', path, **kwargs)

    Note:
        In the case of an ASGI request, this method will simulate the entire
        app lifecycle in a single shot, including lifespan and client
        disconnect events. In order to simulate multiple interleaved
        requests, or to test a streaming endpoint (such as one that emits
        server-sent events), :class:`~falcon.testing.ASGIConductor` can be
        used to more precisely control the app lifecycle.

    Args:
        app (callable): The application to call
        path (str): The URL path to request

    Keyword Args:
        root_path (str): The initial portion of the request URL's "path" that
            corresponds to the application object, so that the application
            knows its virtual "location". This defaults to the empty string,
            indicating that the application corresponds to the "root" of the
            server.
        protocol: The protocol to use for the URL scheme
            (default: 'http')
        port (int): The TCP port to simulate. Defaults to
            the standard port used by the given scheme (i.e., 80 for 'http'
            and 443 for 'https'). A string may also be passed, as long as
            it can be parsed as an int.
        params (dict): A dictionary of query string parameters,
            where each key is a parameter name, and each value is
            either a ``str`` or something that can be converted
            into a ``str``, or a list of such values. If a ``list``,
            the value will be converted to a comma-delimited string
            of values (e.g., 'thing=1,2,3').
        params_csv (bool): Set to ``True`` to encode list values
            in query string params as comma-separated values
            (e.g., 'thing=1,2,3'). Otherwise, parameters will be encoded by
            specifying multiple instances of the parameter
            (e.g., 'thing=1&thing=2&thing=3'). Defaults to ``False``.
        query_string (str): A raw query string to include in the
            request (default: ``None``). If specified, overrides
            `params`.
        content_type (str): The value to use for the Content-Type header in
            the request. If specified, this value will take precedence over
            any value set for the Content-Type header in the
            `headers` keyword argument. The ``falcon`` module provides a number
            of :ref:`constants for common media types <media_type_constants>`.
        headers (dict): Extra headers as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of strings provides the name and value
            for an HTTP header. If desired, multiple header values may be
            combined into a single (*name*, *value*) pair by joining the values
            with a comma when the header in question supports the list
            format (see also RFC 7230 and RFC 7231). Header names are not
            case-sensitive.

            Note:
                If a User-Agent header is not provided, it will default to::

                    f'falcon-client/{falcon.__version__}'

        body (str): The body of the request (default ''). The value will be
            encoded as UTF-8 in the WSGI environ. Alternatively, a byte string
            may be passed, in which case it will be used as-is.
        json(JSON serializable): A JSON document to serialize as the
            body of the request (default: ``None``). If specified,
            overrides `body` and sets the Content-Type header to
            ``'application/json'``, overriding any value specified by either
            the `content_type` or `headers` arguments.
        file_wrapper (callable): Callable that returns an iterable,
            to be used as the value for *wsgi.file_wrapper* in the
            WSGI environ (default: ``None``). This can be used to test
            high-performance file transmission when `resp.stream` is
            set to a file-like object.
        host(str): A string to use for the hostname part of the fully
            qualified request URL (default: 'falconframework.org')
        remote_addr (str): A string to use as the remote IP address for the
            request (default: '127.0.0.1'). For WSGI, this corresponds to
            the 'REMOTE_ADDR' environ variable. For ASGI, this corresponds
            to the IP address used for the 'client' field in the connection
            scope.
        http_version (str): The HTTP version to simulate. Must be either
            '2', '2.0', 1.1', '1.0', or '1' (default '1.1'). If set to '1.0',
            the Host header will not be added to the scope.
        wsgierrors (io): The stream to use as *wsgierrors* in the WSGI
            environ (default ``sys.stderr``)
        asgi_chunk_size (int): The maximum number of bytes that will be
            sent to the ASGI app in a single ``'http.request'`` event (default
            4096).
        asgi_disconnect_ttl (int): The maximum number of seconds to wait
            since the request was initiated, before emitting an
            ``'http.disconnect'`` event when the app calls the
            receive() function (default 300). Set to ``0`` to simulate an
            immediate disconnection without first emitting ``'http.request'``.
        extras (dict): Additional values to add to the WSGI
            ``environ`` dictionary or the ASGI scope for the request
            (default: ``None``)
        cookies (dict): Cookies as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of items provides the name and value
            for the 'Set-Cookie' header.

    Returns:
        :class:`~.Result`: The result of the request
    """
    return simulate_request(app, 'PUT', path, **kwargs)


def simulate_options(app: Callable[..., Any], path: str, **kwargs: Any) -> Result:
    """Simulate an OPTIONS request to a WSGI or ASGI application.

    Equivalent to::

         simulate_request(app, 'OPTIONS', path, **kwargs)

    Note:
        In the case of an ASGI request, this method will simulate the entire
        app lifecycle in a single shot, including lifespan and client
        disconnect events. In order to simulate multiple interleaved
        requests, or to test a streaming endpoint (such as one that emits
        server-sent events), :class:`~falcon.testing.ASGIConductor` can be
        used to more precisely control the app lifecycle.

    Args:
        app (callable): The application to call
        path (str): The URL path to request

    Keyword Args:
        root_path (str): The initial portion of the request URL's "path" that
            corresponds to the application object, so that the application
            knows its virtual "location". This defaults to the empty string,
            indicating that the application corresponds to the "root" of the
            server.
        protocol: The protocol to use for the URL scheme
            (default: 'http')
        port (int): The TCP port to simulate. Defaults to
            the standard port used by the given scheme (i.e., 80 for 'http'
            and 443 for 'https'). A string may also be passed, as long as
            it can be parsed as an int.
        params (dict): A dictionary of query string parameters,
            where each key is a parameter name, and each value is
            either a ``str`` or something that can be converted
            into a ``str``, or a list of such values. If a ``list``,
            the value will be converted to a comma-delimited string
            of values (e.g., 'thing=1,2,3').
        params_csv (bool): Set to ``True`` to encode list values
            in query string params as comma-separated values
            (e.g., 'thing=1,2,3'). Otherwise, parameters will be encoded by
            specifying multiple instances of the parameter
            (e.g., 'thing=1&thing=2&thing=3'). Defaults to ``False``.
        query_string (str): A raw query string to include in the
            request (default: ``None``). If specified, overrides
            `params`.
        headers (dict): Extra headers as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of strings provides the name and value
            for an HTTP header. If desired, multiple header values may be
            combined into a single (*name*, *value*) pair by joining the values
            with a comma when the header in question supports the list
            format (see also RFC 7230 and RFC 7231). Header names are not
            case-sensitive.

            Note:
                If a User-Agent header is not provided, it will default to::

                    f'falcon-client/{falcon.__version__}'

        host(str): A string to use for the hostname part of the fully
            qualified request URL (default: 'falconframework.org')
        remote_addr (str): A string to use as the remote IP address for the
            request (default: '127.0.0.1'). For WSGI, this corresponds to
            the 'REMOTE_ADDR' environ variable. For ASGI, this corresponds
            to the IP address used for the 'client' field in the connection
            scope.
        http_version (str): The HTTP version to simulate. Must be either
            '2', '2.0', 1.1', '1.0', or '1' (default '1.1'). If set to '1.0',
            the Host header will not be added to the scope.
        wsgierrors (io): The stream to use as *wsgierrors* in the WSGI
            environ (default ``sys.stderr``)
        asgi_chunk_size (int): The maximum number of bytes that will be
            sent to the ASGI app in a single ``'http.request'`` event (default
            4096).
        asgi_disconnect_ttl (int): The maximum number of seconds to wait
            since the request was initiated, before emitting an
            ``'http.disconnect'`` event when the app calls the
            receive() function (default 300). Set to ``0`` to simulate an
            immediate disconnection without first emitting ``'http.request'``.
        extras (dict): Additional values to add to the WSGI
            ``environ`` dictionary or the ASGI scope for the request
            (default: ``None``)

    Returns:
        :class:`~.Result`: The result of the request
    """
    return simulate_request(app, 'OPTIONS', path, **kwargs)


def simulate_patch(app: Callable[..., Any], path: str, **kwargs: Any) -> Result:
    """Simulate a PATCH request to a WSGI or ASGI application.

    Equivalent to::

         simulate_request(app, 'PATCH', path, **kwargs)

    Note:
        In the case of an ASGI request, this method will simulate the entire
        app lifecycle in a single shot, including lifespan and client
        disconnect events. In order to simulate multiple interleaved
        requests, or to test a streaming endpoint (such as one that emits
        server-sent events), :class:`~falcon.testing.ASGIConductor` can be
        used to more precisely control the app lifecycle.

    Args:
        app (callable): The application to call
        path (str): The URL path to request

    Keyword Args:
        root_path (str): The initial portion of the request URL's "path" that
            corresponds to the application object, so that the application
            knows its virtual "location". This defaults to the empty string,
            indicating that the application corresponds to the "root" of the
            server.
        protocol: The protocol to use for the URL scheme
            (default: 'http')
        port (int): The TCP port to simulate. Defaults to
            the standard port used by the given scheme (i.e., 80 for 'http'
            and 443 for 'https'). A string may also be passed, as long as
            it can be parsed as an int.
        params (dict): A dictionary of query string parameters,
            where each key is a parameter name, and each value is
            either a ``str`` or something that can be converted
            into a ``str``, or a list of such values. If a ``list``,
            the value will be converted to a comma-delimited string
            of values (e.g., 'thing=1,2,3').
        params_csv (bool): Set to ``True`` to encode list values
            in query string params as comma-separated values
            (e.g., 'thing=1,2,3'). Otherwise, parameters will be encoded by
            specifying multiple instances of the parameter
            (e.g., 'thing=1&thing=2&thing=3'). Defaults to ``False``.
        query_string (str): A raw query string to include in the
            request (default: ``None``). If specified, overrides
            `params`.
        content_type (str): The value to use for the Content-Type header in
            the request. If specified, this value will take precedence over
            any value set for the Content-Type header in the
            `headers` keyword argument. The ``falcon`` module provides a number
            of :ref:`constants for common media types <media_type_constants>`.
        headers (dict): Extra headers as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of strings provides the name and value
            for an HTTP header. If desired, multiple header values may be
            combined into a single (*name*, *value*) pair by joining the values
            with a comma when the header in question supports the list
            format (see also RFC 7230 and RFC 7231). Header names are not
            case-sensitive.

            Note:
                If a User-Agent header is not provided, it will default to::

                    f'falcon-client/{falcon.__version__}'

        body (str): The body of the request (default ''). The value will be
            encoded as UTF-8 in the WSGI environ. Alternatively, a byte string
            may be passed, in which case it will be used as-is.
        json(JSON serializable): A JSON document to serialize as the
            body of the request (default: ``None``). If specified,
            overrides `body` and sets the Content-Type header to
            ``'application/json'``, overriding any value specified by either
            the `content_type` or `headers` arguments.
        host(str): A string to use for the hostname part of the fully
            qualified request URL (default: 'falconframework.org')
        remote_addr (str): A string to use as the remote IP address for the
            request (default: '127.0.0.1'). For WSGI, this corresponds to
            the 'REMOTE_ADDR' environ variable. For ASGI, this corresponds
            to the IP address used for the 'client' field in the connection
            scope.
        http_version (str): The HTTP version to simulate. Must be either
            '2', '2.0', 1.1', '1.0', or '1' (default '1.1'). If set to '1.0',
            the Host header will not be added to the scope.
        wsgierrors (io): The stream to use as *wsgierrors* in the WSGI
            environ (default ``sys.stderr``)
        asgi_chunk_size (int): The maximum number of bytes that will be
            sent to the ASGI app in a single ``'http.request'`` event (default
            4096).
        asgi_disconnect_ttl (int): The maximum number of seconds to wait
            since the request was initiated, before emitting an
            ``'http.disconnect'`` event when the app calls the
            receive() function (default 300). Set to ``0`` to simulate an
            immediate disconnection without first emitting ``'http.request'``.
        extras (dict): Additional values to add to the WSGI
            ``environ`` dictionary or the ASGI scope for the request
            (default: ``None``)
        cookies (dict): Cookies as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of items provides the name and value
            for the 'Set-Cookie' header.

    Returns:
        :class:`~.Result`: The result of the request
    """
    return simulate_request(app, 'PATCH', path, **kwargs)


def simulate_delete(app: Callable[..., Any], path: str, **kwargs: Any) -> Result:
    """Simulate a DELETE request to a WSGI or ASGI application.

    Equivalent to::

         simulate_request(app, 'DELETE', path, **kwargs)

    Note:
        In the case of an ASGI request, this method will simulate the entire
        app lifecycle in a single shot, including lifespan and client
        disconnect events. In order to simulate multiple interleaved
        requests, or to test a streaming endpoint (such as one that emits
        server-sent events), :class:`~falcon.testing.ASGIConductor` can be
        used to more precisely control the app lifecycle.

    Args:
        app (callable): The application to call
        path (str): The URL path to request

    Keyword Args:
        root_path (str): The initial portion of the request URL's "path" that
            corresponds to the application object, so that the application
            knows its virtual "location". This defaults to the empty string,
            indicating that the application corresponds to the "root" of the
            server.
        protocol: The protocol to use for the URL scheme
            (default: 'http')
        port (int): The TCP port to simulate. Defaults to
            the standard port used by the given scheme (i.e., 80 for 'http'
            and 443 for 'https'). A string may also be passed, as long as
            it can be parsed as an int.
        params (dict): A dictionary of query string parameters,
            where each key is a parameter name, and each value is
            either a ``str`` or something that can be converted
            into a ``str``, or a list of such values. If a ``list``,
            the value will be converted to a comma-delimited string
            of values (e.g., 'thing=1,2,3').
        params_csv (bool): Set to ``True`` to encode list values
            in query string params as comma-separated values
            (e.g., 'thing=1,2,3'). Otherwise, parameters will be encoded by
            specifying multiple instances of the parameter
            (e.g., 'thing=1&thing=2&thing=3'). Defaults to ``False``.
        query_string (str): A raw query string to include in the
            request (default: ``None``). If specified, overrides
            `params`.
        content_type (str): The value to use for the Content-Type header in
            the request. If specified, this value will take precedence over
            any value set for the Content-Type header in the
            `headers` keyword argument. The ``falcon`` module provides a number
            of :ref:`constants for common media types <media_type_constants>`.
        headers (dict): Extra headers as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of strings provides the name and value
            for an HTTP header. If desired, multiple header values may be
            combined into a single (*name*, *value*) pair by joining the values
            with a comma when the header in question supports the list
            format (see also RFC 7230 and RFC 7231). Header names are not
            case-sensitive.

            Note:
                If a User-Agent header is not provided, it will default to::

                    f'falcon-client/{falcon.__version__}'

        body (str): The body of the request (default ''). The value will be
            encoded as UTF-8 in the WSGI environ. Alternatively, a byte string
            may be passed, in which case it will be used as-is.
        json(JSON serializable): A JSON document to serialize as the
            body of the request (default: ``None``). If specified,
            overrides `body` and sets the Content-Type header to
            ``'application/json'``, overriding any value specified by either
            the `content_type` or `headers` arguments.
        host(str): A string to use for the hostname part of the fully
            qualified request URL (default: 'falconframework.org')
        remote_addr (str): A string to use as the remote IP address for the
            request (default: '127.0.0.1'). For WSGI, this corresponds to
            the 'REMOTE_ADDR' environ variable. For ASGI, this corresponds
            to the IP address used for the 'client' field in the connection
            scope.
        http_version (str): The HTTP version to simulate. Must be either
            '2', '2.0', 1.1', '1.0', or '1' (default '1.1'). If set to '1.0',
            the Host header will not be added to the scope.
        wsgierrors (io): The stream to use as *wsgierrors* in the WSGI
            environ (default ``sys.stderr``)
        asgi_chunk_size (int): The maximum number of bytes that will be
            sent to the ASGI app in a single ``'http.request'`` event (default
            4096).
        asgi_disconnect_ttl (int): The maximum number of seconds to wait
            since the request was initiated, before emitting an
            ``'http.disconnect'`` event when the app calls the
            receive() function (default 300). Set to ``0`` to simulate an
            immediate disconnection without first emitting ``'http.request'``.
        extras (dict): Additional values to add to the WSGI
            ``environ`` dictionary or the ASGI scope for the request
            (default: ``None``)
        cookies (dict): Cookies as a dict-like (Mapping) object, or an
            iterable yielding a series of two-member (*name*, *value*)
            iterables. Each pair of items provides the name and value
            for the 'Set-Cookie' header.

    Returns:
        :class:`~.Result`: The result of the request
    """
    return simulate_request(app, 'DELETE', path, **kwargs)


class TestClient:
    """Simulate requests to a WSGI or ASGI application.

    This class provides a contextual wrapper for Falcon's ``simulate_*()``
    test functions. It lets you replace this::

        simulate_get(app, '/messages')
        simulate_head(app, '/messages')

    with this::

        client = TestClient(app)
        client.simulate_get('/messages')
        client.simulate_head('/messages')

    For convenience, :class:`TestClient` also exposes shorthand aliases without
    the ``simulate_`` prefix. Just as with a typical Python HTTP client, it is
    possible to simply call::

        client = TestClient(app)
        client.get('/messages')
        client.request('LOCK', '/files/first')

    Note:
        The methods all call ``self.simulate_request()`` for convenient
        overriding of request preparation by child classes.

    Note:
        In the case of an ASGI request, this class will simulate the entire
        app lifecycle in a single shot, including lifespan and client
        disconnect events. In order to simulate multiple interleaved
        requests, or to test a streaming endpoint (such as one that emits
        server-sent events), :class:`~falcon.testing.ASGIConductor` can be
        used to more precisely control the app lifecycle.

        An instance of :class:`~falcon.testing.ASGIConductor` may be
        instantiated directly, or obtained from an instance of
        :class:`~falcon.testing.TestClient` using the
        context manager pattern, as per the following example::

            client = falcon.testing.TestClient(app)

            # -- snip --

            async with client as conductor:
                async with conductor.simulate_get_stream('/events') as result:
                    pass

    Args:
        app (callable): A WSGI or ASGI application to target when simulating
            requests

    Keyword Arguments:
        headers (dict): Default headers to set on every request (default
            ``None``). These defaults may be overridden by passing values
            for the same headers to one of the ``simulate_*()`` methods.
    """

    # NOTE(aryaniyaps): Prevent pytest from collecting tests on the class.
    __test__ = False

    # NOTE(caseit): while any asgi/wsgi app is accept, type this as a falcon
    # app for user convenience
    app: falcon.App
    """The app that this client instance was configured to use."""

    def __init__(
        self,
        app: Callable[..., Any],  # accept any asgi/wsgi app
        headers: Optional[HeaderMapping] = None,
    ) -> None:
        self.app = app  # type: ignore[assignment]
        self._default_headers = headers
        self._conductor: Optional[ASGIConductor] = None

    async def __aenter__(self) -> ASGIConductor:
        if not _is_asgi_app(self.app):
            raise CompatibilityError(
                'a conductor context manager may only be used with a Falcon ASGI app'
            )

        # NOTE(kgriffs): We normally do not expect someone to try to nest
        #   contexts, so this is just a sanity-check.
        assert not self._conductor

        self._conductor = ASGIConductor(self.app, headers=self._default_headers)
        await self._conductor.__aenter__()

        return self._conductor

    async def __aexit__(self, ex_type: Any, ex: Any, tb: Any) -> bool:
        assert self._conductor is not None
        result = await self._conductor.__aexit__(ex_type, ex, tb)

        # NOTE(kgriffs): Reset to allow this instance of TestClient to be
        #   reused in another context.
        self._conductor = None

        return result

    def simulate_get(self, path: str = '/', **kwargs: Any) -> Result:
        """Simulate a GET request to a WSGI application.

        (See also: :meth:`falcon.testing.simulate_get`)
        """
        return self.simulate_request('GET', path, **kwargs)

    def simulate_head(self, path: str = '/', **kwargs: Any) -> Result:
        """Simulate a HEAD request to a WSGI application.

        (See also: :meth:`falcon.testing.simulate_head`)
        """
        return self.simulate_request('HEAD', path, **kwargs)

    def simulate_post(self, path: str = '/', **kwargs: Any) -> Result:
        """Simulate a POST request to a WSGI application.

        (See also: :meth:`falcon.testing.simulate_post`)
        """
        return self.simulate_request('POST', path, **kwargs)

    def simulate_put(self, path: str = '/', **kwargs: Any) -> Result:
        """Simulate a PUT request to a WSGI application.

        (See also: :meth:`falcon.testing.simulate_put`)
        """
        return self.simulate_request('PUT', path, **kwargs)

    def simulate_options(self, path: str = '/', **kwargs: Any) -> Result:
        """Simulate an OPTIONS request to a WSGI application.

        (See also: :meth:`falcon.testing.simulate_options`)
        """
        return self.simulate_request('OPTIONS', path, **kwargs)

    def simulate_patch(self, path: str = '/', **kwargs: Any) -> Result:
        """Simulate a PATCH request to a WSGI application.

        (See also: :meth:`falcon.testing.simulate_patch`)
        """
        return self.simulate_request('PATCH', path, **kwargs)

    def simulate_delete(self, path: str = '/', **kwargs: Any) -> Result:
        """Simulate a DELETE request to a WSGI application.

        (See also: :meth:`falcon.testing.simulate_delete`)
        """
        return self.simulate_request('DELETE', path, **kwargs)

    def simulate_request(self, *args: Any, **kwargs: Any) -> Result:
        """Simulate a request to a WSGI application.

        Wraps :meth:`falcon.testing.simulate_request` to perform a
        WSGI request directly against ``self.app``. Equivalent to::

            falcon.testing.simulate_request(self.app, *args, **kwargs)
        """

        if self._default_headers:
            # NOTE(kgriffs): Handle the case in which headers is explicitly
            # set to None.
            additional_headers = kwargs.get('headers') or {}

            merged_headers = dict(self._default_headers)
            merged_headers.update(additional_headers)

            kwargs['headers'] = merged_headers

        return simulate_request(self.app, *args, **kwargs)

    delete = _simulate_method_alias(simulate_delete)
    get = _simulate_method_alias(simulate_get)
    head = _simulate_method_alias(simulate_head)
    options = _simulate_method_alias(simulate_options)
    patch = _simulate_method_alias(simulate_patch)
    post = _simulate_method_alias(simulate_post)
    put = _simulate_method_alias(simulate_put)
    request = _simulate_method_alias(simulate_request)


# -----------------------------------------------------------------------------
# Private
# -----------------------------------------------------------------------------


class _AsyncContextManager:
    def __init__(self, coro: Awaitable[StreamedResult]):
        self._coro = coro
        self._obj: Optional[StreamedResult] = None

    async def __aenter__(self) -> StreamedResult:
        self._obj = await self._coro
        return self._obj

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        assert self._obj is not None
        await self._obj.finalize()
        self._obj = None


class _WSContextManager:
    def __init__(
        self, ws: helpers.ASGIWebSocketSimulator, task_req: asyncio.Task
    ) -> None:
        self._ws = ws
        self._task_req = task_req

    async def __aenter__(self) -> helpers.ASGIWebSocketSimulator:
        ready_waiter = asyncio.create_task(self._ws.wait_ready())

        # NOTE(kgriffs): Wait on both so that in the case that the request
        #   task raises an error, we don't just end up masking it with an
        #   asyncio.TimeoutError.
        await asyncio.wait(
            [ready_waiter, self._task_req],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if ready_waiter.done():
            await ready_waiter
        else:
            # NOTE(kgriffs): Retrieve the exception, if any
            await self._task_req

            # NOTE(kgriffs): This should complete gracefully (without a
            #   timeout). It may raise WebSocketDisconnected, but that
            #   is expected and desired for "normal" reasons that the
            #   request task finished without accepting the connection.
            await ready_waiter

        return self._ws

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self._ws.close()
        await self._task_req


def _prepare_sim_args(
    path: str,
    query_string: Optional[str],
    params: Optional[Mapping[str, Any]],
    params_csv: bool,
    content_type: Optional[str],
    headers: Optional[HeaderArg],
    body: Optional[Union[str, bytes]],
    json: Optional[Any],
    extras: Optional[Mapping[str, Any]],
) -> Tuple[
    str, str, Optional[HeaderArg], Optional[Union[str, bytes]], Mapping[str, Any]
]:
    if not path.startswith('/'):
        raise ValueError("path must start with '/'")

    if '?' in path:
        if query_string or params:
            raise ValueError(
                'path may not contain a query string in combination with '
                'the query_string or params parameters. Please use only one '
                'way of specifying the query string.'
            )
        path, query_string = path.split('?', 1)
    elif query_string and query_string.startswith('?'):
        raise ValueError("query_string should not start with '?'")

    extras = extras or {}

    if query_string is None:
        query_string = to_query_str(
            params,
            comma_delimited_lists=params_csv,
            prefix=False,
        )

    if content_type is not None:
        headers = dict(headers or {})
        headers['Content-Type'] = content_type

    if json is not None:
        body = json_module.dumps(json, ensure_ascii=False)
        headers = dict(headers or {})
        headers['Content-Type'] = MEDIA_JSON

    return path, query_string, headers, body, extras


def _is_asgi_app(app: Callable[..., Any]) -> bool:
    app_args = inspect.getfullargspec(app).args
    num_app_args = len(app_args)

    # NOTE(kgriffs): Technically someone could name the "self" or "cls"
    #   arg something else, but we will make the simplifying
    #   assumption that this is rare enough to not worry about.
    if app_args[0] in {'cls', 'self'}:
        num_app_args -= 1

    is_asgi = num_app_args == 3

    return is_asgi


async def _wait_for_startup(events: Iterable[AsgiEvent]) -> None:
    # NOTE(kgriffs): This is covered, but our gate for some reason doesn't
    #   understand `while True`.
    while True:  # pragma: nocover
        for e in events:
            if e['type'] == 'lifespan.startup.failed':
                raise RuntimeError(
                    'ASGI app returned lifespan.startup.failed. ' + e['message']
                )

        if any(e['type'] == 'lifespan.startup.complete' for e in events):
            break

        # NOTE(kgriffs): Yield to the concurrent lifespan task
        await asyncio.sleep(0)


async def _wait_for_shutdown(events: Iterable[AsgiEvent]) -> None:
    # NOTE(kgriffs): This is covered, but our gate for some reason doesn't
    #   understand `while True`.
    while True:  # pragma: nocover
        for e in events:
            if e['type'] == 'lifespan.shutdown.failed':
                raise RuntimeError(
                    'ASGI app returned lifespan.shutdown.failed. ' + e['message']
                )

        if any(e['type'] == 'lifespan.shutdown.complete' for e in events):
            break

        # NOTE(kgriffs): Yield to the concurrent lifespan task
        await asyncio.sleep(0)
