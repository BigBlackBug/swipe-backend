import logging
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError

from swipe import database, routes

logging.basicConfig(stream=sys.stderr,
                    format="[%(asctime)s %(levelname)s|%(processName)s] "
                           "%(name)s %(message)s",
                    level=logging.DEBUG)

logger = logging.getLogger(__name__)
app = FastAPI(docs_url="/docs", redoc_url='/redoc')


app.include_router(routes.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logger.exception(f"OMG! The client sent invalid data!: {exc}")
    return await request_validation_exception_handler(request, exc)


if __name__ == '__main__':
    logger.info('Creating tables')
    database.Base.metadata.create_all(bind=database.engine)
    logger.info('Starting app')
    uvicorn.run('main:app', port=8000, reload=True)
