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
