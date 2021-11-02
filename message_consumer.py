import logging
from uuid import UUID

import dateutil.parser
from fastapi import FastAPI, APIRouter, Depends
from starlette.requests import Request

import config
from swipe.chats.models import MessageStatus
from swipe.chats.services import ChatService, RedisChatService

config.configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI()
router = APIRouter()


@router.post('/global')
async def consume_message(request: Request,
                          chat_service: ChatService = Depends()):
    #  {
    #   "room": ''
    #   "textroom": 'message'
    #   "timestamp": "2021-10-26T17:43:46+0000",
    #   "sender": "user_id",
    #   "recipient": "user_id" #optional
    #   "payload" : {} # payload
    # }
    json_data = await request.json()
    timestamp = dateutil.parser.isoparse(json_data['timestamp'])
    payload = json_data['payload']

    message_id = UUID(hex=payload['message_id'])
    sender_id = UUID(hex=json_data['sender'])
    payload_type = payload['type']
    logger.info(f"Got payload with type '{payload_type}' from {sender_id}, "
                f"payload:{payload}")

    if payload_type == 'message':
        if 'recipient' in json_data:
            chat_service.post_message(
                message_id=message_id,
                sender_id=sender_id,
                recipient_id=UUID(hex=json_data['recipient']),
                message=payload.get('text'),
                image_id=payload.get('image_id'),
                timestamp=timestamp
            )
        else:
            chat_service.post_message_to_global(
                message_id=message_id,
                sender_id=sender_id,
                message=payload['text'],
                timestamp=timestamp
            )
    elif payload_type == 'message_status':
        status = MessageStatus.__members__[payload['status'].upper()]
        if status == MessageStatus.RECEIVED:
            chat_service.set_received_status(message_id)
        elif status == MessageStatus.READ:
            chat_service.set_read_status(message_id)
    elif payload_type == 'like':
        chat_service.set_like_status(message_id, payload['status'])


@router.post('/lobby')
async def consume_lobby_message(request: Request,
                                chat_service: ChatService = Depends(),
                                redis_service: RedisChatService = Depends()):
    # response = {
    #   "timestamp": "2021-10-26T17:43:46+0000",
    #   "sender": "user_id",
    #   "recipient": "user_id",
    #   "payload" : {} # payload
    # }
    json_data = await request.json()
    # TODO timestamps come in UTC
    payload = json_data['payload']

    sender_id = json_data['sender']
    recipient_id = json_data['recipient']
    payload_type = payload['type']
    logger.info(f"Got payload with type '{payload_type}' from {sender_id}, "
                f"payload: {payload}")

    if payload_type == 'message':
        logger.info(f"[{sender_id}->{recipient_id}]. Got message: {payload}")
        await redis_service.save_message(
            sender_id, recipient_id,
            timestamp=dateutil.parser.isoparse(json_data['timestamp']),
            payload=payload)
    elif payload_type == 'skip':
        logger.info(f"[{sender_id}->{recipient_id}]. Deleting chat")
        await redis_service.drop_chat(sender_id, recipient_id)
    elif payload_type == 'accept_chat':
        logger.info(f"[{sender_id}->{recipient_id}]. Saving chat to DB")
        partners = {sender_id: recipient_id, recipient_id: sender_id}
        # saving this chat to DB
        messages: dict[str, dict] = \
            await redis_service.fetch_chat(sender_id, recipient_id)
        for message_id, message in messages:
            chat_id: UUID = chat_service.post_message(
                message_id=message_id,
                sender_id=message['sender_id'],
                recipient_id=partners[message['sender_id']],
                timestamp=dateutil.parser.isoparse(message['timestamp']),
                message=message.get('message'),
                image_id=message.get('image_id'),
                status=MessageStatus.__members__[message['status'].upper()],
                is_liked=message['is_liked']
            )
            chat_service.accept_chat(chat_id)
    elif payload_type == 'message_status':
        status = MessageStatus.__members__[payload['status'].upper()]
        if status == MessageStatus.READ:
            await redis_service.set_read_status(sender_id, recipient_id)
        else:
            logger.warning(
                f"[{sender_id}->{recipient_id}]. "
                f"Only READ status updates are supported in lobby chats")
    elif payload_type == 'like':
        message_id = payload['message_id']
        await redis_service.set_like_status(
            sender_id, recipient_id, message_id, payload['status'])


app.include_router(router)
