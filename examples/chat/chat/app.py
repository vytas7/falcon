import falcon.asgi

from .hub import Hub
from .users import UserResource, UserStore


def create_app():
    app = falcon.asgi.App()

    user_store = UserStore()
    hub = Hub(user_store)
    users = UserResource(user_store)
    app.add_route('/users', users, suffix='collection')
    app.add_route('/websocket/{userid}', hub)

    return app
