class Schema(dict):
    @classmethod
    def parse(cls, data):
        return cls(data)

    @property
    def paths(self):
        return self.get('paths') or {}


BOOKS_API = {
    'openapi': '3.0.0',
    'info': {'title': 'Book Management API', 'version': '1.0.0'},
    'paths': {
        '/books': {
            'get': {
                'summary': 'Get a list of all books',
                'responses': {'200': {'description': 'Successful response'}},
            },
            'post': {
                'summary': 'Create a new book',
                'requestBody': {
                    'description': 'Book details',
                    'required': True,
                    'content': {
                        'application/json': {
                            'schema': {
                                'type': 'object',
                                'properties': {
                                    'title': {
                                        'type': 'string',
                                        'description': 'The title of the book',
                                    },
                                    'author': {
                                        'type': 'string',
                                        'description': 'The author of the book',
                                    },
                                    'publication_year': {
                                        'type': 'integer',
                                        'description': 'The year the book was published',
                                    },
                                },
                            }
                        }
                    },
                },
                'responses': {
                    '201': {'description': 'Book created successfully'},
                    '400': {'description': 'Invalid request data'},
                },
            },
        },
        '/books/{bookid}': {
            'get': {
                'summary': 'Get details of a specific book',
                'parameters': [
                    {
                        'name': 'bookid',
                        'in': 'path',
                        'required': True,
                        'description': 'ID of the book',
                        'schema': {'type': 'integer', 'format': 'int64'},
                    }
                ],
                'responses': {
                    '200': {'description': 'Successful response'},
                    '404': {'description': 'Book not found'},
                },
            },
            'put': {
                'summary': 'Update details of a specific book',
                'parameters': [
                    {
                        'name': 'bookid',
                        'in': 'path',
                        'required': True,
                        'description': 'ID of the book',
                        'schema': {'type': 'integer', 'format': 'int64'},
                    }
                ],
                'requestBody': {
                    'description': 'Updated book details',
                    'required': True,
                    'content': {
                        'application/json': {
                            'schema': {
                                'type': 'object',
                                'properties': {
                                    'title': {
                                        'type': 'string',
                                        'description': 'The updated title of the book',
                                    },
                                    'author': {
                                        'type': 'string',
                                        'description': 'The updated author of the book',
                                    },
                                    'publication_year': {
                                        'type': 'integer',
                                        'description': 'The updated publication year of the book',
                                    },
                                },
                            }
                        }
                    },
                },
                'responses': {
                    '200': {'description': 'Book updated successfully'},
                    '400': {'description': 'Invalid request data'},
                    '404': {'description': 'Book not found'},
                },
            },
            'delete': {
                'summary': 'Delete a specific book',
                'parameters': [
                    {
                        'name': 'bookid',
                        'in': 'path',
                        'required': True,
                        'description': 'ID of the book',
                        'schema': {'type': 'integer', 'format': 'int64'},
                    }
                ],
                'responses': {
                    '204': {'description': 'Book deleted successfully'},
                    '404': {'description': 'Book not found'},
                },
            },
        },
    },
}
