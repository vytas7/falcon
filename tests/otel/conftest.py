import pytest

pytest.importorskip('opentelemetry')
pytest.importorskip('opentelemetry.sdk')

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture(scope='session')
def _otel_provider():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # NOTE: opentelemetry.trace.set_tracer_provider allows only one global
    #   set per process; the session scope keeps us on the right side of that.
    trace.set_tracer_provider(provider)
    yield exporter


@pytest.fixture
def span_exporter(_otel_provider):
    _otel_provider.clear()
    yield _otel_provider
    _otel_provider.clear()
