import logging

from .app import create_app

# NOTE(vytas): Useful since ASGI otherwise has nothing like wsgierrors.
logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO
)

app = create_app()
