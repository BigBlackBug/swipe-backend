import logging
from uuid import UUID

import dateutil.parser
from fastapi import FastAPI, APIRouter, Depends
from starlette.requests import Request

import config
from swipe.chats.models import MessageStatus, ChatSource, ChatStatus
from swipe.chats.services import ChatService
from swipe.errors import SwipeError

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

    message_id = UUID(hex=payload['message_id']) \
        if 'message_id' in payload else None
    chat_id = UUID(hex=payload['chat_id']) \
        if 'chat_id' in payload else None
    sender_id = UUID(hex=json_data['sender'])

    payload_type = payload['type']
    logger.info(f"Got payload with type '{payload_type}' from {sender_id}, "
                f"payload:{payload}")

    if payload_type == 'message':
        if 'recipient' in json_data:
            recipient_id = UUID(hex=json_data['recipient'])
            chat_service.post_message(
                message_id=message_id,
                sender_id=sender_id,
                recipient_id=recipient_id,
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
    elif payload_type == 'create_chat':
        source = ChatSource.__members__[payload['source'].upper()]
        recipient_id = UUID(hex=json_data['recipient'])

        # video/audio lobby chats start empty
        messages = []
        # audio/video/text lobby chats are created as accepted
        chat_status = ChatStatus.ACCEPTED
        if source == ChatSource.DIRECT:
            # direct chats go to requested
            # direct chats start with one message
            chat_status = ChatStatus.REQUESTED
            if 'message' not in payload:
                raise SwipeError(
                    "Direct chat payload must include 'message' field")
            messages = [payload['message']]
        elif source == ChatSource.TEXT_LOBBY:
            # text lobby chats start with a shitload of messages
            if 'messages' not in payload:
                raise SwipeError(
                    "Text lobby chat payload must include 'messages' field")
            messages = payload['messages']

        # if a second user tries to accept a text lobby chat
        # before he receives an event, the method will raise SwipeError
        chat_service.create_chat(chat_id=chat_id,
                                 initiator_id=sender_id,
                                 the_other_person_id=recipient_id,
                                 chat_status=chat_status,
                                 source=source)

        for message in messages:
            message_id = UUID(hex=message['message_id'])
            recipient_id = UUID(hex=message['recipient'])
            sender_id = UUID(hex=message['sender'])
            timestamp = dateutil.parser.isoparse(message['timestamp'])
            chat_service.post_message(
                message_id=message_id,
                sender_id=sender_id,
                recipient_id=recipient_id,
                message=message.get('text'),
                image_id=message.get('image_id'),
                timestamp=timestamp
            )

    elif payload_type == 'accept_chat':
        chat_service.accept_chat(chat_id=chat_id)


# TODO add exception handler
app.include_router(router)
