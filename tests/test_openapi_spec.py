import pytest

from falcon.openapi import spec


def test_parse():
    data = {
        'title': 'Example Pet Store App',
        'summary': 'A pet store manager.',
        'description': 'This is an example server for a pet store.',
        'termsOfService': 'https://example.com/terms/',
        'contact': {
            'name': 'API Support',
            'url': 'https://www.example.com/support',
            'email': 'support@example.com',
        },
        'license': {
            'name': 'Apache 2.0',
            'url': 'https://www.apache.org/licenses/LICENSE-2.0.html',
        },
        'version': '1.0.1',
    }

    info = spec.Info.parse(data)

    assert info.summary == 'A pet store manager.'
    assert info.version == '1.0.1'

    assert info.contact.name == 'API Support'
    assert info.contact.email == 'support@example.com'

    assert info.license.name == 'Apache 2.0'


def test_parse_complex():
    data = {
        'tags': ['pet'],
        'summary': 'Updates a pet in the store with form data',
        'operationId': 'updatePetWithForm',
        'parameters': [
            {
                'name': 'petId',
                'in': 'path',
                'description': 'ID of pet that needs to be updated',
                'required': True,
                'schema': {'type': 'string'},
            }
        ],
        'requestBody': {
            'content': {
                'application/x-www-form-urlencoded': {
                    'schema': {
                        'type': 'object',
                        'properties': {
                            'name': {
                                'description': 'Updated name of the pet',
                                'type': 'string',
                            },
                            'status': {
                                'description': 'Updated status of the pet',
                                'type': 'string',
                            },
                        },
                        'required': ['status'],
                    }
                }
            }
        },
        'responses': {
            '200': {
                'description': 'Pet updated.',
                'content': {'application/json': {}, 'application/xml': {}},
            },
            '405': {
                'description': 'Method Not Allowed',
                'content': {
                    'application/json': {},
                    'application/xml': {},
                },
            },
        },
    }

    operation = spec.Operation.parse(data)

    assert operation.tags == ('pet',)
    assert operation.operation_id == 'updatePetWithForm'

    assert len(operation.parameters) == 1
    (pet_id,) = operation.parameters
    assert pet_id.name == 'petId'
    assert pet_id.in_ == 'path'
    assert pet_id.required

    assert len(operation.responses) == 2
    resp200 = operation.responses['200']
    assert resp200.description == 'Pet updated.'


def test_empty_dict():
    data = {
        'url': 'https://development.gigantic-server.com/v1',
        'description': 'Development server',
    }

    server = spec.Server.parse(data)
    assert server.description == 'Development server'
    assert server.variables == {}


def test_missing_required_key():
    with pytest.raises(ValueError):
        spec.License.parse({})


def test_unknown_key():
    with pytest.raises(KeyError):
        spec.License.parse({'name': 'MIT', 'flavor': 'custom'})


def test_extensions():
    license = spec.License.parse({'name': 'Apache 2.0', 'x-falcon': 'peregrine'})
    assert license.name == 'Apache 2.0'
    assert license.extensions == {'x-falcon': 'peregrine'}
