# Simple HTTP server prototyping

import asyncio
import logging

from falcon._protocols._http11 import _HTTP11Protocol

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO
)


class _SimpleProtocol(asyncio.Protocol):
    def __init__(self):
        super().__init__()
        self._protocol = _HTTP11Protocol()

    def connection_made(self, transport):
        peername = transport.get_extra_info('peername')
        logging.info('New connection from {}'.format(peername))
        self.transport = transport

    def data_received(self, data):
        logging.info(f'Data received: {data}')

        self.transport.write(data)

        logging.info('Closing the client socket')
        self.transport.close()


async def _main():
    loop = asyncio.get_running_loop()

    server = await loop.create_server(_SimpleProtocol, '127.0.0.1', 8000)

    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(_main())
