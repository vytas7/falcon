import pytest

import falcon
import falcon.testing


__all__ = [
    'create_app',
    'create_req',
    'create_resp',
    'to_coroutine',
]


try:
    import cython as _cython  # NOQA
    CYTHON = True
except ImportError:
    CYTHON = False


ASGI_SUPPORTED = not (falcon.PY35 or CYTHON)


def create_app(asgi, **app_kwargs):
    if asgi:
        skipif_asgi_unsupported()
        from falcon.asgi import App
        return App(**app_kwargs)

    return falcon.API(**app_kwargs)


def create_req(asgi, options=None, **environ_or_scope_kwargs):
    if asgi:
        skipif_asgi_unsupported()

        req = falcon.testing.create_asgi_req(
            options=options,
            **environ_or_scope_kwargs
        )

    else:
        req = falcon.testing.create_req(
            options=options,
            **environ_or_scope_kwargs
        )

    return req


def create_resp(asgi):
    if asgi:
        skipif_asgi_unsupported()
        from falcon.asgi import Response
        return Response()

    return falcon.Response()


def to_coroutine(callable):
    async def wrapper(*args, **kwargs):
        return callable(*args, **kwargs)

    return wrapper


def skipif_asgi_unsupported():
    if not ASGI_SUPPORTED:
        pytest.skip('ASGI requires CPython or PyPy 3.6+')
