import json
import logging
import sys
from uuid import UUID

import dateutil.parser
from fastapi import FastAPI, APIRouter, Depends
from starlette.requests import Request

from swipe.chats.models import MessageStatus
from swipe.chats.services import ChatService

logging.basicConfig(stream=sys.stderr,
                    format="[%(asctime)s %(levelname)s|%(processName)s] "
                           "%(name)s %(message)s",
                    level=logging.INFO)
app = FastAPI()

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post('/')
async def consume_message(request: Request,
                          chat_service: ChatService = Depends()):
    # response = {
    #     "date": "2021-10-26T17:43:46+0000",
    #     "from": "user_id",
    #     "room": 1234,
    #     "text": "BUT",
    #     "recipient": "user_id",
    #     "textroom": "message"
    # }
    json_data = await request.json()
    # TODO timestamps come in UTC
    if 'recipient' in json_data:
        payload_type = json_data['payload']['type']
        logger.info(f"Got payload with type {payload_type}")
        if payload_type == 'message':
            chat_service.post_message(
                message_id=UUID(hex=json_data['payload']['message_id']),
                sender_id=UUID(hex=json_data['from']),
                recipient_id=UUID(hex=json_data['recipient']),
                message=json_data['payload']['text'],
                timestamp=dateutil.parser.isoparse(json_data['date'])
            )
        elif payload_type == 'event':
            message_id = json_data['payload']['message_id']
            status = json_data['payload']['status']
            chat_service.update_message_status(
                message_id=UUID(hex=message_id),
                status=MessageStatus.__members__[status.upper()]
            )
    else:
        logger.info("Global chat is not supported atm")
    print(json.dumps(json_data, indent=2, sort_keys=True))


app.include_router(router)

# uvicorn.run('message_consumer:app', host='0.0.0.0',  # noqa
#             port=16000)
