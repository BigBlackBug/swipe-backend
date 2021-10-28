import json

from fastapi import FastAPI, APIRouter
from starlette.requests import Request

import config

config.configure_logging()

app = FastAPI()
router = APIRouter()


@router.post('/')
async def consume_event(request: Request):
    print("Got an event")
    json_data = await request.json()
    print(json.dumps(json_data, indent=2, sort_keys=True))


app.include_router(router)
