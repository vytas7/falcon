import io

# import pytest

# import falcon
from falcon.util import BufferedStream


def test_bounded_read():
    stream = io.BytesIO(b'Hello, world!')
    buffered = BufferedStream(stream.read, len('Hello, world'))
    buffered.read()

    assert stream.read() == b'!'


def test_readline():
    source = (
        b'Hello, world!\n'
        b'A line.\n'
        b'\n'
        b'A longer line... \n' +
        b'SPAM ' * 10 + b'\n' +
        b'\n'
    )

    stream = BufferedStream(io.BytesIO(source).read, len(source))
    assert stream.readline() == b'Hello, world!\n'
    assert stream.readline() == b'A line.\n'
    assert stream.readline() == b'\n'
    assert stream.readline() == b'A longer line... \n'


def test_read_until():
    source = (
        b'123456789ABCDEF\n' * 64 * 1024 * 64 +
        b'--boundary1234567890--' +
        b'123456789ABCDEF\n' * 64 * 1024 * 63 +
        b'--boundary1234567890--' +
        b'123456789ABCDEF\n' * 64 * 1024 * 62 +
        b'--boundary1234567890--'
    )

    stream = BufferedStream(io.BytesIO(source).read, len(source))

    assert len(stream.read_until(b'--boundary1234567890--')) == 64 * 1024**2
    stream.read_until(b'123456789ABCDEF\n')
    assert len(stream.read_until(b'--boundary1234567890--')) == 63 * 1024**2
    stream.read_until(b'123456789ABCDEF\n')
    assert len(stream.read_until(b'--boundary1234567890--')) == 62 * 1024**2
