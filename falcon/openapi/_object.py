from __future__ import annotations

from typing import Any, get_type_hints

DOC_TEMPLATE = (
    '\n\n    See also: https://spec.openapis.org/oas/v3.1.1.html#{name}-object'
)


class _Object:
    __registry__: dict[str, 'type[_Object]'] = {}
    __schema__: dict[str, Any] = {}

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        cls.__registry__[cls.__name__] = cls

        try:
            for key, value in get_type_hints(cls).items():
                pass
                # print(f'type hint {key=} {value=}')
        except Exception as ex:
            print(f'Error getting hints: {ex}')

        # TODO: Wrangle compound names.
        assert cls.__doc__ is not None
        cls.__doc__ += '\n\n' + DOC_TEMPLATE.format(name=cls.__name__.lower())

    extensions: dict[str, Any]

    def __init__(self) -> None:
        cls = type(self)
        for key in get_type_hints(cls):
            setattr(self, key, None)

    @classmethod
    def parse(cls, data: dict[str, Any]) -> '_Object':
        obj = cls()

        for key, value in get_type_hints(cls).items():
            if key not in data:
                continue
            elif issubclass(value, _Object):
                parsed_value = value.parse(data[key])
            else:
                parsed_value = data[key]

            setattr(obj, key, parsed_value)

        return obj


class _Meta:
    def __init__(
        self,
        required: bool = False,
        key: str | None = None,
        unsupported: bool = False,
    ) -> None:
        self.required = required
        self.unsupported = unsupported
