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

"""Instrumentation interface."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

from falcon._typing import AsgiReceive
from falcon._typing import AsgiSend
from falcon._typing import StartResponse
from falcon._typing import WSGIEnvironment

if TYPE_CHECKING:
    from falcon.asgi import Request as ASGIRequest
    from falcon.asgi import Response as ASGIResponse
    from falcon.asgi import WebSocket
    from falcon.request import Request as WSGIRequest
    from falcon.response import Response as WSGIResponse

__all__ = ('Instrumentation',)

Span = object


class Instrumentation:
    """Base intrumentation interface.

    Note:
        This class does not derive from ABC, because...

    In order to make the instrumentation class usable, either
    :meth:`start_wsgi_span` or :meth:`start_asgi_span` must be implemented.
    """

    def start_wsgi_span(
        self, env: WSGIEnvironment, start_response: StartResponse
    ) -> Tuple[Optional[Span], StartResponse]:
        """Start a WSGI request span.

        This method has the same signature as a WSGI app callable.

        Args:
            env (dict): A WSGI environment dictionary.
            start_response (callable): A WSGI helper function for setting
                status and headers on a response.

        Returns:
            tuple: A 2-member tuple consisting of the newly started span,
            and the (potentially wrapped) `start_response` function.
        """
        raise NotImplementedError(
            f'{type(self).__qualname__} must implement start_wsgi_span() for '
            f'compatibility with synchronous (WSGI) Falcon apps.'
        )

    def start_asgi_span(
        self, scope: Dict[str, Any], receive: AsgiReceive, send: AsgiSend
    ) -> Tuple[Optional[Span], AsgiReceive, AsgiSend]:
        """Start an ASGI request span.

        This method has the same signature as an ASGI app callable.

        Args:
            scope (dict): A WSGI scope dictionary.
            receive (coroutine function): An ASGI receive function yielding a
                new event dictionary when one is available.
            send (coroutine function): An ASGI send function taking a single
               event dictionary as a positional argument that will return once
               the send has been completed, or the connection has been closed.
        """
        raise NotImplementedError(
            f'{type(self).__qualname__} must implement start_asgi_span() for '
            f'compatibility with asynchronous (ASGI) Falcon apps.'
        )  # pragma: nocover

    def record_exception(
        self, scope: Dict[str, Any], exception: Exception, fatal: bool = False
    ) -> None:
        pass  # pragma: nocover

    def process_teardown(
        self,
        req: WSGIRequest,
        resp: WSGIResponse,
        resource: object,
        req_succeeded: bool,
    ) -> None:
        pass  # pragma: nocover

    async def process_teardown_async(
        self, req: ASGIRequest, resp: ASGIResponse, resource: object
    ) -> None:
        pass  # pragma: nocover

    async def process_teardown_ws(
        self, req: ASGIRequest, ws: WebSocket, resource: object
    ) -> None:
        pass  # pragma: nocover
