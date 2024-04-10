import uuid

import falcon
import falcon.routing.schema
import jsonschema


class Books:
    def __init__(self):
        self._store = {}

    def on_get(self, req, resp):
        resp.media = self._store

    def on_post(self, req, resp):
        bookid = str(uuid.uuid4())
        book = req.get_media()
        jsonschema.validate(
            book,
            req.schema['requestBody']['content'][req.content_type]['schema'],
        )
        self._store[bookid] = book
        resp.location = f'{req.path}/{bookid}'
        resp.status = 201

    def on_get_book(self, req, resp, bookid):
        book = self._store.get(bookid)
        if not book:
            raise falcon.HTTPNotFound
        resp.media = book

    def on_delete_book(self, req, resp, bookid):
        self._store.pop(bookid, None)
        resp.status = 204

    def on_put_book(self, req, resp, bookid):
        self._store[bookid] = req.get_media()


class DebugSchema:
    def process_resource(self, req, resp, resource, params):
        print(f'{req.method} {req.path} {params}')
        print(f'{req.route=}')
        print(f'{req.schema=}')


def handle_validation_error(req, resp, ex, params):
    raise falcon.HTTPUnprocessableEntity(
        title='ValidationError', description=str(ex)
    )


app = falcon.App(middleware=DebugSchema())
books = Books()
app.add_route('/books', books)
app.add_route('/books/{bookid}', books, suffix='book')

app.add_schema(falcon.routing.schema.BOOKS_API)

app.add_error_handler(jsonschema.ValidationError, handle_validation_error)
