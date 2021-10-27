import json

from fastapi import FastAPI, APIRouter
from starlette.requests import Request

app = FastAPI()

router = APIRouter()


@router.post('/')
async def consume_event(request: Request):
    print("Got an event")
    # json_data = await request.json()
    # print(json.dumps(json_data, indent=2, sort_keys=True))


@router.post('/messages')
async def consume_message(request: Request):
    print("Got message")
    # response = {
    #     "date": "2021-10-26T17:43:46+0000",
    #     "from": "SufsmuAMwJrR",
    #     "room": 1234,
    #     "text": "BUT",
    #     "textroom": "message"
    # }
    json_data = await request.json()
    print(json.dumps(json_data, indent=2, sort_keys=True))


app.include_router(router)
