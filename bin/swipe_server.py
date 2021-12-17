import os
import sys

sys.path.insert(1, os.path.join(sys.path[0], '..'))

from swipe import config

config.configure_logging()
import asyncio
import datetime
import logging
import random
from pathlib import Path

import alembic.command
import alembic.config
import dateutil.parser
import sentry_sdk
import uvicorn
from fastapi_utils.tasks import repeat_every
from sqlalchemy import select

from swipe.settings import settings, constants
from swipe.swipe_server import swipe_app
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.misc.storage import storage_client
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.services.online_cache import \
    RedisOnlineUserService
from swipe.swipe_server.users.services.popular_cache import CountryCacheService, \
    PopularUserService
from swipe.swipe_server.users.services.redis_services import \
    RedisUserFetchService

if settings.SENTRY_SWIPE_SERVER_URL:
    sentry_sdk.init(
        settings.SENTRY_SWIPE_SERVER_URL,
        # TODO change in prod
        traces_sample_rate=settings.SENTRY_SAMPLE_RATE
    )
logger = logging.getLogger(__name__)

app = swipe_app.init_app()


# prometheus = Instrumentator().instrument(app).expose(app)


async def run_migrations():
    migrations_dir = str(constants.BASE_DIR.joinpath('migrations').absolute())
    alembic_cfg_dir = str(constants.BASE_DIR.joinpath('alembic.ini').absolute())

    logger.info(
        f'Running DB migrations in {migrations_dir}, {alembic_cfg_dir} '
        f'on {settings.DATABASE_URL}')
    alembic_cfg = alembic.config.Config(alembic_cfg_dir)
    alembic_cfg.set_main_option('script_location', migrations_dir)
    alembic.command.upgrade(alembic_cfg, 'head')


async def init_storage_buckets():
    logger.info("Initializing storage buckets")
    storage_client.initialize_buckets()


# TODO just for devs, remove
async def populate_online_caches():
    redis_online = RedisOnlineUserService(dependencies.redis())
    redis_fetch = RedisUserFetchService(dependencies.redis())
    logger.info("Invalidating online response cache")
    await redis_fetch.drop_fetch_response_caches()
    # TODO just for tests, because chat server is also being restarted
    logger.info("Invalidating online user cache")
    await redis_online.invalidate_online_user_cache()

    with dependencies.db_context() as db:
        last_online = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
        last_online_users = \
            db.execute(select(User).where(
                (User.last_online > last_online) &
                (User.last_online != None)  # noqa
            )).scalars().all()
        logger.info(f"Found {len(last_online_users)} "
                    f"online users during previous hour")
        for user in last_online_users:
            await redis_online.add_to_recently_online_cache(user)
            await redis_online.add_to_online_caches(user)


async def populate_country_cache():
    logger.info("Populating country cache")
    with dependencies.db_context() as db:
        cache_service = CountryCacheService(db, dependencies.redis())
        await cache_service.populate_country_cache()


# The entire piece of shit code below exists only
# because I did not want to drag celery into this
# and @repeat_every runs on every forked process
# so please forgive me :C

# I don't care anymore
popular_cache_lock = Path('/tmp/popular_cache')
popular_cache_lock.touch()


@app.on_event("startup")
@repeat_every(seconds=constants.POPULAR_CACHE_POPULATE_JOB_TIMEOUT_SEC
                      + random.randint(1, 5),
              logger=logger, wait_first=True)
async def populate_popular_cache():
    prev_runtime = popular_cache_lock.read_text()
    if prev_runtime:
        prev_runtime = dateutil.parser.parse(prev_runtime)
        if datetime.datetime.utcnow() - prev_runtime < \
                datetime.timedelta(
                    seconds=constants.POPULAR_CACHE_POPULATE_JOB_TIMEOUT_SEC):
            return

    popular_cache_lock.write_text(datetime.datetime.utcnow().isoformat())

    with dependencies.db_context() as db:
        service = PopularUserService(db, dependencies.redis())
        await service.populate_popular_cache()


recently_online_lock = Path('/tmp/recently_online')
recently_online_lock.touch()


@app.on_event("startup")
@repeat_every(seconds=constants.RECENTLY_ONLINE_CLEAR_JOB_TIMEOUT_SEC
                      + random.randint(1, 5),
              logger=logger, wait_first=True)
async def update_recently_online_cache():
    prev_runtime = recently_online_lock.read_text()
    if prev_runtime:
        prev_runtime = dateutil.parser.parse(prev_runtime)
        if datetime.datetime.utcnow() - prev_runtime < \
                datetime.timedelta(
                    seconds=constants.RECENTLY_ONLINE_CLEAR_JOB_TIMEOUT_SEC):
            return

    recently_online_lock.write_text(datetime.datetime.utcnow().isoformat())

    logger.info("Removing recently online users from the online cache")
    service = RedisOnlineUserService(dependencies.redis())
    await service.update_recently_online_cache()


loop = asyncio.get_event_loop()

if __name__ == '__main__':
    loop.run_until_complete(run_migrations())
    loop.run_until_complete(init_storage_buckets())
    loop.run_until_complete(populate_online_caches())
    loop.run_until_complete(populate_country_cache())
    loop.run_until_complete(populate_popular_cache())
    loop.run_until_complete(update_recently_online_cache())

    logger.info(f'Starting app at port {settings.SWIPE_PORT}')
    uvicorn.run('bin.swipe_server:app', host='0.0.0.0',  # noqa
                port=settings.SWIPE_PORT,
                workers=settings.SWIPE_SERVER_WORKER_NUMBER,
                reload=settings.ENABLE_WEB_SERVER_AUTORELOAD)
