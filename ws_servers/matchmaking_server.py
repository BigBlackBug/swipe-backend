import os
import sys

# TODO WTF
sys.path.insert(1, os.path.join(sys.path[0], '..'))
import config

config.configure_logging()

import json
import logging
import asyncio

from pydantic import BaseModel
from ws_servers import matchmaker
from starlette.websockets import WebSocketDisconnect
from ws_servers.schemas import MMBasePayload, MMMatchPayload, \
    MMResponseAction

from asyncio import StreamReader, StreamWriter, Task
from multiprocessing import Process

from aiopipe import aiopipe
from uvicorn import Config, Server

from swipe.users.schemas import UserOutGlobalChatPreviewORM

from uuid import UUID

from fastapi import FastAPI, Depends, Body
from fastapi import WebSocket

from swipe.users.services import UserService
from ws_servers.services import WSConnectionManager, ConnectedUser, \
    MMPipe

logger = logging.getLogger(__name__)

app = FastAPI()

mm_reader_pipe, mm_writer_pipe = aiopipe()
user_event_reader_pipe, user_event_writer_pipe = aiopipe()

_supported_payloads = []
for cls in BaseModel.__subclasses__():
    if cls.__name__.endswith('Payload') \
            and cls.__name__.startswith('MM') \
            and 'type_' in cls.__fields__:
        _supported_payloads.append(cls.__name__)


@app.get("/connect/docs")
async def docs(json_data: MMBasePayload = Body(..., examples={
    'endpoint message': {
        'summary': 'Payload structure',
        'description':
            'Payload takes one of the types listed below:\n' +
            '\n'.join([f"- {x}" for x in _supported_payloads]),
        'value': {
            'sender_id': '<user_id>',
            'recipient_id': '<user_id>',
            'payload': {}
        }
    }
})):
    pass


@app.websocket("/connect/{user_id}")
async def matchmaker_endpoint(
        user_id: UUID,
        websocket: WebSocket,
        connection_manager: WSConnectionManager = Depends(),
        user_service: UserService = Depends()):
    if (user := user_service.get_global_chat_preview_one(user_id)) is None:
        logger.info(f"User {user_id} not found")
        await websocket.close(1003)
        return

    logger.info(f"{user_id} connected")
    user = UserOutGlobalChatPreviewORM.from_orm(user)
    user = ConnectedUser(user_id=user_id, name=user.name,
                         avatar=user.avatar, connection=websocket)
    await connection_manager.connect(user)

    event_writer: StreamWriter
    async with user_event_writer_pipe.open() as event_writer:
        mm_pipe = MMPipe(event_writer)
        mm_pipe.connect(str(user_id))

        while True:
            try:
                # TODO any exception breaks the fucking pipe
                await handle_client(
                    user_id, websocket, connection_manager, mm_pipe)
            except:
                logger.exception("Smth went wrong")
                break


async def handle_client(user_id: UUID, websocket: WebSocket,
                        connection_manager: WSConnectionManager,
                        mm_pipe: MMPipe):
    try:
        data: dict = await websocket.receive_json()
        logger.info(f"Received data {data} from {user_id}")
    except WebSocketDisconnect as e:
        logger.exception(f"{user_id} disconnected with code {e.code}")
        await connection_manager.disconnect(user_id)
        mm_pipe.disconnect(str(user_id))
        raise

    payload: MMBasePayload = MMBasePayload.validate(data)
    if isinstance(payload.payload, MMMatchPayload):
        # one decline -> put both back to MM
        if payload.payload.action == MMResponseAction.DECLINE:
            logger.info(
                f"Placing {payload.sender_id} "
                f"and {payload.recipient_id} back to matchmaker")
            mm_pipe.connect(payload.sender_id)
            mm_pipe.connect(payload.recipient_id)

    await connection_manager.send(
        UUID(hex=payload.recipient_id),
        payload.dict(by_alias=True, exclude_unset=True))


# matchmaker runs in a new process and sends matches through pipe
# connection_manager is running in the same event loop as the pusher
async def match_sender():
    with mm_writer_pipe.detach() as writer_pipe, \
            user_event_reader_pipe.detach() as reader_pipe:
        logger.info("Starting the matchmaker process")
        proc = Process(target=matchmaker.main,
                       args=(reader_pipe, writer_pipe))
        proc.start()

    # same main process, so we're safe with using a class variable
    connection_manager = WSConnectionManager()

    reader: StreamReader
    async with mm_reader_pipe.open() as reader:
        while True:
            try:
                raw_data = await reader.readline()
                logger.info(f"Read raw match data {raw_data}")
                if not raw_data:
                    logger.info("No match data from matchmaker")
                    break

                match_data: dict = json.loads(raw_data)
                user_a_raw, user_b_raw = match_data['match']
                user_a = UUID(hex=user_a_raw)
                user_b = UUID(hex=user_b_raw)

                if connection_manager.is_connected(user_a) \
                        and connection_manager.is_connected(user_b):
                    # TODO what if one of them is gone by this time?
                    await connection_manager.send(user_a, {'match': user_b})
                    await connection_manager.send(user_b, {'match': user_a})
            except:
                logger.exception("Error reading from pipe, matchmaker down?")
                break

    proc.join()


if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    pusher_future: Task = loop.create_task(match_sender())
    logger.info(f"Created match sender {pusher_future}, starting server")

    config = Config(app=app, host='0.0.0.0', port=17000, loop='asyncio')
    server = Server(config)
    loop.run_until_complete(server.serve())
