import logging
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError

import swipe
from settings import settings
from swipe import users

# TODO proper logging configuration
logging.basicConfig(stream=sys.stderr,
                    format="[%(asctime)s %(levelname)s|%(processName)s] "
                           "%(name)s %(message)s",
                    level=logging.DEBUG)

logger = logging.getLogger(__name__)
app = FastAPI(docs_url=f'/docs', redoc_url=f'/redoc')

app.include_router(users.routes.router)
app.include_router(swipe.routes.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logger.exception(f"OMG! The client sent invalid data!: {exc}")
    return await request_validation_exception_handler(request, exc)


if __name__ == '__main__':
    logger.info(f'Starting app at port {settings.PORT}')
    uvicorn.run('main:app', host='0.0.0.0',
                port=settings.PORT,
                reload=settings.ENABLE_WEB_SERVER_AUTORELOAD)
