from __future__ import annotations

from types import UnionType
from typing import Any, get_type_hints

DOC_TEMPLATE = (
    '\n\n    See also: https://spec.openapis.org/oas/v3.1.1.html#{name}-object'
)


class _ValueParser:
    def __init__(self, key: str, data_type: type, required: bool) -> None:
        self._key = key
        self._data_type = data_type
        self._required = required

    def __call__(self, value: Any, obj: _Object) -> None:
        if value is None:
            if self._required:
                raise ValueError(f'{self._key} is required')
            setattr(obj, self._key, None)
        else:
            if issubclass(self._data_type, _Object):
                parsed: Any = self._data_type.parse(value)
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
        if isinstance(annotation, UnionType):
            data_type, none_type = annotation.__args__
            assert none_type is type(None)
            return _ValueParser(key, data_type, False)

        # if isinstance(annotation, GenericAlias):
        #     print('_c_p: not implemented', key, annotation)
        #     return None  # type: ignore[return-value]

        return _ValueParser(key, annotation, True)

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        cls.__schema__ = {}

        for key, annotation in get_type_hints(cls, include_extras=True).items():
            if key.startswith('_'):
                continue

            data_key = key
            if hasattr(annotation, '__metadata__'):
                (meta,) = annotation.__metadata__
                annotation = annotation.__origin__
                data_key = meta.key or data_key

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
    def parse(cls, data: dict[str, Any]) -> '_Object':
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


class _Meta:
    def __init__(
        self,
        required: bool = False,
        key: str | None = None,
        unsupported: bool = False,
    ) -> None:
        self.required = required
        self.unsupported = unsupported
        self.key = key
