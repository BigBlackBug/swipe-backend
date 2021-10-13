import logging

from swipe.database import SessionLocal

logging = logging.getLogger(__name__)


def db():
    logging.info("Creating a db connection")
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
