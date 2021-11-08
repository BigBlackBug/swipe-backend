from __future__ import annotations

import datetime
import logging
import sys
from typing import Optional, Union, Any, Type
from urllib.request import Request
from uuid import UUID

import uvicorn
from fastapi import FastAPI, APIRouter, Depends, Body
from pydantic import BaseModel, Field
from starlette import status
from starlette.responses import JSONResponse

import config
from settings import settings
from swipe.chats.models import MessageStatus, ChatSource, ChatStatus
from swipe.chats.services import ChatService
from swipe.errors import SwipeError

config.configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(docs_url=f'/docs')
router = APIRouter()


class MessagePayload(BaseModel):
    type_: str = Field('message', alias='type')
    message_id: UUID
    text: Optional[str]
    image_id: Optional[UUID]


class MessageStatusPayload(BaseModel):
    type_: str = Field('message_status', alias='type')
    message_id: UUID
    status: MessageStatus


class MessageLikePayload(BaseModel):
    type_: str = Field('like', alias='type')
    message_id: UUID
    like: bool


class ChatMessagePayload(BaseModel):
    message_id: UUID
    sender: UUID
    recipient: UUID
    timestamp: datetime.datetime
    text: Optional[str]
    image_id: Optional[UUID]


class CreateChatPayload(BaseModel):
    type_: str = Field('create_chat', alias='type')
    source: ChatSource
    chat_id: UUID
    message: Optional[ChatMessagePayload] = None
    messages: Optional[list[ChatMessagePayload]] = []


class AcceptChatPayload(BaseModel):
    type_: str = Field('accept_chat', alias='type')
    chat_id: UUID


class DeclineChatPayload(BaseModel):
    type_: str = Field('delete_chat', alias='type')
    chat_id: UUID


class BasePayload(BaseModel):
    # room_id
    room: str
    # always equal to 'message'
    textroom: str
    timestamp: datetime.datetime
    sender: UUID
    recipient: Optional[UUID] = None
    payload: Union[MessagePayload, MessageStatusPayload, MessageLikePayload,
                   DeclineChatPayload, AcceptChatPayload, CreateChatPayload]

    @classmethod
    def payload_type(cls, payload_type: str) -> Type[BaseModel]:
        if payload_type == 'message_status':
            return MessageStatusPayload
        elif payload_type == 'message':
            return MessagePayload
        elif payload_type == 'like':
            return MessageLikePayload
        elif payload_type == 'create_chat':
            return CreateChatPayload
        elif payload_type == 'accept_chat':
            return AcceptChatPayload
        elif payload_type == 'decline_chat':
            return DeclineChatPayload

    @classmethod
    def validate(cls: BasePayload, value: Any) -> BasePayload:
        result: BasePayload = super().validate(value)  # noqa
        payload_type = cls.payload_type(value['payload']['type'])
        result.payload = payload_type.parse_obj(value['payload'])
        return result


@router.post('/global', description='')
async def consume_message(
        json_data: BasePayload = Body(...),
        chat_service: ChatService = Depends()):
    payload = json_data.payload
    logger.info(f"Got payload with type '{payload.type_}' "
                f"from {json_data.sender}, payload:{payload}")

    if isinstance(payload, MessagePayload):
        if json_data.recipient:
            chat_service.post_message(
                message_id=payload.message_id,
                sender_id=json_data.sender,
                recipient_id=json_data.recipient,
                message=payload.text,
                image_id=payload.image_id,
                timestamp=json_data.timestamp
            )
        else:
            chat_service.post_message_to_global(
                message_id=payload.message_id,
                sender_id=json_data.sender,
                message=payload.text,
                timestamp=json_data.timestamp
            )
    elif isinstance(payload, MessageStatusPayload):
        status = MessageStatus.__members__[payload.status.upper()]
        if status == MessageStatus.RECEIVED:
            chat_service.set_received_status(payload.message_id)
        elif status == MessageStatus.READ:
            chat_service.set_read_status(payload.message_id)
    elif isinstance(payload, MessageLikePayload):
        chat_service.set_like_status(payload.message_id, payload.like)
    elif isinstance(payload, CreateChatPayload):
        source = ChatSource.__members__[payload.source.upper()]
        # video/audio lobby chats start empty
        messages = []
        # audio/video/text lobby chats are created as accepted
        chat_status = ChatStatus.ACCEPTED
        if source == ChatSource.DIRECT:
            # direct chats go to requested
            # direct chats start with one message
            chat_status = ChatStatus.REQUESTED
            if not payload.message:
                raise SwipeError(
                    "Direct chat payload must include 'message' field")
            messages = [payload.message]
        elif source == ChatSource.TEXT_LOBBY:
            # text lobby chats start with a shitload of messages
            if not payload.messages:
                raise SwipeError(
                    "Text lobby chat payload must include 'messages' field")
            messages = payload.messages

        # if a second user tries to accept a text lobby chat
        # before he receives an event, the method will raise SwipeError
        chat_service.create_chat(chat_id=payload.chat_id,
                                 initiator_id=json_data.sender,
                                 the_other_person_id=json_data.recipient,
                                 chat_status=chat_status,
                                 source=source)
        message: ChatMessagePayload
        for message in messages:
            chat_service.post_message(
                message_id=message.message_id,
                sender_id=message.sender,
                recipient_id=message.recipient,
                message=message.text,
                image_id=message.image_id,
                timestamp=message.timestamp
            )

    elif isinstance(payload, AcceptChatPayload):
        chat_service.accept_chat(chat_id=payload.chat_id)
    elif isinstance(payload, DeclineChatPayload):
        chat_service.delete_chat(chat_id=payload.chat_id)


async def global_error_handler(request: Request, exc: Exception):
    logger.exception("Something wrong", exc_info=sys.exc_info())
    return JSONResponse({
        'detail': str(exc)
    }, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


app.include_router(router)
app.add_exception_handler(Exception, global_error_handler)

if __name__ == '__main__':
    uvicorn.run('message_consumer:app', host='0.0.0.0',  # noqa
                port=16001,
                # workers=1,
                reload=settings.ENABLE_WEB_SERVER_AUTORELOAD)
