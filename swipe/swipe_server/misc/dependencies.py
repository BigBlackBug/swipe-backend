import logging

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
        session.close()


async def redis() -> aioredis.Redis:
    logging.info(f'Connecting to a redis@{settings.REDIS_URL}')
    # TODO IDK if it's the right way to use redis connections since it's a pool
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)
