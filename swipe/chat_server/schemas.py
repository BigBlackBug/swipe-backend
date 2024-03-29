from __future__ import annotations

import datetime
import enum
from typing import Optional, Union, Any, Type
from uuid import UUID

from pydantic import BaseModel, Field

from swipe.swipe_server.chats.models import MessageStatus, ChatSource


class ChatMessagePayload(BaseModel):
    message_id: UUID
    sender_id: UUID
    recipient_id: UUID
    timestamp: datetime.datetime
    is_liked: Optional[bool] = False

    text: Optional[str] = None
    image_id: Optional[str] = None
    image_url: Optional[str] = None


class MessagePayload(BaseModel):
    type_: str = Field('message', alias='type', const=True)
    message_id: UUID
    timestamp: datetime.datetime
    text: Optional[str] = None
    image_id: Optional[str] = None
    image_url: Optional[str] = None


class GlobalMessagePayload(BaseModel):
    type_: str = Field('global_message', alias='type', const=True)
    timestamp: datetime.datetime
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


class UserJoinEventPayload(BaseModel):
    type_: str = Field('join', alias='type', const=True)
    user_id: str
    name: str
    avatar_url: str


class RatingChangedEventPayload(BaseModel):
    type_: str = Field('rating_changed', alias='type', const=True)
    user_id: str
    rating: int


class UserEventType(str, enum.Enum):
    USER_LEFT = 'leave'
    USER_BLACKLISTED = 'blacklisted'
    USER_DELETED = 'user_deleted'


class GenericEventPayload(BaseModel):
    type_: UserEventType = Field(..., alias='type')


class AckType(str, enum.Enum):
    ACK = 'ack'
    ACK_FAILED = 'ack_failed'


class AckPayload(BaseModel):
    type_: AckType = Field(..., alias='type')
    timestamp: datetime.datetime
    request_id: UUID


class OutPayload(BaseModel):
    payload: AckPayload


class BasePayload(BaseModel):
    sender_id: Optional[UUID] = None
    recipient_id: Optional[UUID] = None
    timestamp: Optional[datetime.datetime] = None
    request_id: Optional[UUID] = None

    payload: Union[
        MessagePayload, GlobalMessagePayload,
        MessageStatusPayload, MessageLikePayload,
        DeclineChatPayload, AcceptChatPayload, CreateChatPayload,
        OpenChatPayload,

        UserJoinEventPayload, GenericEventPayload, RatingChangedEventPayload
    ]

    @classmethod
    def payload_type(cls, payload_type: str) -> Type[BaseModel]:
        if payload_type == 'message_status':
            return MessageStatusPayload
        elif payload_type == 'message':
            return MessagePayload
        elif payload_type == 'global_message':
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
        payload_type = cls.payload_type(value['payload']['type'])
        result.payload = payload_type.parse_obj(value['payload'])
        return result
