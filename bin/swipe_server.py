import datetime
import os
import sys

import uvicorn
from sqlalchemy import select

sys.path.insert(1, os.path.join(sys.path[0], '..'))

from swipe import config

config.configure_logging()
import logging

import alembic.command
import alembic.config
from fastapi_utils.tasks import repeat_every
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.redis_services import RedisOnlineUserService, \
    RedisUserFetchService
from swipe.swipe_server.users.services import PopularUserService, \
    CountryCacheService
from swipe.swipe_server.misc.storage import storage_client
from swipe.swipe_server.misc import dependencies
from swipe.settings import settings, constants
from swipe.swipe_server import swipe_app
import sentry_sdk

if settings.SENTRY_SWIPE_SERVER_URL:
    sentry_sdk.init(
        settings.SENTRY_SWIPE_SERVER_URL,
        # TODO change in prod
        traces_sample_rate=settings.SENTRY_SAMPLE_RATE
    )
logger = logging.getLogger(__name__)

app = swipe_app.init_app()


# prometheus = Instrumentator().instrument(app).expose(app)


@app.on_event("startup")
async def run_migrations():
    migrations_dir = str(constants.BASE_DIR.joinpath('migrations').absolute())
    alembic_cfg_dir = str(constants.BASE_DIR.joinpath('alembic.ini').absolute())

    logger.info(
        f'Running DB migrations in {migrations_dir}, {alembic_cfg_dir} '
        f'on {settings.DATABASE_URL}')
    alembic_cfg = alembic.config.Config(alembic_cfg_dir)
    alembic_cfg.set_main_option('script_location', migrations_dir)
    alembic.command.upgrade(alembic_cfg, 'head')


@app.on_event("startup")
async def invalidate_caches():
    redis_online = RedisOnlineUserService(dependencies.redis())
    redis_fetch = RedisUserFetchService(dependencies.redis())
    logger.info("Invalidating online response cache")
    await redis_fetch.drop_fetch_response_caches()
    # TODO just for tests, because chat server is also being restarted
    logger.info("Invalidating online user cache")
    await redis_online.invalidate_online_user_cache()


@app.on_event("startup")
async def init_storage_buckets():
    logger.info("Initializing storage buckets")
    storage_client.initialize_buckets()


# TODO just for devs, remove
@app.on_event("startup")
async def populate_online_cache():
    redis_online = RedisOnlineUserService(dependencies.redis())
    with dependencies.db_context() as db:
        last_online = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
        last_online_users = \
            db.execute(select(User).where(
                (User.last_online > last_online) &
                (User.last_online != None) # noqa
            )).scalars().all()
        logger.info(f"Found {len(last_online_users)} "
                    f"online users during previous hour")
        for user in last_online_users:
            await redis_online.add_to_recently_online_cache(user)
            await redis_online.add_to_online_caches(user)


@app.on_event("startup")
async def populate_country_cache():
    logger.info("Populating country cache")
    with dependencies.db_context() as db:
        cache_service = CountryCacheService(db, dependencies.redis())
        await cache_service.populate_country_cache()


@app.on_event("startup")
@repeat_every(seconds=constants.POPULAR_CACHE_POPULATE_JOB_TIMEOUT_SEC,
              logger=logger)
async def populate_popular_cache():
    logger.info("Populating popular cache")
    with dependencies.db_context() as db:
        service = PopularUserService(db, dependencies.redis())
        await service.populate_popular_cache()


@app.on_event("startup")
@repeat_every(seconds=constants.RECENTLY_ONLINE_CLEAR_JOB_TIMEOUT_SEC,
              logger=logger, wait_first=True)
async def remove_recently_online_cache():
    logger.info("Filtering recently online users")
    service = RedisOnlineUserService(dependencies.redis())
    await service.update_recently_online_cache()


if __name__ == '__main__':
    logger.info(f'Starting app at port {settings.SWIPE_PORT}')

    uvicorn.run('bin.swipe_server:app', host='0.0.0.0',  # noqa
                port=settings.SWIPE_PORT, workers=1,
                reload=settings.ENABLE_WEB_SERVER_AUTORELOAD)
