import logging
import sys

from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse

from swipe.swipe_server.misc.errors import SwipeError

logger = logging.getLogger(__name__)


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
