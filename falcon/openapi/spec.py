"""OpenAPI spec support doodles. Not much to see yet."""

from __future__ import annotations

from typing import Annotated

from ._object import _Meta as Meta
from ._object import _Object as Object

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


class OpenAPI(Object):
    """The root object of the OpenAPI Description."""

    openapi: str
    info: Annotated[Info, Meta(required=True)]
    json_schema_dialect: Annotated[str, Meta(key='jsonSchemaDialect')]
    servers: list[Server]
    # webhooks
    # components
    # security
    # tags
    external_docs: Annotated[ExternalDocumentation, Meta(key='externalDocs')]


class Info(Object):
    """The object provides metadata about the API.

    The metadata *MAY* be used by the clients if needed, and *MAY* be presented
    in editing or documentation generation tools for convenience.
    """

    title: Annotated[str, Meta(required=True)]
    summary: str
    description: str
    terms_of_service: Annotated[str, Meta(key='termsOfService')]
    contact: Contact
    license: License
    version: Annotated[str, Meta(required=True)]


class Contact(Object):
    """Contact information for the exposed API."""

    name: str
    url: str
    email: str


class License(Object):
    """License information for the exposed API."""

    name: Annotated[str, Meta(required=True)]
    identifier: str
    url: str


class Server(Object):
    """An object representing a Server."""

    url: Annotated[str, Meta(required=True)]
    description: str
    variables: Annotated[str, Meta(unsupported=True)]


class ExternalDocumentation(Object):
    """Allows referencing an external resource for extended documentation."""

    description: str
    url: Annotated[str, Meta(required=True)]


class PathItem(Object):
    """Describes the operations available on a single path.

    A Path Item *MAY* be empty, due to ACL constraints.

    The path itself is still exposed to the documentation viewer but they will
    not know which operations and parameters are available.
    """

    summary: str
    description: str


class Operation(Object):
    """Describes a single API operation on a path."""

    tags: list[str]
    summary: str
    description: str
    external_docs: Annotated[ExternalDocumentation, Meta(key='externalDocs')]
    operation_id: Annotated[str, Meta(key='operationId')]
    # parameters
    # requestBody
    # responses
    # callbacks
    deprecated: bool
    # security: list[SecurityRequirement]
    servers: list[Server]
