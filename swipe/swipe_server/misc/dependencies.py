import logging
from contextlib import contextmanager

import aioredis
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server.misc.database import SessionLocal

logging = logging.getLogger(__name__)


def db() -> Session:
    logging.info(f'Connecting to a database@{settings.DATABASE_URL}')
    session = SessionLocal()
    try:
        yield session
    finally:
        logging.info(f'Closing connection@{settings.DATABASE_URL}')
        session.close()


@contextmanager
def db_context() -> Session:
    logging.info(f'Connecting to a database@{settings.DATABASE_URL}')
    session = SessionLocal()
    try:
        yield session
    finally:
        logging.info(f'Closing connection@{settings.DATABASE_URL}')
        session.close()


logging.info(f'Connecting to a redis@{settings.REDIS_URL}')
redis_pool = aioredis.ConnectionPool.from_url(
    settings.REDIS_URL, decode_responses=True)


def redis() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=redis_pool)
