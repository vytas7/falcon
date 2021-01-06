import io
import cgi
import csv
import json

import falcon
from falcon import testing


class TestCapitalizingHeaderNames:

    class CustomHeadersMiddleware:
        def __init__(self, app, title_case=True, custom_capitalization=None):
            self._app = app
            self._title_case = title_case
            self._capitalization = custom_capitalization or {}

        def __call__(self, environ, start_response):
            def start_response_wrapper(status, response_headers, exc_info=None):
                if self._title_case:
                    headers = [
                        (self._capitalization.get(name, name.title()), value)
                        for name, value in response_headers]
                else:
                    headers = [
                        (self._capitalization.get(name, name), value)
                        for name, value in response_headers]
                start_response(status, headers, exc_info)

            return self._app(environ, start_response_wrapper)

    class FunkyResource:
        def on_get(self, req, resp):
            resp.set_header('x-Falcon', 'peregrine')
            resp.set_header('X-Funky-header', 'test')
            resp.media = {'message': 'Hello'}

    class CustomStartResponse:
        def __init__(self):
            self.status = None
            self.headers = None

        def __call__(self, status, headers, exc_info=None):
            self.status = status
            self.headers = dict(headers)

    def test_custom_capitalization(self):
        app = falcon.App()
        app.add_route('/test', self.FunkyResource())

        app = self.CustomHeadersMiddleware(
            app,
            custom_capitalization={'x-funky-header': 'X-FuNkY-HeADeR'},
        )

        # NOTE(vytas): We cannot use Falcon's standard simulate_request, since
        #   it opts to lowercase headers again upon creating the result object.
        environ = testing.create_environ(path='/test')
        srmock = self.CustomStartResponse()

        app(environ, srmock)

        assert srmock.status == '200 OK'
        assert srmock.headers == {
            'Content-Length': '20',
            'Content-Type': 'application/json',
            'X-Falcon': 'peregrine',
            'X-FuNkY-HeADeR': 'test',
        }


class TestOutputtingCSV:

    class Report:
        def on_get(self, req, resp):
            output = io.StringIO()
            writer = csv.writer(output, quoting=csv.QUOTE_NONNUMERIC)
            writer.writerow(('fruit', 'quantity'))
            writer.writerow(('apples', 13))
            writer.writerow(('oranges', 37))

            resp.content_type = 'text/csv'
            resp.downloadable_as = 'report.csv'
            resp.text = output.getvalue()

    class StreamingReport:
        class PseudoTextStream:
            def __init__(self):
                self.clear()

            def clear(self):
                self.result = []

            def write(self, data):
                self.result.append(data.encode())

        def fibonacci_generator(self, n=1000):
            stream = self.PseudoTextStream()
            writer = csv.writer(stream, quoting=csv.QUOTE_NONNUMERIC)
            writer.writerow(('n', 'Fibonacci Fn'))

            previous = 1
            current = 0
            for i in range(n+1):
                writer.writerow((i, current))
                previous, current = current, current + previous

                yield from stream.result
                stream.clear()

        def on_get(self, req, resp):
            resp.content_type = 'text/csv'
            resp.downloadable_as = 'report.csv'
            resp.stream = self.fibonacci_generator(n=10)

    def _test_csv_report(self, resource, expected):
        app = falcon.App()
        app.add_route('/files/report.csv', resource)

        resp = testing.simulate_get(app, '/files/report.csv')

        assert resp.status_code == 200
        assert resp.headers['Content-Type'] == 'text/csv'
        assert resp.headers['Content-Disposition'] == 'attachment; filename="report.csv"'
        assert resp.text == expected

    def test_simple_report(self):
        expected = (
            '"fruit","quantity"\r\n'
            '"apples",13\r\n'
            '"oranges",37\r\n'
        )
        self._test_csv_report(self.Report(), expected)

    def test_streaming_report(self):
        expected = (
            '"n","Fibonacci Fn"\r\n'
            '0,0\r\n'
            '1,1\r\n'
            '2,1\r\n'
            '3,2\r\n'
            '4,3\r\n'
            '5,5\r\n'
            '6,8\r\n'
            '7,13\r\n'
            '8,21\r\n'
            '9,34\r\n'
            '10,55\r\n'
        )
        self._test_csv_report(self.StreamingReport(), expected)


class TestPrettifyingJSON:

    class CustomJSONHandler(falcon.media.BaseHandler):
        MAX_INDENT_LEVEL = 8

        def deserialize(self, stream, content_type, content_length):
            data = stream.read()
            return json.loads(data.decode())

        def serialize(self, media, content_type):
            _, params = cgi.parse_header(content_type)
            indent = params.get('indent')
            if indent is not None:
                try:
                    indent = int(indent)
                    # NOTE: Impose a reasonable indentation level limit.
                    if indent < 0 or indent > self.MAX_INDENT_LEVEL:
                        indent = None
                except ValueError:
                    # TODO: Handle invalid params?
                    indent = None

            result = json.dumps(media, indent=indent, sort_keys=bool(indent))
            return result.encode()
