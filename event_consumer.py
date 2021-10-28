import json
import logging
import sys

from fastapi import FastAPI, APIRouter
from starlette.requests import Request

logging.basicConfig(stream=sys.stderr,
                    format="[%(asctime)s %(levelname)s|%(processName)s] "
                           "%(name)s %(message)s",
                    level=logging.DEBUG)
app = FastAPI()

router = APIRouter()


@router.post('/')
async def consume_event(request: Request):
    print("Got an event")
    json_data = await request.json()
    print(json.dumps(json_data, indent=2, sort_keys=True))


app.include_router(router)

# uvicorn.run('event_consumer:app', host='0.0.0.0',  # noqa
#             port=15000)
