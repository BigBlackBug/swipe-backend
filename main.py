import logging
import sys
from pathlib import Path
from uuid import UUID

import alembic.command
import alembic.config
import uvicorn
from fastapi import FastAPI
from fastapi_utils import tasks
from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse

import config
import swipe
import swipe.dependencies
from settings import settings, constants
from swipe import endpoints as misc_endpoints, chats, janus_client
from swipe.errors import SwipeError
from swipe.users.endpoints import me, users, swipes
from swipe.users.services import RedisUserService


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
logger_janus = logging.getLogger('janus_client')


@tasks.repeat_every(seconds=constants.ONLINE_USER_COOLDOWN_SEC - 5,
                    logger=logger_janus)
async def populate_online_users_cache():
    redis_service = RedisUserService(await swipe.dependencies.redis())

    for participant in janus_client.fetch_online_users(
            settings.JANUS_GATEWAY_GLOBAL_ROOM_ID, logger_janus):
        await redis_service.refresh_online_status(
            UUID(hex=participant['username']))


@tasks.repeat_every(seconds=constants.ONLINE_USER_COOLDOWN_SEC - 5,
                    logger=logger_janus)
async def populate_lobby_users_cache():
    redis_service = RedisUserService(await swipe.dependencies.redis())

    for participant in janus_client.fetch_online_users(
            settings.JANUS_GATEWAY_LOBBY_ROOM_ID, logger_janus):
        await redis_service.refresh_online_lobby_status(
            UUID(hex=participant['username']))


if settings.ENABLE_ONLINE_CACHE_JOB:
    populate_online_users_cache = \
        fast_api.on_event("startup")(populate_online_users_cache)

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
