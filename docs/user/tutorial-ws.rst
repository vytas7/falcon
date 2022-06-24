.. _tutorial-ws:

Tutorial (WebSocket)
====================

In this tutorial we'll walk through building a simple chat using Falcon's
WebSocket functionality.

.. note::
    Unlike other :doc:`Falcon tutorials <index>`, this document doesn't delve
    into details such as setting up a *virtualenv* or basic Falcon concepts.

    Assuming that the reader is already comfortable with the
    :ref:`ASGI flavor of the framework <tutorial-asgi>`, we'll instead focus on
    designing, developiong and testing the WebSocket and SSE parts of an async
    Falcon application.
