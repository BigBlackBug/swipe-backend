import logging

from settings import settings
from swipe.database import SessionLocal

logging = logging.getLogger(__name__)


def db():
    logging.info(f'Connecting to a database@{settings.DATABASE_URL}')
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
