import logging
import sys
from pathlib import Path

import alembic.command
import alembic.config
import uvicorn
from fastapi import FastAPI

import swipe
from settings import settings
from swipe import users
# TODO proper logging configuration
from swipe.storage import CloudStorage


def init_app() -> FastAPI:
    app = FastAPI(docs_url=f'/docs', redoc_url=f'/redoc')
    app.include_router(swipe.endpoints.router)
    app.include_router(users.endpoints.me_router)
    app.include_router(users.endpoints.users_router)
    return app


fast_api = init_app()
if __name__ == '__main__':
    logging.basicConfig(stream=sys.stderr,
                        format="[%(asctime)s %(levelname)s|%(processName)s] "
                               "%(name)s %(message)s",
                        level=logging.DEBUG)

    logger = logging.getLogger(__name__)
    migrations_dir = str(Path('migrations').absolute())
    logger.info(
        f'Running DB migrations in {migrations_dir} '
        f'on {settings.DATABASE_URL}')
    alembic_cfg = alembic.config.Config('alembic.ini')
    alembic_cfg.set_main_option('script_location', migrations_dir)
    alembic_cfg.set_main_option('sqlalchemy.url', settings.DATABASE_URL)
    alembic.command.upgrade(alembic_cfg, 'head')

    CloudStorage().initialize_storage()
    logger.info(f'Starting app at port {settings.PORT}')

    uvicorn.run('main:fast_api', host='0.0.0.0',
                port=settings.PORT,
                reload=settings.ENABLE_WEB_SERVER_AUTORELOAD)
