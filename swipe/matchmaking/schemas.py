from __future__ import annotations

from enum import Enum
from typing import Union, Type, Tuple, Any, Optional

from pydantic import BaseModel, Field

from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import IDList

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
    RECONNECT = 'reconnect'


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
    gender: Gender
    gender_filter: Optional[Gender] = None

    def increase_age_diff(self):
        self.age_diff = min(self.age_diff + 2, self.max_age_diff)

    def reset_weight(self):
        self.current_weight = 0

    def increase_weight(self):
        self.current_weight += 1


class VertexData(BaseModel):
    user_id: str
    mm_settings: MMSettings
    edges: set[str] = set()


class MMDataCache(BaseModel):
    new_users: dict[str, VertexData] = {}
    returning_users: set[str] = set()
    disconnected_users: set[str] = set()
    decline_pairs: list[Tuple[str, str]] = []

    sent_matches: dict[str, str] = dict()
    online_users: set[str] = set()

    def clear(self):
        self.new_users.clear()
        self.returning_users.clear()
        self.disconnected_users.clear()
        self.decline_pairs.clear()

    def disconnect(self, user_id: str):
        self.disconnected_users.add(user_id)
        self.online_users.remove(user_id)

    def reconnect(self, user_id: str):
        self.returning_users.add(user_id)

    def reconnect_decline(self, user_a_id: str, user_b_id: str):
        self.decline_pairs.append((user_a_id, user_b_id))
        self.sent_matches.pop(user_a_id, None)
        self.sent_matches.pop(user_b_id, None)

    def connect(self, user_id: str, mm_settings: MMSettings,
                connections: IDList):
        self.online_users.add(user_id)

        new_vertex = VertexData(user_id=user_id, mm_settings=mm_settings)
        for connection in connections:
            new_vertex.edges.add(str(connection))
        self.new_users[user_id] = new_vertex

    def repr_matchmaking(self):
        return f'new: {self.new_users}, ' \
               f'returning: {self.returning_users}, ' \
               f'disconnected: {self.disconnected_users}, ' \
               f'declines: {self.decline_pairs}'

    def __repr__(self):
        return f'{self.repr_matchmaking()}, ' \
               f'sent_matches: {self.sent_matches}, ' \
               f'online_users: {self.online_users}'

    def remove_match(self, user_id: str):
        self.sent_matches.pop(user_id, None)

    def add_match(self, user_a: str, user_b: str):
        self.sent_matches[user_a] = user_b
        self.sent_matches[user_b] = user_a

    def get_match(self, user_id: str):
        return self.sent_matches.get(user_id)
