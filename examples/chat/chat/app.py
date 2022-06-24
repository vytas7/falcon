import falcon.asgi


def create_app():
    app = falcon.asgi.App(middleware=[cache])

    app.add_route('/users', users)

    return app
