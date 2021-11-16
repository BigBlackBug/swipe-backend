import json
import logging
from asyncio import StreamWriter

from swipe.matchmaking.schemas import MMSettings

logger = logging.getLogger(__name__)


class MM2WSConnection:
    def __init__(self, writer: StreamWriter):
        self.writer = writer

    async def send_match(self, user_a, user_b):
        logger.info(f"Sending match {user_a}-{user_b} to ws handler")
        self.writer.write(json.dumps({
            'match': [user_a, user_b]
        }).encode('utf-8'))
        self.writer.write(b'\n')
        await self.writer.drain()


class WS2MMConnection:
    def __init__(self, writer: StreamWriter):
        self.writer = writer

    async def connect(self, user_id: str, settings: MMSettings):
        self.writer.write(json.dumps({
            'user_id': user_id,
            'operation': 'connect',
            'settings': settings.dict()
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
