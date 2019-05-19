import io

import pytest

import falcon
from falcon import media
from falcon import testing


class MockBoundedStream(io.BytesIO):

    def exhaust(self):
        self.read()


EXAMPLE1 = (
    b'--5b11af82ab65407ba8cdccf37d2a9c4f\r\n'
    b'Content-Disposition: form-data; name="hello"\r\n\r\n'
    b'world\r\n'
    b'--5b11af82ab65407ba8cdccf37d2a9c4f\r\n'
    b'Content-Disposition: form-data; name="document"\r\n'
    b'Content-Type: application/json\r\n\r\n'
    b'{"debug": true, "message": "Hello, world!", "score": 7}\r\n'
    b'--5b11af82ab65407ba8cdccf37d2a9c4f\r\n'
    b'Content-Disposition: form-data; name="file1"; filename="test.txt"\r\n'
    b'Content-Type: text/plain\r\n\r\n'
    b'Hello, world!\n\r\n'
    b'--5b11af82ab65407ba8cdccf37d2a9c4f--\r\n')

EXAMPLE2 = (
    b'-----------------------------1574247108204320607285918568\r\n'
    b'Content-Disposition: form-data; name="description"\r\n\r\n'
    b'\r\n'
    b'-----------------------------1574247108204320607285918568\r\n'
    b'Content-Disposition: form-data; name="moderation"\r\n\r\n'
    b'approved\r\n'
    b'-----------------------------1574247108204320607285918568\r\n'
    b'Content-Disposition: form-data; name="title"\r\n\r\n'
    b'A simple text file example.\r\n'
    b'-----------------------------1574247108204320607285918568\r\n'
    b'Content-Disposition: form-data; name="uploadid"\r\n\r\n'
    b'00l33t0174873295\r\n'
    b'-----------------------------1574247108204320607285918568\r\n'
    b'Content-Disposition: form-data; name="file"; filename="test.txt"\r\n'
    b'Content-Type: text/plain\r\n\r\n'
    b'Hello, world!\n'
    b'\r\n'
    b'-----------------------------1574247108204320607285918568--\r\n'
)

EXAMPLE3 = (
    b'--BOUNDARY\r\n'
    b'Content-Disposition: form-data; name="file"; filename="bytes"\r\n'
    b'Content-Type: application/x-falcon\r\n\r\n' +
    b'123456789abcdef\n' * 64 * 1024 +
    b'\r\n'
    b'--BOUNDARY\r\n'
    b'Content-Disposition: form-data; name="empty"\r\n'
    b'Content-Type: text/plain\r\n\r\n'
    b'\r\n'
    b'--BOUNDARY--\r\n'
)


@pytest.mark.parametrize('example,boundary', [
    (EXAMPLE1, '5b11af82ab65407ba8cdccf37d2a9c4f'),
    (EXAMPLE2, '---------------------------1574247108204320607285918568'),
    (EXAMPLE3, 'BOUNDARY'),
])
def test_parse(example, boundary):
    handler = media.MultipartFormHandler()
    form = handler.deserialize(
        MockBoundedStream(example),
        'multipart/form-data; boundary=' + boundary,
        len(example))

    for part in form:
        output = io.BytesIO()
        part.stream.pipe(output)
        assert isinstance(output.getvalue(), bytes)


class TextParser:
    def on_post(self, req, resp):
        values = []
        for part in req.media:
            values.append({
                'content_type': part.content_type,
                'filename': part.filename,
                'name': part.name,
                'text': part.text,
            })

        resp.media = values


def test_e2e():
    handlers = media.Handlers({
        falcon.MEDIA_JSON: media.JSONHandler(),
        falcon.MEDIA_MULTIPART: media.MultipartFormHandler(),
    })
    api = falcon.API()
    api.req_options.media_handlers = handlers
    api.add_route('/media', TextParser())

    client = testing.TestClient(api)

    resp = client.simulate_post(
        '/media',
        headers={
            'Content-Type':
            'multipart/form-data; boundary=5b11af82ab65407ba8cdccf37d2a9c4f',
        },
        body=EXAMPLE1)

    assert resp.json == [
        {
            'content_type': 'text/plain',
            'filename': None,
            'name': 'hello',
            'text': 'world',
        },
        {
            'content_type': 'application/json',
            'filename': None,
            'name': 'document',
            'text': '{"debug": true, "message": "Hello, world!", "score": 7}'},
        {
            'content_type': 'text/plain',
            'filename': 'test.txt',
            'name': 'file1',
            'text': 'Hello, world!\n',
        },
    ]
