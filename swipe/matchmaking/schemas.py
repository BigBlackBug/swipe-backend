from __future__ import annotations

from enum import Enum
from typing import Union, Type, Tuple, Any

from pydantic import BaseModel, Field

Match = Tuple[str, str]


class MMSDPPayload(BaseModel):
    type_: str = Field('sdp', alias='type', const=True)
    sdp: str


class MMResponseAction(str, Enum):
    ACCEPT = 'accept'
    DECLINE = 'decline'


class MMMatchPayload(BaseModel):
    type_: str = Field('match', alias='type', const=True)
    action: MMResponseAction


class MMBasePayload(BaseModel):
    sender_id: str
    recipient_id: str
    payload: Union[
        MMSDPPayload, MMMatchPayload
    ]

    @classmethod
    def payload_type(cls, payload_type: str) -> Type[BaseModel]:
        if payload_type == 'sdp':
            return MMSDPPayload
        elif payload_type == 'match':
            return MMMatchPayload

    @classmethod
    def validate(cls: MMBasePayload, value: Any) -> MMBasePayload:
        result: MMBasePayload = super().validate(value)  # noqa
        payload_type = cls.payload_type(value['payload']['type'])
        result.payload = payload_type.parse_obj(value['payload'])
        return result
