from __future__ import annotations

import datetime
from typing import Optional, Union, Any, Type
from uuid import UUID

from pydantic import BaseModel, Field

from swipe.chats.models import MessageStatus, ChatSource


class ChatMessagePayload(BaseModel):
    message_id: UUID
    sender: UUID
    recipient: UUID
    timestamp: datetime.datetime
    text: Optional[str]
    image_id: Optional[UUID]


class MessagePayload(BaseModel):
    type_: str = Field('message', alias='type', const=True)
    message_id: UUID
    text: Optional[str]
    image_id: Optional[UUID]


class GlobalMessagePayload(BaseModel):
    type_: str = Field('message', alias='type', const=True)
    message_id: UUID
    text: str


class MessageStatusPayload(BaseModel):
    type_: str = Field('message_status', alias='type', const=True)
    message_id: UUID
    status: MessageStatus


class MessageLikePayload(BaseModel):
    type_: str = Field('like', alias='type', const=True)
    message_id: UUID
    like: bool


class CreateChatPayload(BaseModel):
    type_: str = Field('create_chat', alias='type', const=True)
    source: ChatSource
    chat_id: UUID
    message: Optional[ChatMessagePayload] = None
    messages: Optional[list[ChatMessagePayload]] = []


class AcceptChatPayload(BaseModel):
    type_: str = Field('accept_chat', alias='type', const=True)
    chat_id: UUID


class DeclineChatPayload(BaseModel):
    type_: str = Field('decline_chat', alias='type', const=True)
    chat_id: UUID


class OpenChatPayload(BaseModel):
    type_: str = Field('open_chat', alias='type', const=True)
    chat_id: UUID


class BasePayload(BaseModel):
    # room_id
    room: str
    # always equal to 'message'
    textroom: str
    timestamp: datetime.datetime
    sender: UUID
    recipient: Optional[UUID] = None
    payload: Union[
        MessagePayload, MessageStatusPayload, MessageLikePayload,
        DeclineChatPayload, AcceptChatPayload, CreateChatPayload,
        OpenChatPayload
    ]

    @classmethod
    def payload_type(cls, payload_type: str, json_data: dict) \
            -> Type[BaseModel]:
        if payload_type == 'message_status':
            return MessageStatusPayload
        elif payload_type == 'message':
            if json_data.get('recipient'):
                return MessagePayload
            else:
                return GlobalMessagePayload
        elif payload_type == 'like':
            return MessageLikePayload
        elif payload_type == 'create_chat':
            return CreateChatPayload
        elif payload_type == 'accept_chat':
            return AcceptChatPayload
        elif payload_type == 'decline_chat':
            return DeclineChatPayload
        elif payload_type == 'open_chat':
            return OpenChatPayload

    @classmethod
    def validate(cls: BasePayload, value: Any) -> BasePayload:
        result: BasePayload = super().validate(value)  # noqa
        payload_type = cls.payload_type(value['payload']['type'], value)
        result.payload = payload_type.parse_obj(value['payload'])
        return result
