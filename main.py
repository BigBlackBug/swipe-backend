import logging
import sys

import uvicorn
from fastapi import FastAPI

from settings import settings
from swipe import users

# TODO proper logging configuration
logging.basicConfig(stream=sys.stderr,
                    format="[%(asctime)s %(levelname)s|%(processName)s] "
                           "%(name)s %(message)s",
                    level=logging.DEBUG)

logger = logging.getLogger(__name__)
app = FastAPI(docs_url=f'/docs', redoc_url=f'/redoc')

app.include_router(users.endpoints.me_router)
app.include_router(users.endpoints.users_router)

if __name__ == '__main__':
    logger.info(f'Starting app at port {settings.PORT}')
    uvicorn.run('main:app', host='0.0.0.0',
                port=settings.PORT,
                reload=settings.ENABLE_WEB_SERVER_AUTORELOAD)
