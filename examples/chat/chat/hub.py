import asyncio
import logging

import falcon
import falcon.asgi


class Client:
    MAX_QUEUE_SIZE = 1024

    def __init__(self, send_media):
        self._queue = asyncio.Queue(maxsize=self.MAX_QUEUE_SIZE)
        self._send_media = send_media

    def enqueue(self, message):
        self._queue.put_nowait(message)

    async def send(self):
        while True:
            message = await self._queue.get()
            await self._send_media(message)


class Hub:
    def __init__(self, store):
        self._clients = {}
        self._store = store

    def is_active(self, user):
        return user in self._clients

    def _create_message(self, user, action, data=None):
        return {
            'user': str(user.userid),
            'name': user.name,
            'action': action,
            'data': data,
        }

    def _broadcast(self, message):
        for client in self._clients.values():
            client.enqueue(message)

    async def on_websocket(self, req, ws, userid):
        user = self._store.get(userid)
        if user is None:
            raise falcon.HTTPForbidden

        if self.is_active(user):
            raise falcon.HTTPConflict(description=f'{user} is already connected')

        client = Client(ws.send_media)
        self._clients[user] = client
        send_task = asyncio.create_task(client.send())

        try:
            await ws.accept()
            logging.info(f'{user} connected')

            self._broadcast(self._create_message(user, 'connect'))

            while True:
                payload = await ws.receive_media()

                action = payload.get('action')
                if action != 'message':
                    logging.info(f'unsupported message from {user}: {payload}')
                    continue
                data = payload.get('data')
                if not data:
                    continue

                self._broadcast(self._create_message(user, action, data))

        finally:
            logging.info(f'{user} disconnected')
            self._clients.pop(user, None)

            send_task.cancel()

            self._broadcast(self._create_message(user, 'disconnect'))
