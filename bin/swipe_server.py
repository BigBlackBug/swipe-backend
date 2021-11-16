import os
import sys

# TODO WTF
sys.path.insert(1, os.path.join(sys.path[0], '..'))
from swipe import config

config.configure_logging()
import logging
from pathlib import Path

import alembic.command
import alembic.config
import uvicorn

from swipe.settings import settings, constants
from swipe.swipe_server import swipe_app

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


if __name__ == '__main__':
    run_migrations()
    logger.info(f'Starting app at port {settings.SWIPE_PORT}')
    uvicorn.run('bin.swipe_server:app', host='0.0.0.0',  # noqa
                port=settings.SWIPE_PORT, workers=1,
                reload=settings.ENABLE_WEB_SERVER_AUTORELOAD)
