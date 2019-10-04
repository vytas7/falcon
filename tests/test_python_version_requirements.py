import pytest

from falcon import PY35

from _util import CYTHON  # NOQA


def test_asgi():
    if PY35 or CYTHON:
        with pytest.raises(ImportError):
            import falcon.asgi
    else:
        # Should not raise
        import falcon.asgi  # NOQA
