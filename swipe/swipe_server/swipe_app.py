import logging

from fastapi import FastAPI

from swipe import error_handlers
from swipe.middlewares import AccessMiddleware, CorrelationIdMiddleware
from swipe.settings import settings
from swipe.swipe_server import endpoints as misc_endpoints
from swipe.swipe_server.chats.endpoints import router as chat_router
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.users.endpoints import users, me, swipes

logger = logging.getLogger(__name__)


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
    app.include_router(chat_router,
                       prefix=f'{settings.API_V1_PREFIX}/me/chats',
                       tags=['my chats'])
    app.add_exception_handler(SwipeError, error_handlers.swipe_error_handler)
    app.add_exception_handler(Exception, error_handlers.global_error_handler)
    app.add_middleware(AccessMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    return app
