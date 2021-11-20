from __future__ import annotations

from enum import Enum
from typing import Union, Type, Tuple, Any, Optional

from pydantic import BaseModel, Field

from swipe.swipe_server.users.enums import Gender

Match = Tuple[str, str]


class MMSDPPayload(BaseModel):
    type_: str = Field('sdp', alias='type', const=True)
    sdp: dict[str, Any]


class MMICEPayload(BaseModel):
    type_: str = Field('ice', alias='type', const=True)
    ice: dict[str, Any]


class MMResponseAction(str, Enum):
    ACCEPT = 'accept'
    DECLINE = 'decline'


class MMMatchPayload(BaseModel):
    type_: str = Field('match', alias='type', const=True)
    action: MMResponseAction


class MMLobbyAction(str, Enum):
    CONNECT = 'connect'
    DISCONNECT = 'disconnect'


class MMLobbyPayload(BaseModel):
    type_: str = Field('lobby', alias='type', const=True)
    action: MMLobbyAction


class MMBasePayload(BaseModel):
    sender_id: str
    recipient_id: Optional[str] = None
    payload: Union[
        MMLobbyPayload, MMSDPPayload, MMMatchPayload, MMICEPayload
    ]

    @classmethod
    def payload_type(cls, payload_type: str) -> Type[BaseModel]:
        if payload_type == 'sdp':
            return MMSDPPayload
        elif payload_type == 'ice':
            return MMICEPayload
        elif payload_type == 'match':
            return MMMatchPayload
        elif payload_type == 'lobby':
            return MMLobbyPayload

    @classmethod
    def validate(cls: MMBasePayload, value: Any) -> MMBasePayload:
        result: MMBasePayload = super().validate(value)  # noqa
        payload_type = cls.payload_type(value['payload']['type'])
        result.payload = payload_type.parse_obj(value['payload'])
        return result


class MMSettings(BaseModel):
    age: int
    # TODO change in prod obviously
    age_diff: int = 20
    max_age_diff: int = 20
    current_weight: int = 0
    gender: Optional[Gender] = None

    def increase_age_diff(self):
        self.age_diff = min(self.age_diff + 1, self.max_age_diff)

    def reset_weight(self):
        self.current_weight = 0

    def increase_weight(self):
        self.current_weight += 1
