import os
import sys

# TODO WTF
sys.path.insert(1, os.path.join(sys.path[0], '..'))
import logging

import uvicorn

from swipe import config

config.configure_logging()
from swipe.settings import settings
from swipe.swipe_server import swipe_app

logger = logging.getLogger(__name__)

app = swipe_app.init_app()

if __name__ == '__main__':
    # TODO path issues, doesn't work
    # root_dir = Path('.').absolute()
    # migrations_dir = str(root_dir.joinpath('migrations').absolute())
    # logger.info(
    #     f'Running DB migrations in {migrations_dir} '
    #     f'on {settings.DATABASE_URL}')
    # alembic_cfg = alembic.config.Config(
    #     str(root_dir.joinpath('alembic.ini').absolute()))
    # alembic_cfg.set_main_option('script_location', migrations_dir)
    # alembic.command.upgrade(alembic_cfg, 'head')

    logger.info(f'Starting app at port {settings.SWIPE_PORT}')
    uvicorn.run('swipe_server:app', host='0.0.0.0',  # noqa
                port=settings.SWIPE_PORT,
                # workers=1,
                reload=settings.ENABLE_WEB_SERVER_AUTORELOAD)
