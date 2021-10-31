import logging
from uuid import UUID

import dateutil.parser
from fastapi import FastAPI, APIRouter, Depends
from starlette.requests import Request

import config
from swipe.chats.models import MessageStatus
from swipe.chats.services import ChatService

config.configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI()
router = APIRouter()


@router.post('/')
async def consume_message(request: Request,
                          chat_service: ChatService = Depends()):
    # response = {
    #   "timestamp": "2021-10-26T17:43:46+0000",
    #   "sender": "user_id",
    #   "recipient": "user_id",
    #   "payload" : {} # payload
    # }
    json_data = await request.json()
    # TODO timestamps come in UTC
    message_date = json_data['timestamp']
    payload = json_data['payload']

    message_id = UUID(hex=payload['message_id'])
    sender_id = UUID(hex=json_data['sender'])
    payload_type = payload['type']
    logger.info(f"Got payload with type {payload_type} from {sender_id}")

    if payload_type == 'message':
        if 'recipient' in json_data:
            chat_service.post_message(
                message_id=message_id,
                sender_id=sender_id,
                recipient_id=UUID(hex=json_data['recipient']),
                message=payload.get('text'),
                image_id=payload.get('image_id'),
                timestamp=dateutil.parser.isoparse(message_date)
            )
        else:
            chat_service.post_message_to_global(
                message_id=message_id,
                sender_id=sender_id,
                message=payload['text'],
                timestamp=dateutil.parser.isoparse(message_date)
            )
    elif payload_type == 'message_status':
        status = MessageStatus.__members__[payload['status'].upper()]
        if status == MessageStatus.RECEIVED:
            chat_service.set_received_status(message_id)
        elif status == MessageStatus.READ:
            chat_service.set_read_status(message_id)


app.include_router(router)

# uvicorn.run('message_consumer:app', host='0.0.0.0',  # noqa
#             port=16000)
