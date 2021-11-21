import asyncio
import datetime
import logging
from uuid import UUID

from dateutil.relativedelta import relativedelta
from fastapi import FastAPI, Body, Query, Depends
from fastapi import WebSocket
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import Response
from starlette.websockets import WebSocketDisconnect
from uvicorn import Config, Server

from swipe.chat_server.services import ConnectedUser, WSConnectionManager, \
    MMUserData
from swipe.matchmaking.schemas import MMBasePayload, MMMatchPayload, \
    MMResponseAction, MMLobbyPayload, MMLobbyAction, MMSettings, MMDataCache
from swipe.matchmaking.services import MMUserService
from swipe.settings import settings
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import IDList

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
matchmaking_data = MMDataCache()
connection_manager = WSConnectionManager()


@app.websocket("/connect/{user_id}")
async def matchmaker_endpoint(user_id: UUID, websocket: WebSocket,
                              user_service: MMUserService = Depends(),
                              gender: Gender = Query(None)):
    if (user := user_service.get_matchmaking_preview(user_id)) is None:
        logger.info(f"User {user_id} not found")
        await websocket.close(1003)
        return

    age_delta = relativedelta(datetime.date.today(), user.date_of_birth)
    age = round(age_delta.years + age_delta.months / 12)

    logger.info(f"{user_id}, rounded age: {age} "
                f"connected with filter: {gender}")

    user_id = str(user_id)
    user = ConnectedUser(user_id=user_id, connection=websocket,
                         data=MMUserData(age=age, gender_filter=gender,
                                         gender=user.gender))
    await connection_manager.connect(user)

    while True:
        try:
            data: dict = await websocket.receive_json()
            logger.info(f"Received data {data} from {user_id}")
        except WebSocketDisconnect as e:
            logger.info(f"{user_id} disconnected with code {e.code}, "
                        f"removing him from matchmaking")

            user_id_str = str(user_id)
            matchmaking_data.disconnect(user_id_str)
            await connection_manager.disconnect(user_id)

            # we need to keep track of sent matches so that we could
            # send decline events if one of the users disconnects
            # on the match screen
            if match_user_id := matchmaking_data.sent_matches.get(user_id_str):
                logger.info(f"Removing {user_id_str} from sent matches")
                matchmaking_data.sent_matches.pop(user_id_str, None)

                logger.info(
                    f"Removing {match_user_id}, match of {user_id_str}"
                    f"from sent matches")
                matchmaking_data.sent_matches.pop(match_user_id, None)

                if match_user_id in connection_manager.active_connections:
                    logger.info(f"Sending decline to {match_user_id}, "
                                f"match of {user_id_str} and reconnecting "
                                f"to matchmaker")
                    payload = MMMatchPayload(action=MMResponseAction.DECLINE)
                    await connection_manager.send(
                        match_user_id,
                        MMBasePayload(
                            sender_id=user_id_str,
                            recipient_id=match_user_id,
                            payload=payload).dict(by_alias=True))
                    # placing this guy back to next round
                    matchmaking_data.reconnect(match_user_id)
            return

        try:
            base_payload: MMBasePayload = MMBasePayload.validate(data)
            await _process_payload(base_payload, user.data, user_service)

            if base_payload.recipient_id:
                await connection_manager.send(
                    base_payload.recipient_id,
                    base_payload.dict(by_alias=True, exclude_unset=True))
        except:
            logger.exception(f"Error processing payload from {user_id}")


async def _process_payload(base_payload: MMBasePayload, user_data: MMUserData,
                           user_service: MMUserService):
    data_payload = base_payload.payload
    sender_id = base_payload.sender_id
    recipient_id = base_payload.recipient_id

    if isinstance(data_payload, MMMatchPayload):
        if data_payload.action == MMResponseAction.ACCEPT:
            logger.info(f"{sender_id} accepted match, "
                        f"removing from sent_matches")
            matchmaking_data.sent_matches.pop(sender_id, None)
        elif data_payload.action == MMResponseAction.DECLINE:
            # one decline -> put both back to MM
            logger.info(
                f"Got decline from {sender_id}, "
                f"placing him and {recipient_id} "
                f"back to matchmaker, removing from sent matches")
            matchmaking_data.reconnect_decline(sender_id, recipient_id)
            # a decline means we add them to each others blacklist
            user_service.update_blacklist(sender_id, recipient_id)
    elif isinstance(data_payload, MMLobbyPayload):
        if data_payload.action == MMLobbyAction.CONNECT:
            # user joined the lobby
            mm_settings = MMSettings(
                age=user_data.age,
                gender=user_data.gender,
                gender_filter=user_data.gender_filter)
            logger.info(f"Connecting {sender_id} to matchmaking, "
                        f"settings: {mm_settings}")
            logger.info(f"Current online users {matchmaking_data.online_users}")
            connections: IDList = \
                user_service.find_user_ids(
                    sender_id,
                    age=mm_settings.age,
                    online_users=matchmaking_data.online_users,
                    age_difference=mm_settings.age_diff,
                    gender=mm_settings.gender)
            logger.info(f"Connections for {sender_id}: {connections}")
            matchmaking_data.connect(
                sender_id, mm_settings, connections)
        elif data_payload.action == MMLobbyAction.RECONNECT:
            # user tapped next or add to friends
            logger.info(f"Reconnecting {sender_id} after a call")
            matchmaking_data.reconnect(sender_id)


@app.post('/send_match')
async def send_match_data(request: Request):
    match_data: dict = await request.json()
    logger.info(f"Got match {match_data}, sending to clients")
    user_a_id, user_b_id = match_data['match']
    if connection_manager.is_connected(user_a_id):
        if connection_manager.is_connected(user_b_id):
            # both connected
            logger.info(f"Both are connected, "
                        f"sending matches to {user_a_id}, {user_b_id}")
            matchmaking_data.sent_matches[user_a_id] = user_b_id
            matchmaking_data.sent_matches[user_b_id] = user_a_id

            await connection_manager.send(user_b_id, {
                'match': user_a_id, 'host': False
            })
            await connection_manager.send(user_a_id, {
                'match': user_b_id, 'host': True
            })
            return Response()
    # if at least one is not available -> put both back to lobby
    logger.info(f"One of the matches is not online anymore, "
                f"returning both {user_a_id} and {user_b_id} to matchmaking")
    matchmaking_data.reconnect(user_a_id)
    matchmaking_data.reconnect(user_b_id)
    return Response()


@app.get('/new_round_data', response_model=MMDataCache)
async def fetch_new_round_data(request: Request):
    logger.info("Got a request to fetch new round data")
    response_data = matchmaking_data.dict(
        exclude={'sent_matches', 'online_users'})
    logger.info("Removing data before the next round")
    matchmaking_data.clear()
    return response_data


def start_server():
    server_config = Config(app=app, host='0.0.0.0',
                           port=settings.MATCHMAKING_SERVER_PORT,
                           workers=1, loop='asyncio')
    server = Server(server_config)
    loop.run_until_complete(server.serve())
