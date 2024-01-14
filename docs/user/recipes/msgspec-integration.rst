.. _msgspec-recipe:

Basic msgspec integration
=========================

This recipe illustrates how the popular
`msgspec <https://jcristharif.com/msgspec/>`__ data serialization and
validation library can be used with Falcon.

Media handlers
--------------

``msgspec`` can be used for JSON serialization by simply instantiating
:class:`~falcon.media.JSONHandler` with the ``msgspec.json.decode`` and
``msgspec.json.encode`` functions:

.. code:: python

    from falcon import media
    import msgspec

    json_handler = media.JSONHandler(
        dumps=msgspec.json.encode,
        loads=msgspec.json.decode,
    )

.. note::
   It would be more efficient to use preconstructed ``msgspec.json.Decoder``
   and ``msgspec.json.Encoder`` instead of initializing them every time via
   ``msgspec.json.decode`` and ``msgspec.json.encode``, respectively.
   This optimization is left as an exercise for the reader.

Using ``msgspec`` for handling MessagePack or YAML media is slightly more
involved, as we need to implement the :class:`~falcon.media.BaseHandler`
interface:

.. code:: python

    from falcon.media import BaseHandler
    import msgspec

    class MsgspecMessagePackHandler(BaseHandler):
        def deserialize(self, stream, content_type, content_length):
            return msgspec.msgpack.decode(stream.read())

        def serialize(self, media, content_type):
            return msgspec.msgpack.encode(media)

    msgspec_handler = MsgspecMessagePackHandler()

We can now use these handlers for request and response media
(see also: :ref:`custom_media_handlers`).

Media validation
----------------

Falcon currently only provides optional media validation using JSON Schema, so
we will implement validation separately using
:ref:`process_resource middleware <middleware>`. To that end, let us assume
that resources may expose schema attributes based on the HTTP verb:
``PATCH_SCHEMA``, ``POST_SCHEMA``, etc, pointing to the ``msgspec.Struct`` in
question. We will inject the validated object into `params`:

.. code:: python

    import msgspec

    class MsgspecMiddleware:
        def process_request(self, req, resp, resource, params):
            schema = getattr(resource, f'{req.method}_SCHEMA', None)
            if schema:
                param = schema.__name__.lower()
                params[param] = msgspec.convert(req.get_media(), schema)

Complete example
----------------

(In progress.)
