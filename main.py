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

import config
from settings import settings
from swipe import endpoints as misc_endpoints, chats
from swipe.errors import SwipeError
from swipe.users.endpoints import me, users, swipes


async def swipe_error_handler(request: Request, exc: SwipeError):
    logger.exception("Something wrong", exc_info=sys.exc_info())
    return JSONResponse({
        'detail': str(exc)
    }, status_code=status.HTTP_409_CONFLICT)


async def global_error_handler(request: Request, exc: Exception):
    logger.exception("Something wrong", exc_info=sys.exc_info())
    return JSONResponse({
        'detail': str(exc)
    }, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


def init_app() -> FastAPI:
    app = FastAPI(docs_url=f'/docs', redoc_url=f'/redoc')
    app.include_router(misc_endpoints.router,
                       prefix=f'{settings.API_V1_PREFIX}')
    app.include_router(users.router,
                       prefix=f'{settings.API_V1_PREFIX}/users',
                       tags=["users"])
    app.include_router(me.router,
                       prefix=f'{settings.API_V1_PREFIX}/me',
                       tags=["me"])
    app.include_router(swipes.router,
                       prefix=f'{settings.API_V1_PREFIX}/me/swipes',
                       tags=['my swipes'])
    app.include_router(chats.router,
                       prefix=f'{settings.API_V1_PREFIX}/me/chats',
                       tags=['my chats'])
    app.add_exception_handler(SwipeError, swipe_error_handler)
    app.add_exception_handler(Exception, global_error_handler)
    return app


fast_api = init_app()

config.configure_logging()
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    migrations_dir = str(Path('migrations').absolute())
    logger.info(
        f'Running DB migrations in {migrations_dir} '
        f'on {settings.DATABASE_URL}')
    alembic_cfg = alembic.config.Config('alembic.ini')
    alembic_cfg.set_main_option('script_location', migrations_dir)
    alembic.command.upgrade(alembic_cfg, 'head')

    logger.info(f'Starting app at port {settings.SWIPE_PORT}')
    uvicorn.run('main:fast_api', host='0.0.0.0',  # noqa
                port=settings.SWIPE_PORT,
                # workers=1,
                reload=settings.ENABLE_WEB_SERVER_AUTORELOAD)
