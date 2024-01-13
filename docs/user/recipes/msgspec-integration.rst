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

Using ``msgspec`` for handling MessagePack or YAML media is slightly more
involved, as we would need to implement the :class:`~falcon.media.BaseHandler`
interface:

.. code:: python

    from falcon.media import BaseHandler
    import msgspec

    class MyMessagePackHandler(BaseHandler):
        def deserialize(self, stream, content_type, content_length):
            return msgspec.msgpack.decode(stream.read())

        def serialize(self, media, content_type):
            return msgspec.msgpack.encode(media)
