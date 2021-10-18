import logging
import sys
from pathlib import Path

import alembic.command
import alembic.config
import uvicorn
from fastapi import FastAPI
from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse

import swipe
from settings import settings
from swipe import users
from swipe.storage import CloudStorage


def init_app() -> FastAPI:
    app = FastAPI(docs_url=f'/docs', redoc_url=f'/redoc')
    app.include_router(swipe.endpoints.router)
    app.include_router(users.endpoints.me_router)
    app.include_router(users.endpoints.users_router)
    return app


fast_api = init_app()


# TODO introduce a validation error
@fast_api.exception_handler(ValueError)
async def validation_exception_handler(
        request: Request, exc: ValueError):
    return JSONResponse({
        'detail': str(exc)
    }, status_code=status.HTTP_400_BAD_REQUEST)


# TODO add operation logging
# TODO proper logging configuration
# TODO add current user to context
logging.basicConfig(stream=sys.stderr,
                    format="[%(asctime)s %(levelname)s|%(processName)s] "
                           "%(name)s %(message)s",
                    level=logging.DEBUG)

logger = logging.getLogger(__name__)

if __name__ == '__main__':
    CloudStorage().initialize_storage()

    migrations_dir = str(Path('migrations').absolute())
    logger.info(
        f'Running DB migrations in {migrations_dir} '
        f'on {settings.DATABASE_URL}')
    alembic_cfg = alembic.config.Config('alembic.ini')
    alembic_cfg.set_main_option('script_location', migrations_dir)
    alembic_cfg.set_main_option('sqlalchemy.url', settings.DATABASE_URL)
    alembic.command.upgrade(alembic_cfg, 'head')

    logger.info(f'Starting app at port {settings.PORT}')
    uvicorn.run('main:fast_api', host='0.0.0.0',  # noqa
                port=settings.PORT,
                # workers=1,
                reload=settings.ENABLE_WEB_SERVER_AUTORELOAD)
