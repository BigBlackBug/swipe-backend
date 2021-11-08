import json

from fastapi import FastAPI, APIRouter
from starlette.requests import Request

import config

config.configure_logging()

app = FastAPI()
router = APIRouter()


@router.post('/')
async def consume_event(request: Request):
    # TODO handle join/leave events and update lobby/online cache accordingly
    # remove the user from the online cache
    # there should be a leave event, but it doesn't work
    # [
    #   {
    #     "emitter": "MyJanusInstance",
    #     "event": {
    #       "name": "destroyed"
    #     },
    #     "session_id": 5041779847538953,
    #     "timestamp": 1635601135069082,
    #     "type": 1
    #   }
    # ]
    print("Got an event")
    json_data = await request.json()
    print(json.dumps(json_data, indent=2, sort_keys=True))


app.include_router(router)
