import asyncio
import datetime
import json
import logging
from asyncio import StreamReader
from uuid import UUID

from dateutil.relativedelta import relativedelta
from fastapi import FastAPI, Body, Query
from fastapi import WebSocket
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect
from uvicorn import Config, Server

import swipe.swipe_server.misc.database as database
from swipe.chat_server.services import ConnectedUser, WSConnectionManager
from swipe.matchmaking.connections import WS2MMConnection
from swipe.matchmaking.schemas import MMBasePayload, MMMatchPayload, \
    MMResponseAction, MMLobbyPayload, MMLobbyAction, MMSettings
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


loop = asyncio.get_event_loop()
matchmaker: WS2MMConnection
sent_matches: dict[str, str] = dict()
connection_manager = WSConnectionManager()

DECLINE_PAYLOAD = MMMatchPayload(action=MMResponseAction.DECLINE)


@app.websocket("/connect/{user_id}")
async def matchmaker_endpoint(user_id: str, websocket: WebSocket,
                              date_of_birth: datetime.date = Query(...),
                              gender: Gender = Query(None)):
    try:
        UUID(hex=user_id)
    except ValueError:
        logger.exception(f"Invalid user id: {user_id}")
        await websocket.close(1003)

    with database.session_context() as db:
        user_service = MMUserService(db)
        if not user_service.user_exists(user_id):
            logger.info(f"User {user_id} not found")
            await websocket.close(1003)
            return

    age_delta = relativedelta(datetime.date.today(), date_of_birth)
    age = round(age_delta.years + age_delta.months / 12)

    logger.info(f"{user_id}, rounded age: {age} "
                f"connected with filter: {gender}")

    user = ConnectedUser(user_id=user_id, age=age, connection=websocket)
    await connection_manager.connect(user)

    while True:
        try:
            data: dict = await websocket.receive_json()
            logger.info(f"Received data {data} from {user_id}")
        except WebSocketDisconnect as e:
            logger.info(f"{user_id} disconnected with code {e.code}, "
                        f"removing him from matchmaking")

            user_id_str = str(user_id)
            await matchmaker.disconnect(user_id_str, remove_settings=True)
            await connection_manager.disconnect(user_id)

            # we need to keep track of sent matches so that we could
            # send decline events if one of the users disconnects
            # on the match screen
            if match_user_id := sent_matches.get(user_id_str):
                logger.info(f"Removing {user_id_str} from sent matches")
                sent_matches.pop(user_id_str, None)

                logger.info(
                    f"Removing {match_user_id}, match of {user_id_str}"
                    f"from sent matches")
                sent_matches.pop(match_user_id, None)

                if match_user_id in connection_manager.active_connections:
                    logger.info(f"Sending decline to {match_user_id}, "
                                f"match of {user_id_str} and reconnecting "
                                f"to matchmaker")
                    await connection_manager.send(
                        match_user_id,
                        MMBasePayload(
                            sender_id=user_id_str,
                            recipient_id=match_user_id,
                            payload=DECLINE_PAYLOAD).dict(by_alias=True))

                    await matchmaker.reconnect(match_user_id)
            return

        try:
            base_payload: MMBasePayload = MMBasePayload.validate(data)
            await _process_payload(base_payload, user)

            if base_payload.recipient_id:
                await connection_manager.send(
                    base_payload.recipient_id,
                    base_payload.dict(by_alias=True, exclude_unset=True))
        except:
            logger.exception(f"Error processing payload from {user_id}")


async def _process_payload(base_payload: MMBasePayload, user: ConnectedUser):
    data_payload = base_payload.payload
    sender_id = base_payload.sender_id
    recipient_id = base_payload.recipient_id

    if isinstance(data_payload, MMMatchPayload):
        if data_payload.action == MMResponseAction.ACCEPT:
            logger.info(f"{sender_id} accepted match, "
                        f"removing from sent_matches")
            sent_matches.pop(sender_id, None)
        elif data_payload.action == MMResponseAction.DECLINE:
            # one decline -> put both back to MM
            logger.info(
                f"Got decline from {sender_id}, "
                f"placing him and {recipient_id} "
                f"back to matchmaker, removing from sent matches")
            sent_matches.pop(sender_id, None)
            sent_matches.pop(recipient_id, None)

            await matchmaker.reconnect(sender_id)
            await matchmaker.reconnect(recipient_id)
    elif isinstance(data_payload, MMLobbyPayload):
        if data_payload.action == MMLobbyAction.CONNECT:
            # user joined or pressed next, connect to matchmaking
            logger.info(f"Connecting {sender_id} to matchmaking")
            await matchmaker.connect(sender_id, settings=MMSettings(
                age=user.age, gender=user.gender_filter))
        elif data_payload.action == MMLobbyAction.DISCONNECT:
            # call has started, disconnect from matchmaking
            logger.info(f"Call has started, disconnecting "
                        f"{sender_id} from matchmaking")
            await matchmaker.disconnect(sender_id)


# same main process, so we're safe with using a module level connection_manager
async def _send_match_data(user_a_id: str, user_b_id: str):
    if connection_manager.is_connected(user_a_id):
        if connection_manager.is_connected(user_b_id):
            # both connected
            logger.info(f"Both are connected, "
                        f"sending matches to {user_a_id}, {user_b_id}")
            await connection_manager.send(user_b_id, {
                'match': user_a_id, 'host': False
            })
            sent_matches[user_a_id] = user_b_id

            await connection_manager.send(user_a_id, {
                'match': user_b_id, 'host': True
            })
            sent_matches[user_b_id] = user_a_id
        else:
            logger.info(f"{user_b_id} is gone, "
                        f"sending decline to {user_a_id}")
            # if B is gone, send decline to A
            await connection_manager.send(
                user_a_id,
                MMBasePayload(
                    sender_id=user_b_id,
                    recipient_id=user_a_id,
                    payload=DECLINE_PAYLOAD).dict(by_alias=True))
    elif connection_manager.is_connected(user_b_id):
        logger.info(f"{user_a_id} is gone, "
                    f"sending decline to {user_b_id}")
        # if A is gone, send decline to B
        await connection_manager.send(
            user_b_id,
            MMBasePayload(
                sender_id=user_a_id,
                recipient_id=user_b_id,
                payload=DECLINE_PAYLOAD).dict(by_alias=True))


async def match_sender(mm_reader: StreamReader):
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
    logger.info("Connected to matchmaking server")
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
