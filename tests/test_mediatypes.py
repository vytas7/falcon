import pytest

from falcon.util import mediatypes


@pytest.mark.parametrize('value,expected', [
    ('', ('', {})),
    ('text/plain', ('text/plain', {})),
    (' text/plain ', ('text/plain', {})),
    ('   text/plain   ', ('text/plain', {})),
    ('text/plain; charset=utf-8', ('text/plain', {'charset': 'utf-8'})),
    (
        'application/falcon; P1 = "key; value"; P2="\\""',
        ('application/falcon', {'p1': 'key; value', 'p2': '"'}),
    ),
])
def test_parse_header(value, expected):
    assert mediatypes.parse_header(value) == expected
