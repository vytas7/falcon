class SchemaValidator:
    def __init__(self, schema):
        self._schema = schema
        self._validator = None

    def from_schema(self, schema):
        cls = type(self)
        return cls(schema)

    def _compile_validator(self):
        code = ['def validate(data):']
        # header.extend(code)
        code.append('return data')

        body = '\n    '.join(code)
        print('Function body')
        print('-------------')
        print(body)
        print('-------------')

        ast = compile(body, '<string>', 'exec')

        _globals = {}
        _locals = {}
        exec(ast, _globals, _locals)

        self._validator = _locals['validate']

    def __call__(self, data):
        return self._validator(data)
