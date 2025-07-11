import pytest

import falcon
from falcon import testing
from falcon.instrumentation.base import Instrumentation


class TestAbstractMethods:
    class IncompleteInstrumentation(Instrumentation):
        def process_request(self, req, resp):
            pass

    def test_unimplemented_wsgi_span(self, util):
        app = util.create_app(False, _instrumentation=self.IncompleteInstrumentation())

        with pytest.raises(NotImplementedError):
            testing.simulate_get(app, '/')


class TestExceptionRecording:
    class ErrorTracer(Instrumentation):
        def __init__(self):
            self.recorded_exceptions = []

        def start_wsgi_span(self, env, start_response):
            span = env['test_instrumentation'] = object()
            return (span, start_response)

        def record_exception(self, scope, exception, fatal=False):
            self.recorded_exceptions.append(type(exception))

        def process_request(self, req, resp):
            pass

    def test_record_exceptions(self, util):
        class FaultyMiddleware:
            def process_response(self, req, resp, resource, req_succeeded):
                raise RuntimeError('middleware issue')

        tracer = self.ErrorTracer()

        app = util.create_app(False, _instrumentation=tracer)
        app.add_middleware(FaultyMiddleware())

        resp = testing.simulate_get(app, '/404')
        assert resp.status_code == 500

        assert tracer.recorded_exceptions == [falcon.HTTPRouteNotFound, RuntimeError]
