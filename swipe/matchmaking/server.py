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

import swipe.swipe_server.misc.database as database
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


sent_matches: dict[str:str] = dict()


@app.websocket("/connect/{user_id}")
async def matchmaker_endpoint(
        user_id: UUID,
        websocket: WebSocket,
        gender: Gender = Query(None),
        connection_manager: WSConnectionManager = Depends()):
    with database.session_context() as db:
        user_service = MMUserService(db)
        if (user := user_service.get_matchmaking_preview(user_id)) is None:
            logger.info(f"User {user_id} not found")
            await websocket.close(1003)
            return
    user_id_str = str(user_id)
    logger.info(f"{user_id} connected with filter: {gender}")

    user_data: MMPreview = MMPreview.from_orm(user)
    user = ConnectedUser(user_id=user_id,
                         age=user_data.age, connection=websocket)
    await connection_manager.connect(user)
    await matchmaker.connect(
        user_id_str, settings=MMSettings(age=user.age, gender=gender))

    while True:
        try:
            data: dict = await websocket.receive_json()
            logger.info(f"Received data {data} from {user_id}")
        except WebSocketDisconnect as e:
            logger.info(f"{user_id} disconnected with code {e.code}, "
                        f"removing him from matchmaking")
            await connection_manager.disconnect(user_id)
            await matchmaker.disconnect(user_id_str)

            if match_user_id := sent_matches.get(user_id_str):
                logger.info(f"Removing {user_id_str} from sent matches")
                sent_matches.pop(user_id_str, None)

                logger.info(
                    f"Removing {match_user_id}, match of {user_id_str}"
                    f"from sent matches")
                sent_matches.pop(match_user_id, None)

                logger.info(f"Sending decline to {match_user_id}, "
                            f"match of {user_id_str}")
                await connection_manager.send(
                    UUID(hex=match_user_id),
                    MMBasePayload(
                        sender_id=user_id_str,
                        recipient_id=match_user_id,
                        payload=MMMatchPayload(
                            action=MMResponseAction.DECLINE))
                        .dict(by_alias=True))

                logger.info(f"Reconnecting {match_user_id} to matchmaker")
                await matchmaker.reconnect(match_user_id)
            return

        try:
            payload: MMBasePayload = MMBasePayload.validate(data)
            if isinstance(payload.payload, MMMatchPayload):
                if payload.payload.action == MMResponseAction.ACCEPT:
                    logger.info(f"{payload.sender_id} accepted match, "
                                f"removing from sent_matches")
                    sent_matches.pop(payload.sender_id, None)
                elif payload.payload.action == MMResponseAction.DECLINE:
                    # one decline -> put both back to MM
                    logger.info(
                        f"Got decline from {payload.sender_id}, placing him "
                        f"and {payload.recipient_id} back to matchmaker, "
                        f"removing from sent matches")
                    sent_matches.pop(payload.sender_id, None)
                    sent_matches.pop(payload.recipient_id, None)
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

    async def _send_match_data(user_a_id: str, user_b_id: str):
        user_a = UUID(hex=user_a_id)
        user_b = UUID(hex=user_b_id)

        decline_payload = MMMatchPayload(action=MMResponseAction.DECLINE)
        if connection_manager.is_connected(user_a):
            if connection_manager.is_connected(user_b):
                # both connected
                logger.info(f"Sending matches to {user_a_id}, {user_b_id}")
                await connection_manager.send(user_b, {
                    'match': user_a, 'host': False
                })
                await connection_manager.send(user_a, {
                    'match': user_b, 'host': True
                })
                sent_matches[user_a_id] = user_b_id
                sent_matches[user_b_id] = user_a_id
            else:
                # if B is gone, send decline to A
                await connection_manager.send(
                    user_a,
                    MMBasePayload(
                        sender_id=user_b_id,
                        recipient_id=user_a_id,
                        payload=decline_payload).dict(by_alias=True))
        elif connection_manager.is_connected(user_b):
            # if A is gone, send decline to B
            await connection_manager.send(
                user_b,
                MMBasePayload(
                    sender_id=user_a_id,
                    recipient_id=user_b_id,
                    payload=decline_payload).dict(by_alias=True))

    reader: StreamReader
    while True:
        try:
            logger.info(f"Waiting for data from matchmaker")
            raw_data = await mm_reader.readline()
            logger.info(f"Read raw match data {raw_data} from matchmaker")
            if not raw_data:
                logger.exception("Matchmaker down")
                break

            match_data: dict = json.loads(raw_data)
            user_a_raw, user_b_raw = match_data['match']
            await _send_match_data(user_a_raw, user_b_raw)
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
