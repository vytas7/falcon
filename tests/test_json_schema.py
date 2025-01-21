from falcon.openapi.schema import SchemaValidator


def test_basic():
    validator = SchemaValidator({})
    validator._compile_validator()
    assert validator({}) == {}
