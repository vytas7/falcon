import io

DEFAULT_CHUNK_SIZE = io.DEFAULT_BUFFER_SIZE * 2


cdef class BufferedStream:

    cdef _read
    cdef int _chunk_size

    cdef bytes _buffer
    cdef int _buffer_len
    cdef int _max_bytes_remaining

    def __cinit__(self, read, max_stream_len, chunk_size=None):
        self._read = read
        self._chunk_size = chunk_size or DEFAULT_CHUNK_SIZE

        self._buffer = b''
        self._buffer_len = 0
        self._max_bytes_remaining = max_stream_len

    def read(self, amount=-1):
        if (amount == -1 or amount is None or
                amount >= self._max_bytes_remaining + self._buffer_len):
            amount = self._max_bytes_remaining + self._buffer_len

        if self._buffer_len == 0:
            self._max_bytes_remaining -= amount
            return self._read(amount)

        if amount == self._buffer_len:
            result = self._buffer
            self._buffer_len = 0
            self._buffer = b''
            return result

        if amount < self._buffer_len:
            result = self._buffer[:amount]
            self._buffer_len -= amount
            self._buffer = self._buffer[amount:]
            return result

        # NOTE(vytas): if amount > self._buffer_len
        self._buffer_len = 0
        result = self._buffer
        self._buffer = b''
        self._max_bytes_remaining -= amount - self._buffer_len
        return result + self._read(amount - self._buffer_len)

    def read_until(self, delimiter, amount=-1, missing_delimiter_error=None):
        if (amount == -1 or amount is None or
                amount >= self._max_bytes_remaining + self._buffer_len):
            amount = self._max_bytes_remaining + self._buffer_len

        result = []
        have_bytes = 0
        delimiter_len_1 = len(delimiter) - 1
        if not 0 <= delimiter_len_1 < self._chunk_size:
            raise ValueError('delimiter length must be within [1, chunk_size]')

        while True:
            if delimiter in self._buffer:
                break

            read_amount = self._chunk_size
            if read_amount > self._max_bytes_remaining:
                read_amount = self._max_bytes_remaining
            self._max_bytes_remaining -= read_amount
            next_chunk = self._read(read_amount)
            next_chunk_len = len(next_chunk)
            if self._buffer_len == 0:
                self._buffer_len = next_chunk_len
                self._buffer = next_chunk
                continue
            if next_chunk_len < self._chunk_size:
                self._buffer_len += next_chunk_len
                self._buffer += next_chunk
                break

            if delimiter_len_1 > 0:
                if delimiter in (self._buffer[-delimiter_len_1:] +
                                 next_chunk[:delimiter_len_1]):
                    self._buffer_len += next_chunk_len
                    self._buffer += next_chunk
                    break

            have_bytes += self._buffer_len

            if have_bytes >= amount:
                if not result:
                    if have_bytes == amount:
                        self._buffer_len = next_chunk_len
                        self._buffer = next_chunk
                        return self._buffer

                    ret_value = self._buffer[:amount]
                    self._buffer_len = have_bytes - amount + next_chunk_len
                    self._buffer = self._buffer[amount:] + next_chunk
                    return ret_value

                if have_bytes == amount:
                    result.append(self._buffer)
                    self._buffer_len = next_chunk_len
                    self._buffer = next_chunk
                    return b''.join(result)

                result.append(self._buffer[:have_bytes-amount])
                self._buffer_len = have_bytes - amount + next_chunk_len
                self._buffer = self._buffer[have_bytes-amount:] + next_chunk
                return b''.join(result)

            result.append(self._buffer)
            self._buffer_len = next_chunk_len
            self._buffer = next_chunk

        data, found_delimiter, remainder = self._buffer.partition(delimiter)
        if not found_delimiter:
            if missing_delimiter_error:
                raise missing_delimiter_error(
                    'unexpected EOF without delimiter')
            raise RuntimeError('TODO')

        result.append(data[:amount-have_bytes])
        self._buffer = data[amount-have_bytes:] + found_delimiter + remainder
        self._buffer_len = len(self._buffer)
        return b''.join(result)

    def pipe(self, destination=None):
        destination_is_not_none = (destination is not None)

        while True:
            chunk = self.read(self._chunk_size)
            if not chunk:
                break

            if destination_is_not_none:
                destination.write(chunk)

    def pipe_until(self, delimiter, destination=None):
        destination_is_not_none = (destination is not None)

        while True:
            chunk = self.read_until(delimiter, self._chunk_size)
            if not chunk:
                break

            if destination_is_not_none:
                destination.write(chunk)

    def exhaust(self):
        self.pipe()

    def readline(self, size=-1):
        return self.read_until(b'\n', size) + self.read(1)

    # --- implementing IOBase methods, the duck-typing way ---

    def readable(self):
        """Always returns ``True``."""
        return True

    def seekable(self):
        """Always returns ``False``."""
        return False

    def writeable(self):
        """Always returns ``False``."""
        return False
