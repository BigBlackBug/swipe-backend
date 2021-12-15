from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from starlette.websockets import WebSocket

from swipe.swipe_server.users.enums import Gender

logger = logging.getLogger(__name__)


class PayloadEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, datetime.datetime):
            return str(obj)
        elif isinstance(obj, bytes):
            # avatars are b64 encoded byte strings
            return obj.decode('utf-8')
        return json.JSONEncoder.default(self, obj)


@dataclass
class ChatUserData:
    user_id: str
    name: str
    avatar_url: str
    gender: Gender


@dataclass
class MMUserData:
    age: int
    gender: Gender
    gender_filter: Optional[Gender] = None


class ConnectedUser:
    def __init__(self, user_id: str, connection: WebSocket,
                 data: Optional[ChatUserData | MMUserData] = None):
        self.connection = connection
        self.user_id = user_id
        self.data = data


class WSConnectionManager:
    active_connections: dict[str, ConnectedUser] = {}

    def get_user_data(self, user_id: str) \
            -> Optional[ChatUserData | MMUserData]:
        return self.active_connections[user_id].data \
            if user_id in self.active_connections else None

    async def connect(self, user: ConnectedUser):
        await user.connection.accept()
        self.active_connections[user.user_id] = user

    async def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    async def send(self, user_id: str, payload: dict):
        if user_id not in self.active_connections:
            logger.info(f"{user_id} is not online, payload won't be sent")
            return

        # TODO stupid workaround
        if 'payload' in payload:
            payload_type = payload['payload'].get('type', '???')
        else:
            payload_type = payload.get('type', payload)

        logger.info(f"Sending '{payload_type}' payload to {user_id}")
        # TODO use orjson instead of that dumb encoder shit
        try:
            await self.active_connections[user_id].connection.send_text(
                json.dumps(payload, cls=PayloadEncoder))
        except:
            logger.exception(f"Unable to send '{payload_type}' to {user_id}")

    async def broadcast(self, sender_id: str, payload: dict):
        # TODO stupid workaround
        if 'payload' in payload:
            payload_type = payload['payload'].get('type', '???')
        else:
            payload_type = payload.get('type', payload)

        logger.info(f"Broadcasting '{payload_type}' event of {sender_id}")

        # it's required because another coroutine might change this dict
        user_ids = list(self.active_connections.keys())
        for user_id in user_ids:
            if user_id == sender_id:
                continue

            logger.info(f"Sending '{payload_type}' payload of {sender_id} "
                        f"to {user_id}")
            try:
                if user := self.active_connections.get(user_id, None):
                    await user.connection.send_text(
                        json.dumps(payload, cls=PayloadEncoder))
            except:
                logger.exception(
                    f"Unable to send '{payload_type}' payload "
                    f"of {sender_id} to {user_id}")

    def is_connected(self, user_id: str):
        return user_id in self.active_connections
