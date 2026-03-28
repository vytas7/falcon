class _ProtocolBuffer:
    def __init__(self, max_size=262144):
        self._buffer = bytearray(max_size)
        self._start = 0
        self._length = 0

        self._buffer_at_least: int = 0
        self._buffer_until: bytes | None = None
