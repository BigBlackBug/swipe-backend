import json
import logging
from asyncio import StreamWriter
from dataclasses import dataclass
from uuid import UUID

from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)


class UUIDEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, bytes):
            # avatars are b64 encoded byte strings
            return obj.decode('utf-8')
        return json.JSONEncoder.default(self, obj)


class MMServerConnection:
    def __init__(self, writer: StreamWriter):
        self.writer = writer

    async def send_match(self, user_a, user_b):
        self.writer.write(json.dumps({
            'match': [user_a, user_b]
        }).encode('utf-8'))
        self.writer.write(b'\n')
        await self.writer.drain()


@dataclass
class ConnectedUser:
    user_id: UUID
    name: str
    avatar: bytes
    connection: WebSocket


class WSConnectionManager:
    active_connections: dict[UUID, ConnectedUser] = {}

    async def connect(self, user: ConnectedUser):
        await user.connection.accept()
        self.active_connections[user.user_id] = user

    async def disconnect(self, user_id: UUID):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    async def send(self, user_id: UUID, payload: dict):
        logger.info(f"Sending payload to {user_id}")
        if user_id not in self.active_connections:
            logger.info(f"{user_id} is not online, payload won't be sent")
            return

        await self.active_connections[user_id].connection.send_text(
            json.dumps(payload, cls=UUIDEncoder))

    async def broadcast(self, sender_id: UUID, payload: dict):
        for user_id, user in self.active_connections.items():
            if user_id == sender_id:
                continue
            logger.info(f"Sending payload to {user_id}")
            await user.connection.send_text(
                json.dumps(payload, cls=UUIDEncoder))

    def is_connected(self, user_id: UUID):
        return user_id in self.active_connections


class MatchMakerConnection:
    def __init__(self, writer: StreamWriter):
        self.writer = writer

    async def connect(self, user_id: str):
        self.writer.write(json.dumps({
            'user_id': user_id,
            'operation': 'connect'
        }).encode('utf-8'))
        self.writer.write(b'\n')
        await self.writer.drain()

    async def disconnect(self, user_id: str):
        self.writer.write(json.dumps({
            'user_id': user_id,
            'operation': 'disconnect'
        }).encode('utf-8'))
        self.writer.write(b'\n')
        await self.writer.drain()
