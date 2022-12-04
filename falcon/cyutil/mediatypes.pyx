cdef EMPTY = ''


cdef str _trimmed(unsigned char* data, Py_ssize_t start, Py_ssize_t end):
    for pos in range(start, end):
        if data[pos] not in b' \t\r\n':
            start = pos
            break
    else:
        return EMPTY

    for pos in range(end, start+1, -1):
        if data[pos-1] not in b' \t\r\n':
            end = pos
            break

    return data[start:end].decode('utf-8')


cdef tuple _parse_bytes(unsigned char* data, Py_ssize_t length):
    cdef Py_ssize_t start = 0
    cdef Py_ssize_t end = length
    cdef Py_ssize_t pos
    cdef unsigned char c
    cdef dict params = {}
    cdef bint in_quotes = False

    for pos in range(0, length):
        c = data[pos]
        if in_quotes:
            if c == '"':
                in_quotes = False
            else:
                continue
        if c == b';':
            return (_trimmed(data, start, pos), params)
    return (_trimmed(data, start, length), params)

def parse_header(str line not None):
    cdef bytes data = line.encode()
    cdef Py_ssize_t length = len(data)
    return _parse_bytes(data, length)
