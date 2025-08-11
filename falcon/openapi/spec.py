"""OpenAPI spec support doodles. Not much to see yet."""

from __future__ import annotations

from ._object import _Object as Object

# from ._object import _Polymorphic as Polymorphic

__all__ = (
    'OpenAPI',
    'Info',
    'Contact',
    'License',
    'Server',
    'ExternalDocumentation',
    'PathItem',
    'Operation',
)


class Contact(Object):
    """Contact information for the exposed API."""

    name: str | None
    url: str | None
    email: str | None


class License(Object):
    """License information for the exposed API."""

    name: str
    identifier: str | None
    url: str | None


class Info(Object):
    """The object provides metadata about the API.

    The metadata *MAY* be used by the clients if needed, and *MAY* be presented
    in editing or documentation generation tools for convenience.
    """

    title: str
    summary: str | None
    description: str | None
    terms_of_service: str | None
    contact: Contact | None
    license: License | None
    version: str


class ServerVariable(Object):
    """A Server Variable for server URL template substitution."""

    enum: tuple[str, ...] | None
    default: str
    description: str


class Server(Object):
    """An object representing a Server."""

    url: str
    description: str | None
    variables: dict[str, ServerVariable]


class PathItem(Object):
    """Describes the operations available on a single path.

    A Path Item *MAY* be empty, due to ACL constraints.

    The path itself is still exposed to the documentation viewer but they will
    not know which operations and parameters are available.
    """

    summary: str | None
    description: str | None


class ExternalDocumentation(Object):
    """Allows referencing an external resource for extended documentation."""

    description: str | None
    url: str


class Example(Object):
    """An object grouping an example value with basic metadata.

    This object is typically used in fields named ``examples`` (plural), and is
    a referenceable alternative to older ``example`` (singular) fields that do
    not support referencing or metadata.

    Examples allow demonstration of the usage of properties, parameters and
    objects within OpenAPI.
    """

    summary: str | None
    description: str | None
    # TODO: Support Any value?
    value: dict
    external_value: str | None


class Parameter(Object):
    """Describes a single operation parameter.

    A unique parameter is defined by a combination of a name and location.
    """

    IN: str | None = None

    name: str
    in_: str
    description: str | None
    required: bool | None
    allow_empty_value: bool | None
    schema: dict | None


class QueryParameter(Parameter):
    """A cls:`Parameter` that is defined in the query."""

    IN = 'query'


class HeaderParameter(Parameter):
    """A cls:`Parameter` that is defined in a header."""

    IN = 'header'


class PathParameter(Parameter):
    """A cls:`Parameter` that is defined in the path."""

    IN = 'path'


class CookieParameter(Parameter):
    """A cls:`Parameter` that is defined in a cookie."""

    IN = 'cookie'


class MediaType(Object):
    """Provides schema and examples for the media type identified by its key.

    When ``example`` or ``examples`` are provided, the example *SHOULD* match
    the specified schema and be in the correct format as specified by the media
    type and its encoding.

    The ``example`` and ``examples`` fields are mutually exclusive, and if
    either is present it *SHALL* override any example in the schema.
    """

    schema: dict | None
    example: dict | None
    examples: dict[str, Example] | None
    # TODO(vytas): Support encoding?
    # encoding: ...


class RequestBody(Object):
    """Describes a single request body."""

    description: str | None
    content: dict[str, MediaType]
    required: bool | None


class Response(Object):
    """Describes a single response from an API :class:`Operation`."""

    description: str
    # headers
    content: dict[str, MediaType]
    # links


class Operation(Object):
    """Describes a single API operation on a path."""

    tags: tuple[str, ...] | None
    summary: str | None
    description: str | None
    external_docs: ExternalDocumentation | None
    operation_id: str | None
    parameters: tuple[Parameter, ...]
    request_body: RequestBody | None
    responses: dict[str, Response]
    # callbacks
    deprecated: bool | None
    # security: list[SecurityRequirement]
    servers: tuple[Server, ...] | None


class Tag(Object):
    """Adds metadata to a single tag that is used by the :class:`Operation` Object.

    It is not mandatory to have a :class:`Tag` Object per tag defined in the
    :class`Operation` Object instances.
    """

    name: str
    description: str | None
    external_docs: ExternalDocumentation | None


class OpenAPI(Object):
    """The root object of the OpenAPI Description."""

    openapi: str
    info: Info
    json_schema_dialect: str | None
    servers: tuple[Server, ...]
    # webhooks
    # components
    # security
    tags: tuple[Tag, ...]
    external_docs: ExternalDocumentation | None
