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
    terms_of_service: Annotated[str | None, Meta(key='termsOfService')]
    contact: Contact | None
    license: License | None
    version: str


class Server(Object):
    """An object representing a Server."""

    url: str
    description: str | None
    variables: Annotated[str, Meta(unsupported=True)]


class ExternalDocumentation(Object):
    """Allows referencing an external resource for extended documentation."""

    description: str | None
    url: str


class PathItem(Object):
    """Describes the operations available on a single path.

    A Path Item *MAY* be empty, due to ACL constraints.

    The path itself is still exposed to the documentation viewer but they will
    not know which operations and parameters are available.
    """

    summary: str | None
    description: str | None


class Operation(Object):
    """Describes a single API operation on a path."""

    tags: tuple[str, ...] | None
    summary: str | None
    description: str | None
    external_docs: Annotated[ExternalDocumentation | None, Meta(key='externalDocs')]
    operation_id: Annotated[str | None, Meta(key='operationId')]
    # parameters
    # requestBody
    # responses
    # callbacks
    deprecated: bool
    # security: list[SecurityRequirement]
    servers: tuple[Server, ...] | None


class OpenAPI(Object):
    """The root object of the OpenAPI Description."""

    openapi: str
    info: Info
    json_schema_dialect: Annotated[str | None, Meta(key='jsonSchemaDialect')]
    servers: tuple[Server, ...] | None
    # webhooks
    # components
    # security
    # tags
    external_docs: Annotated[ExternalDocumentation, Meta(key='externalDocs')]
