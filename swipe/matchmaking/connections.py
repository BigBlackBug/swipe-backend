import json
import logging
from asyncio import StreamWriter

from swipe.matchmaking.schemas import MMSettings

logger = logging.getLogger(__name__)


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

    async def disconnect(self, user_id: str, remove_settings: bool = False):
        self.writer.write(json.dumps({
            'user_id': user_id,
            'operation': 'disconnect',
            'remove_settings': remove_settings
        }).encode('utf-8'))
        self.writer.write(b'\n')
        await self.writer.drain()

    async def reconnect(self, user_id: str):
        self.writer.write(json.dumps({
            'user_id': user_id,
            'operation': 'reconnect'
        }).encode('utf-8'))
        self.writer.write(b'\n')
        await self.writer.drain()
