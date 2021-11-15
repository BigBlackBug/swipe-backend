import json
import logging
from asyncio import StreamWriter

logger = logging.getLogger(__name__)


class MMServerConnection:
    def __init__(self, writer: StreamWriter):
        self.writer = writer

    async def send_match(self, user_a, user_b):
        self.writer.write(json.dumps({
            'match': [user_a, user_b]
        }).encode('utf-8'))
        self.writer.write(b'\n')
        await self.writer.drain()


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
