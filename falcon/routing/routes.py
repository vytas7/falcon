import dataclasses
import typing


# TODO(vytas): Find a more perf structure
@dataclasses.dataclass
class Route:
    uri_template: str
    resource: object
    kwargs: dict
    schema: typing.Optional[dict] = None

    @property
    def suffix(self):
        self.kwargs.get('suffix')


class Routes:
    def __init__(self):
        self._schema = None
        self._routes = {}

    def add_route(self, uri_template, resource, kwargs):
        self._routes[uri_template] = Route(
            uri_template=uri_template, resource=resource, kwargs=kwargs.copy()
        )

    def get_route(self, uri_template):
        return self._routes.get(uri_template)

    def set_schema(self, schema):
        self._schema = schema

        # TODO: Also afford adding schema before routes

        for path, path_schema in self._schema.paths.items():
            route = self._routes.get(path)
            if route:
                route.schema = path_schema
