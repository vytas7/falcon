from __future__ import annotations

import sys

from types import GenericAlias
from types import NoneType
from types import UnionType
from typing import Any, get_type_hints, TYPE_CHECKING

if TYPE_CHECKING:
    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing import TypeAlias
        Self: TypeAlias = '_Object'

DOC_TEMPLATE = (
    '\n\n    See also: https://spec.openapis.org/oas/v3.1.1.html#{name}-object'
)


def _to_camel_case(name: str) -> str:
    first, *words = name.split('_')
    return first + ''.join(word.title() for word in words)


class _ValueParser:
    def __init__(
        self, key: str, container: type | None, data_type: type, required: bool
    ) -> None:
        self._key = key
        self._container = container
        self._data_type = data_type
        self._required = required

    def __call__(self, value: Any, obj: _Object) -> None:
        if value is None:
            if not self._required:
                setattr(obj, self._key, None)
            elif self._container is tuple or self._container is dict:
                setattr(obj, self._key, self._container())
            else:
                raise ValueError(f'{self._key} is required')
        else:
            # TODO: DRY this mess, it is a rough PoC to "make things work".
            if self._container is tuple:
                assert isinstance(value, list)
                load: Any = self._data_type
                if issubclass(self._data_type, _Object):
                    load = self._data_type.parse
                parsed: Any = tuple(load(item) for item in value)
            elif self._container is dict:
                assert isinstance(value, dict)
                load = self._data_type
                if issubclass(self._data_type, _Object):  # pragma: nocover
                    load = self._data_type.parse
                parsed = {key: load(value) for key, value in value.items()}
            elif issubclass(self._data_type, _Object):
                parsed = self._data_type.parse(value)
            else:
                assert isinstance(value, self._data_type)
                parsed = value
            setattr(obj, self._key, parsed)

    def __repr__(self) -> str:  # pragma: nocover
        if self._required:
            return f'ValueParser<{self._key}: {self._data_type.__name__}>'
        return f'ValueParser<{self._key}: {self._data_type.__name__} | None>'


class _Object:
    __schema__: dict[str, _ValueParser]

    _extensions: tuple[tuple[str, Any], ...] = ()

    @classmethod
    def _create_parser(cls, key: str, annotation: Any) -> _ValueParser:
        required = True

        if isinstance(annotation, UnionType):
            annotation, none_type = annotation.__args__
            assert none_type is NoneType
            required = False

        if isinstance(annotation, GenericAlias):
            container: type = annotation.__origin__  # type: ignore[assignment]
            if container is tuple:
                data_type, ellipsis = annotation.__args__
                assert ellipsis is Ellipsis
            else:
                assert container is dict
                key_type, data_type = annotation.__args__
                assert key_type is str
            return _ValueParser(key, container, data_type, required)

        return _ValueParser(key, None, annotation, required)

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        cls.__schema__ = {}

        for key, annotation in get_type_hints(cls, include_extras=True).items():
            if key.startswith('_'):
                continue

            data_key = _to_camel_case(key)
            # if hasattr(annotation, '__metadata__'):
            #     (meta,) = annotation.__metadata__
            #     annotation = annotation.__origin__
            #     data_key = meta.key or data_key

            cls.__schema__[data_key] = cls._create_parser(key, annotation)

        # TODO: Wrangle compound names.
        assert cls.__doc__ is not None
        cls.__doc__ += '\n\n' + DOC_TEMPLATE.format(name=cls.__name__.lower())

    def __init__(self) -> None:
        self._extensions: tuple[tuple[str, Any], ...] = ()

        cls = type(self)
        for key in get_type_hints(cls):
            setattr(self, key, None)

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Self:
        obj = cls()

        extensions = []
        for key, value in data.items():
            if key.startswith('x-'):
                extensions.append((key, value))
            elif key not in cls.__schema__:
                raise KeyError(f'unknown key: {key}')
        obj._extensions = tuple(extensions)

        for key, parser in cls.__schema__.items():
            parser(data.get(key), obj)

        return obj

    @property
    def extensions(self) -> dict[str, Any]:
        return dict(self._extensions)


# class _Polymorphic:
#     def __init__(self, on: str) -> None:
#         self.on = on
