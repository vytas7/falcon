import os

import pytest

try:
    import cython
except ImportError:
    cython = None

import falcon
import falcon.cyutil._cython


_FALCON_TEST_ENV = (
    ('FALCON_ASGI_WRAP_NON_COROUTINES', 'Y'),
    ('FALCON_TESTING_SESSION', 'Y'),
    # NOTE: PYTHONASYNCIODEBUG is optional (set in tox.ini).
    # ('PYTHONASYNCIODEBUG', '1'),
)


@pytest.fixture(params=[True, False], ids=['asgi', 'wsgi'])
def asgi(request):
    return request.param


@pytest.fixture(params=[True, False], ids=['cython-compiled', 'pure-python'])
def cython_compiled(request, monkeypatch):
    compiled = request.param

    if cython is not None:
        if compiled != cython.compiled:
            pytest.skip(f'Real Cython is available; compiled: {cython.compiled}')
    else:
        monkeypatch.setattr(falcon.cyutil._cython, 'compiled', compiled)

    return compiled


# NOTE(kgriffs): Some modules actually run a wsgiref server, so
# to ensure we reset the detection for the other modules, we just
# run this fixture before each one is tested.
@pytest.fixture(autouse=True, scope='module')
def reset_request_stream_detection():
    falcon.Request._wsgi_input_type_known = False
    falcon.Request._always_wrap_wsgi_input = False


def pytest_configure(config):
    if config.pluginmanager.getplugin('asyncio'):
        config.option.asyncio_mode = 'strict'

    mypy_plugin = config.pluginmanager.getplugin('mypy')
    if mypy_plugin:
        mypy_plugin.mypy_argv.append('--ignore-missing-imports')


def pytest_sessionstart(session):
    for key, value in _FALCON_TEST_ENV:
        os.environ.setdefault(key, value)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    if hasattr(item, 'cls') and item.cls:
        item.cls._item = item

    yield
