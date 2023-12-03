# Copyright 2023 by Vytautas Liuolia.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Media (aka MIME) type parsing and matching utilities."""

import typing

try:
    import cython
except ImportError:
    import falcon.cyutil._cython as cython


def _parse_header_old_stdlib(line):  # type: ignore
    """Parse a Content-type like header.

    Return the main content-type and a dictionary of options.

    Note:
        This method has been copied (almost) verbatim from CPython 3.8 stdlib.
        It is slated for removal from the stdlib in 3.13.
    """
    def _parseparam(s):  # type: ignore
        while s[:1] == ';':
            s = s[1:]
            end = s.find(';')
            while end > 0 and (s.count('"', 0, end) - s.count('\\"', 0, end)) % 2:
                end = s.find(';', end + 1)
            if end < 0:
                end = len(s)
            f = s[:end]
            yield f.strip()
            s = s[end:]

    parts = _parseparam(';' + line)
    key = parts.__next__()
    pdict = {}
    for p in parts:
        i = p.find('=')
        if i >= 0:
            name = p[:i].strip().lower()
            value = p[i + 1 :].strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
                value = value.replace('\\\\', '\\').replace('\\"', '"')
            pdict[name] = value
    return key, pdict


@cython.cfunc
@cython.annotation_typing(True)
def _trimmed(data: cython.p_uchar, start: cython.Py_ssize_t, end:
             cython.Py_ssize_t):
    pos: cython.Py_ssize_t

    for pos in range(start, end):
        if data[pos] not in b' \t\r\n':
            start = pos
            break
    else:
        return ''

    for pos in range(end, start+1, -1):
        if data[pos-1] not in b' \t\r\n':
            end = pos
            break

    return data[start:end].decode('utf-8')


@cython.annotation_typing(True)
def parse_header(line: str) -> typing.Tuple[str, dict]:
    if cython.compiled:
        line_encoded: bytes = line.encode()
        data: cython.p_uchar = line_encoded
        length: cython.Py_ssize_t = len(data)
        return (_trimmed(data, 0, length), {})

    # Python fallback
    elif '"' not in line and '\\' not in line:
        key, semicolon, parts = line.partition(';')
        if not semicolon:
            return (key.strip(), {})

        pdict = {}
        for part in parts.split(';'):
            name, equals, value = part.partition('=')
            if equals:
                pdict[name.strip().lower()] = value.strip()

        return (key.strip(), pdict)

    return _parse_header_old_stdlib(line)


__all__ = ['parse_header']
