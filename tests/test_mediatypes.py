import cgi

import pytest

from falcon.util import mediatypes


@pytest.mark.parametrize(
    'value,expected',
    [
        ('', ('', {})),
        ('strange', ('strange', {})),
        ('text/plain', ('text/plain', {})),
        ('text/plain ', ('text/plain', {})),
        (' text/plain', ('text/plain', {})),
        (' text/plain ', ('text/plain', {})),
        ('   text/plain   ', ('text/plain', {})),
        (
            'falcon/peregrine;  key1; key2=value; key3',
            ('falcon/peregrine', {'key2': 'value'}),
        ),
        ('"falcon/peregrine" ; key="value"', ('"falcon/peregrine"', {'key': 'value'})),
        ('text/plain; charset=utf-8', ('text/plain', {'charset': 'utf-8'})),
        (
            'application/falcon; P1 = "key; value"; P2="\\""',
            ('application/falcon', {'p1': 'key; value', 'p2': '"'}),
        ),
    ],
)
def test_parse_header(value, expected):  # , cython_compiled):
    assert mediatypes.parse_header(value) == expected == cgi.parse_header(value)


def test_parse_simple_poc(cython_compiled):
    result = mediatypes.parse_header('  text/plain   ')
    assert result == ('text/plain', {})
