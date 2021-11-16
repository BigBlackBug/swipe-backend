import asyncio
import json
import logging
from asyncio import StreamReader
from uuid import UUID

from fastapi import FastAPI, Depends, Body, Query
from fastapi import WebSocket
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect
from uvicorn import Config, Server

from swipe.chat_server.services import ConnectedUser, WSConnectionManager
from swipe.matchmaking.connections import WS2MMConnection
from swipe.matchmaking.schemas import MMBasePayload, MMMatchPayload, \
    MMResponseAction, MMPreview, MMSettings
from swipe.matchmaking.services import MMUserService
from swipe.settings import settings
from swipe.swipe_server.users.enums import Gender

logger = logging.getLogger(__name__)

app = FastAPI()

_supported_payloads = []
for cls in BaseModel.__subclasses__():
    if cls.__name__.endswith('Payload') \
            and cls.__name__.startswith('MM') \
            and 'type_' in cls.__fields__:
        _supported_payloads.append(cls.__name__)

loop = asyncio.get_event_loop()
matchmaker: WS2MMConnection


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
        gender: Gender = Query(None),
        connection_manager: WSConnectionManager = Depends(),
        user_service: MMUserService = Depends()):
    if (user := user_service.get_matchmaking_preview(user_id)) is None:
        logger.info(f"User {user_id} not found")
        await websocket.close(1003)
        return

    logger.info(f"{user_id} connected")

    user_data: MMPreview = MMPreview.from_orm(user)
    user = ConnectedUser(user_id=user_id,
                         age=user_data.age, connection=websocket)
    await connection_manager.connect(user)
    await matchmaker.connect(
        str(user_id), settings=MMSettings(age=user.age, gender=gender))

    while True:
        try:
            data: dict = await websocket.receive_json()
            logger.info(f"Received data {data} from {user_id}")
        except WebSocketDisconnect as e:
            logger.info(f"{user_id} disconnected with code {e.code}")
            await connection_manager.disconnect(user_id)
            await matchmaker.disconnect(str(user_id))
            return

        try:
            payload: MMBasePayload = MMBasePayload.validate(data)
            if isinstance(payload.payload, MMMatchPayload):
                # one decline -> put both back to MM
                if payload.payload.action == MMResponseAction.DECLINE:
                    logger.info(
                        f"Placing {payload.sender_id} "
                        f"and {payload.recipient_id} back to matchmaker")
                    await matchmaker.reconnect(payload.sender_id)
                    await matchmaker.reconnect(payload.recipient_id)

            await connection_manager.send(
                UUID(hex=payload.recipient_id),
                payload.dict(by_alias=True, exclude_unset=True))
        except:
            logger.exception(f"Error processing payload from {user_id}")


async def match_sender(mm_reader: StreamReader):
    # same main process, so we're safe with using a class variable
    connection_manager = WSConnectionManager()

    reader: StreamReader
    while True:
        try:
            logger.info(f"Waiting for data from matchmaker")
            raw_data = await mm_reader.readline()
            logger.info(f"Read raw match data {raw_data} from matchmaker")
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
                await connection_manager.send(user_a, {
                    'match': user_b, 'host': True
                })
                await connection_manager.send(user_b, {
                    'match': user_a, 'host': False
                })
        except:
            logger.exception("Error reading from pipe, matchmaker down?")
            break


async def connect_to_matchmaker():
    logger.info("Connecting to matchmaker server")
    reader, writer = await asyncio.open_connection(
        settings.MATCHMAKER_HOST, settings.MATCHMAKER_PORT, loop=loop)
    global matchmaker
    matchmaker = WS2MMConnection(writer)

    loop.create_task(match_sender(reader))


def start_server():
    server_config = Config(app=app, host='0.0.0.0',
                           port=settings.MATCHMAKING_SERVER_PORT,
                           workers=1, loop='asyncio')
    server = Server(server_config)
    loop.run_until_complete(connect_to_matchmaker())
    loop.run_until_complete(server.serve())
