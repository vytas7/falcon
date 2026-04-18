from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from falcon.otel import _opentelemetry
from falcon.otel import _protocol


@dataclass
class InstrumentationOptions:
    excluded_urls: tuple[str, ...] = field(default_factory=tuple)


def _span_name_wsgi(environ: dict[str, Any]) -> str:
    method = environ.get('REQUEST_METHOD') or 'HTTP'
    return f'{method} {environ.get("PATH_INFO") or "/"}'


def _span_name_asgi(scope: dict[str, Any]) -> str:
    method = scope.get('method') or 'HTTP'
    return f'{method} {scope.get("path") or "/"}'


class Instrumentation:
    options: InstrumentationOptions

    def __init__(self, options: InstrumentationOptions | None = None) -> None:
        if not _opentelemetry.AVAILABLE:
            raise RuntimeError(
                'OpenTelemetry Python API is not installed. '
                'Install it with: pip install opentelemetry-api'
            )

        self.options = options or InstrumentationOptions()
        self._tracer = _opentelemetry.trace.get_tracer('falcon')
        self._wsgi_getter = _protocol.WSGICarrierGetter()
        self._asgi_getter = _protocol.ASGICarrierGetter()

    @contextmanager
    def instrument_wsgi(self, environ: dict[str, Any]) -> Iterator[Any]:
        yield from self._instrument(
            carrier=environ,
            getter=self._wsgi_getter,
            attrs=_protocol.attrs_from_wsgi_environ(environ),
            span_name=_span_name_wsgi(environ),
        )

    @contextmanager
    def instrument_asgi(self, scope: dict[str, Any]) -> Iterator[Any]:
        yield from self._instrument(
            carrier=scope,
            getter=self._asgi_getter,
            attrs=_protocol.attrs_from_asgi_scope(scope),
            span_name=_span_name_asgi(scope),
        )

    def _instrument(
        self,
        carrier: dict[str, Any],
        getter: Any,
        attrs: dict[str, Any],
        span_name: str,
    ) -> Iterator[Any]:
        trace = _opentelemetry.trace
        context = _opentelemetry.context
        extract = _opentelemetry.extract

        token = None
        if trace.get_current_span() is trace.INVALID_SPAN:
            ctx = extract(carrier, getter=getter)
            token = context.attach(ctx)
            kind = trace.SpanKind.SERVER
        else:
            ctx = context.get_current()
            kind = trace.SpanKind.INTERNAL

        span = self._tracer.start_span(
            name=span_name,
            context=ctx,
            kind=kind,
            attributes=attrs,
        )
        try:
            with trace.use_span(span, end_on_exit=False, record_exception=False):
                yield span
        finally:
            span.end()
            if token is not None:
                context.detach(token)
