import functools
import io
import sys

from falcon.media import BaseHandler


_CHUNK_SIZE = io.DEFAULT_BUFFER_SIZE
_BUFFER_NEEDED = _CHUNK_SIZE + 70 + 2

_ALLOWED_CONTENT_HEADERS = frozenset([
    b'content-type',
    b'content-disposition',
    b'content-transfer-encoding',
])


# TODO(vytas): Inherit from falcon.HTTPBadRequest
class MultipartParseError(Exception):
    pass


class MultipartStreamWrapper(io.IOBase):

    def __init__(self, read, pipe):
        self.read = read
        self.pipe = pipe


class BodyPart:

    _stream = None
    _data = None

    def __init__(self, read, pipe, headers):
        self._read = read
        self._pipe = pipe
        self._headers = headers

    @property
    def stream(self):
        if self._stream is None:
            self._stream = MultipartStreamWrapper(self._read, self._pipe)
        return self._stream

    @property
    def data(self):
        if self._data is None:
            self._data = self._read()
        return self._data

    @property
    def text(self):
        if self._data is None:
            self._data = self._read()
        return self._data.decode()

    @property
    def content_type(self):
        value = self._headers.get(b'content_type')
        if value is None:
            return value
        return value.decode('ascii')


class MultipartForm:

    def __init__(self, stream, boundary):
        self._stream = stream
        self._boundary = boundary

        self._dash_boundary = b'--' + boundary
        self._buffer = b''

    def _read_until(self, delimiter, amount=None):
        # TODO(vytas): This is a raw preview: optimize this code heavily;
        #   potentially cythonize the hottest paths.
        if amount is None or amount == -1:
            amount = sys.maxsize
        stream = self._stream
        result = []
        have_bytes = 0

        current = self._buffer
        while True:
            if len(current) < _BUFFER_NEEDED:
                current += stream.read(_BUFFER_NEEDED - len(current))
                if len(current) < _BUFFER_NEEDED:
                    break
            if delimiter in current:
                break

            result.append(current[:_CHUNK_SIZE])
            have_bytes += _CHUNK_SIZE
            current = current[_CHUNK_SIZE:]

            if have_bytes >= amount:
                data = b''.join(result)
                self._buffer = data[amount:]
                return data[:amount]

        data, has_delimiter, remainder = current.partition(delimiter)
        if not has_delimiter:
            raise MultipartParseError('unexpected EOF without delimiter')
        data = b''.join(result) + data
        self._buffer = data[amount:] + has_delimiter + remainder
        return data[:amount]

    def _pipe_until(self, delimiter, destination=None):
        # TODO(vytas): This is a raw preview: optimize this code heavily;
        #   potentially cythonize the hottest paths.
        stream = self._stream
        current = self._buffer

        while True:
            if len(current) < _BUFFER_NEEDED:
                current += stream.read(_BUFFER_NEEDED - len(current))
                if len(current) < _BUFFER_NEEDED:
                    break
            if delimiter in current:
                break

            if destination is not None:
                destination.write(current[:_CHUNK_SIZE])
            current = current[_CHUNK_SIZE:]

        data, has_delimiter, remainder = current.partition(delimiter)
        if not has_delimiter:
            raise MultipartParseError('unexpected EOF without delimiter')
        if destination is not None:
            destination.write(data)

        self._buffer = has_delimiter + remainder

    def __iter__(self):
        while True:
            # Either exhaust the unused part stream part, or skip prologue
            self._pipe_until(self._dash_boundary)
            self._buffer = self._buffer[len(self._dash_boundary):]

            if not self._dash_boundary.startswith(b'\r\n'):
                self._dash_boundary = b'\r\n' + self._dash_boundary

            separator = self._read_until(b'\r\n', 2)
            if separator == b'--':
                if not self._buffer.startswith(b'\r\n'):
                    raise MultipartParseError('unexpected form epilogue')
                # TODO(vytas): the tests are currently based on io.BytesIO
                # self._stream.exhaust()
                break
            elif separator:
                raise MultipartParseError('unexpected data structure')

            headers = {}
            headers_block = self._read_until(b'\r\n\r\n')
            self._buffer = self._buffer[4:]

            for line in headers_block.split(b'\r\n'):
                name, sep, value = line.partition(b': ')
                if sep:
                    name = name.lower()
                    # NOTE(vytas): Other header fields MUST NOT be included and
                    #   MUST be ignored.
                    if name in _ALLOWED_CONTENT_HEADERS:
                        headers[name] = value

            read = functools.partial(self._read_until, self._dash_boundary)
            pipe = functools.partial(self._pipe_until, self._dash_boundary)
            yield BodyPart(read, pipe, headers)


class MultipartFormHandler(BaseHandler):
    """
    Multipart form (content type ``multipart/form-data``) media handler.

    The ``multipart/form-data`` media type for HTML5 forms is defined in the
    `RFC 7578 <https://tools.ietf.org/html/rfc7578>`_.

    The multipart media type itself is defined in the
    `RFC 2046 section 5.1 <https://tools.ietf.org/html/rfc2046#section-5.1>`_.

    .. note::
       Note that unlike many others, this handler does not consume the stream
       immediately. Rather, the serialized media object shall be iterated to
       parse the body parts.
    """

    def deserialize(self, stream, content_type, content_length):
        boundary = None
        for key_value in content_type.split('; '):
            _, _, boundary = key_value.partition('boundary=')
            if boundary:
                break

        if boundary is None:
            raise MultipartParseError(
                'no boundary specifier found in {!r}'.format(content_type))

        # NOTE(vytas): If a boundary delimiter line appears to end with white
        #   space, the white space must be presumed to have been added by a
        #   gateway, and must be deleted.
        boundary = boundary.rstrip()

        # NOTE(vytas): As per RFC 2046 section 5.1, the boundary parameter
        #   consists of 1 to 70 characters from a set of characters known to be
        #   very robust through mail gateways, and NOT ending with white space.
        if not 1 <= len(boundary) <= 70:
            raise MultipartParseError(
                'the boundary parameter must consist of 1 to 70 characters')

        return MultipartForm(stream, boundary.encode())

    def serialize(self, media, content_type):
        raise NotImplementedError('multipart form serialization unsupported')
