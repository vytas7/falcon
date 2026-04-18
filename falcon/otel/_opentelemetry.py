try:
    from opentelemetry import context
    from opentelemetry import trace
    from opentelemetry.propagate import extract

    AVAILABLE = True

except ImportError:
    context = None
    trace = None
    extract = None

    AVAILABLE = False


__all__ = ('AVAILABLE', 'context', 'extract', 'trace')
