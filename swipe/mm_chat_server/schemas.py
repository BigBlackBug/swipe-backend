from __future__ import annotations

import datetime
from enum import Enum
from typing import Union, Type, Any, Optional

import dateutil.parser
from pydantic import BaseModel, Field, validator


class MMTextChatAction(str, Enum):
    OFFER = 'offer'
    ACCEPT = 'accept'


class MMTextChatPayload(BaseModel):
    type_: str = Field('chat', alias='type', const=True)
    action: MMTextChatAction


class MMTextMessagePayload(BaseModel):
    type_: str = Field('message', alias='type', const=True)
    message_id: str
    sender_id: str
    recipient_id: str
    timestamp: str
    text: str

    is_liked: Optional[bool] = None

    @validator('timestamp', pre=True)
    def validate_timestamp(cls, value):
        dateutil.parser.parse(value)
        return value


class MMTextMessageLikePayload(BaseModel):
    type_: str = Field('like', alias='type', const=True)
    message_id: str
    like: bool


class MMTextBasePayload(BaseModel):
    sender_id: str
    recipient_id: str
    payload: Union[
        MMTextMessagePayload, MMTextMessageLikePayload, MMTextChatPayload,
    ]

    @classmethod
    def payload_type(cls, payload_type: str) -> Type[BaseModel]:
        if payload_type == 'message':
            return MMTextMessagePayload
        elif payload_type == 'like':
            return MMTextMessageLikePayload
        elif payload_type == 'chat':
            return MMTextChatPayload

    @classmethod
    def validate(cls: MMTextBasePayload, value: Any) -> MMTextBasePayload:
        result: MMTextBasePayload = super().validate(value)  # noqa
        payload_type = cls.payload_type(value['payload']['type'])
        result.payload = payload_type.parse_obj(value['payload'])
        return result
