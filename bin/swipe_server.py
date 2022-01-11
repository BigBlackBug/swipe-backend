import os
import sys

sys.path.insert(1, os.path.join(sys.path[0], '..'))

from swipe import config

config.configure_logging()
import asyncio
import logging

import alembic.command
import alembic.config
import sentry_sdk
import uvicorn
from swipe.swipe_server.users import swipe_bg_tasks
from swipe.settings import settings, constants
from swipe.swipe_server import swipe_app
from swipe.swipe_server.misc.storage import storage_client

if settings.SENTRY_SWIPE_SERVER_URL:
    sentry_sdk.init(
        settings.SENTRY_SWIPE_SERVER_URL,
        traces_sample_rate=settings.SENTRY_SAMPLE_RATE,
        release=settings.SWIPE_VERSION
    )
logger = logging.getLogger(__name__)

app = swipe_app.init_app()


def run_migrations():
    migrations_dir = str(constants.BASE_DIR.joinpath('migrations').absolute())
    alembic_cfg_dir = str(constants.BASE_DIR.joinpath('alembic.ini').absolute())

    logger.info(
        f'Running DB migrations in {migrations_dir}, {alembic_cfg_dir} '
        f'on {settings.DATABASE_URL}')
    alembic_cfg = alembic.config.Config(alembic_cfg_dir)
    alembic_cfg.set_main_option('script_location', migrations_dir)
    alembic.command.upgrade(alembic_cfg, 'head')


def init_storage_buckets():
    logger.info("Initializing storage buckets")
    storage_client.initialize_buckets()


loop = asyncio.get_event_loop()

if __name__ == '__main__':
    run_migrations()
    init_storage_buckets()

    loop.run_until_complete(swipe_bg_tasks.drop_user_cache())
    loop.run_until_complete(swipe_bg_tasks.populate_online_caches())
    loop.run_until_complete(swipe_bg_tasks.populate_country_cache())

    # these will be run periodically
    loop.run_until_complete(swipe_bg_tasks.populate_popular_cache())
    loop.run_until_complete(swipe_bg_tasks.update_recently_online_cache())

    logger.info(f'Starting app at port {settings.SWIPE_PORT}')
    uvicorn.run('bin.swipe_server:app', host='0.0.0.0',  # noqa
                port=settings.SWIPE_PORT,
                workers=settings.SWIPE_SERVER_WORKER_NUMBER,
                reload=settings.ENABLE_WEB_SERVER_AUTORELOAD)
