import pytest


@pytest.mark.hello
def test_hello_metric(gauge):
    gauge('hello')


@pytest.mark.media
def test_media_metric(gauge):
    gauge('media')