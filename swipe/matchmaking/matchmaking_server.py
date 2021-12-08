import asyncio
import logging
import secrets

import requests
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
    MMResponseAction, MMLobbyPayload, MMLobbyAction, MMSettings, MMRoundData, \
    MMChatPayload, MMChatAction
from swipe.matchmaking.services import MMUserService
from swipe.settings import settings, constants
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.schemas import OnlineFilterBody
from swipe.swipe_server.users.services.fetch_service import FetchUserService
from swipe.swipe_server.users.services.online_cache import \
    RedisMatchmakingOnlineUserService
from swipe.swipe_server.users.services.redis_services import \
    RedisChatCacheService
from swipe.swipe_server.users.services.services import BlacklistService

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
matchmaking_data = MMRoundData()
connection_manager = WSConnectionManager()


@app.websocket("/connect/{user_id}")
async def matchmaker_endpoint(
        user_id: str, websocket: WebSocket,
        gender: Gender = Query(None)):
    redis_online = RedisMatchmakingOnlineUserService(dependencies.redis())
    user: User
    with dependencies.db_context(expire_on_commit=False) as session:
        # loading only age and gender
        user_service = MMUserService(session)
        if (user := user_service.get_matchmaking_preview(user_id)) is None:
            logger.info(f"User {user_id} not found")
            await websocket.close(1003)
            return

        partner_ids: list[str] = user_service.get_user_chat_partners(user_id)

    await redis_online.add_to_online_caches(user)
    logger.info(f"{user_id}, rounded age: {user.age} "
                f"connected with filter: {gender}")

    connected_user = ConnectedUser(
        user_id=user_id, connection=websocket,
        data=MMUserData(age=user.age, gender_filter=gender, gender=user.gender))
    await connection_manager.connect(connected_user)

    logger.info(f"Chat partners of {user_id}: {partner_ids}")
    redis_chats = RedisChatCacheService(dependencies.redis())
    await redis_chats.save_chat_partner_cache(user_id, partner_ids)

    while True:
        try:
            data: dict = await websocket.receive_json()
            logger.info(f"Received data {data} from {user_id}")
        except WebSocketDisconnect as e:
            logger.info(f"{user_id} disconnected with code {e.code}, "
                        f"removing him from matchmaking")
            await redis_online.remove_from_online_caches(user)
            await _process_disconnect(user_id)
            return

        try:
            base_payload: MMBasePayload = MMBasePayload.validate(data)
            await _process_payload(base_payload, connected_user)

            if base_payload.recipient_id:
                await connection_manager.send(
                    base_payload.recipient_id,
                    base_payload.dict(by_alias=True, exclude_unset=True))
        except:
            logger.exception(f"Error processing payload from {user_id}")


async def _process_disconnect(user_id: str):
    matchmaking_data.disconnect(user_id)
    await connection_manager.disconnect(user_id)
    # user disconnected, his chat cache is no longer needed
    redis_chats = RedisChatCacheService(dependencies.redis())
    await redis_chats.drop_chat_partner_cache(user_id)

    # we need to keep track of sent matches so that we could
    # send decline/reconnect events if one of the users disconnects

    # A disconnects on a match screen or on call
    if match := matchmaking_data.get_match(user_id):
        logger.info(f"{user_id} is matched with {match.user_id}")

        match_status = matchmaking_data.get_match(match.user_id)
        if match_status.accepted and match.accepted:
            # they are on call, send B reconnect signal
            logger.info(
                f"{user_id} and {match.user_id} were on call, "
                f"sending reconnect to {match.user_id}")
            reconnect = MMLobbyPayload(action=MMLobbyAction.RECONNECT)
            await connection_manager.send(
                match.user_id,
                MMBasePayload(
                    sender_id=user_id,
                    recipient_id=match.user_id,
                    payload=reconnect).dict(by_alias=True))
        else:
            # B is also on the match screen
            logger.info(f"{match.user_id} is on a match screen, "
                        f"sending decline")
            decline = MMMatchPayload(action=MMResponseAction.DECLINE)
            await connection_manager.send(
                match.user_id,
                MMBasePayload(
                    sender_id=user_id,
                    recipient_id=match.user_id,
                    payload=decline).dict(by_alias=True))

            logger.info(f"Reconnecting {match.user_id} to matchmaking")
            matchmaking_data.reconnect(match.user_id)

        logger.info(f"Removing {user_id} from sent matches")
        matchmaking_data.remove_match(user_id)

        logger.info(
            f"Removing {match.user_id}, match of {user_id}"
            f"from sent matches")
        matchmaking_data.remove_match(match.user_id)


async def _process_payload(base_payload: MMBasePayload,
                           connected_user: ConnectedUser):
    data_payload = base_payload.payload
    sender_id = base_payload.sender_id
    recipient_id = base_payload.recipient_id

    if isinstance(data_payload, MMMatchPayload):
        if data_payload.action == MMResponseAction.ACCEPT:
            logger.info(f"{sender_id} accepted match")
            matchmaking_data.accept_match(sender_id)
        elif data_payload.action == MMResponseAction.DECLINE:
            # one decline -> put both back to MM
            logger.info(
                f"Got decline from {sender_id}, "
                f"placing him and {recipient_id} "
                f"back to matchmaker, removing from sent matches")
            matchmaking_data.reconnect_decline(sender_id, recipient_id)
            matchmaking_data.remove_match(sender_id)
            matchmaking_data.remove_match(recipient_id)

            # a decline means we add them to each others blacklist
            if settings.ENABLE_MATCHMAKING_BLACKLIST:
                with dependencies.db_context() as session:
                    blacklist_service = BlacklistService(
                        session, dependencies.redis())
                    await blacklist_service.update_blacklist(
                        sender_id, recipient_id)
    elif isinstance(data_payload, MMLobbyPayload):
        if data_payload.action == MMLobbyAction.CONNECT:
            # user joined the lobby
            user_data = connected_user.data
            mm_settings = MMSettings(
                age=user_data.age,
                gender=user_data.gender,
                gender_filter=user_data.gender_filter,
                session_id=secrets.token_urlsafe(16))
            logger.info(f"Connecting {sender_id} to matchmaking, "
                        f"settings: {mm_settings}")
            logger.info(f"Current online users {matchmaking_data.online_users}")

            redis_chats = RedisChatCacheService(dependencies.redis())
            chat_partners = await redis_chats.get_chat_partners(sender_id)

            logger.info(f"Chat partners for {sender_id}: {chat_partners}")
            fetch_service = FetchUserService(
                RedisMatchmakingOnlineUserService(dependencies.redis()),
                dependencies.redis())
            connections = await fetch_service.collect(
                sender_id,
                user_age=mm_settings.age,
                filter_params=OnlineFilterBody(
                    session_id=mm_settings.session_id,
                    gender=mm_settings.gender_filter,
                    limit=constants.MATCHMAKING_FETCH_LIMIT
                ),
                disallowed_users=chat_partners)
            logger.info(f"Got connections for {sender_id}: {connections}")
            matchmaking_data.connect(
                sender_id, mm_settings, connections)
        elif data_payload.action == MMLobbyAction.RECONNECT:
            logger.info(f"Reconnecting {sender_id} to matchmaking")
            matchmaking_data.reconnect(sender_id)
    elif isinstance(data_payload, MMChatPayload):
        if data_payload.action == MMChatAction.ACCEPT:
            logger.info(
                f"{sender_id} has accepted chat request from {recipient_id}, "
                f"sending request to chat server")
            url = f'{settings.CHAT_SERVER_HOST}/matchmaking/chat'
            # yeah they are reversed
            output_payload = {
                'sender_id': base_payload.recipient_id,
                'recipient_id': base_payload.sender_id,
                'payload': {
                    'type': 'create_chat',
                    'source': data_payload.source.value,
                    'chat_id': str(data_payload.chat_id)
                }
            }
            # TODO use aiohttp?
            requests.post(url, json=output_payload)


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
            matchmaking_data.add_match(user_a_id, user_b_id)

            await connection_manager.send(user_b_id, {
                'match': user_a_id, 'host': False
            })
            await connection_manager.send(user_a_id, {
                'match': user_b_id, 'host': True
            })

    return Response()


@app.get('/new_round_data', response_model=MMRoundData)
async def fetch_new_round_data(request: Request):
    response_data = matchmaking_data.dict(
        exclude={'sent_matches', 'online_users'})
    logger.info("New round started, clearing cache")
    matchmaking_data.clear()
    return response_data


@app.get(
    '/fetch_candidates',
    name='Fetch candidates for matchmaking',
    responses={
        200: {'description': 'List of users according to filter'},
        400: {'description': 'Bad Request'},
    })
async def fetch_user_ids_for_matchmaking(
        user_id: str = Query(None),
        user_age: int = Query(None),
        gender_filter: Gender = Query(None),
        session_id: str = Query(None),
        redis_chats: RedisChatCacheService = Depends()):
    chat_partners = await redis_chats.get_chat_partners(user_id)
    logger.info(f"Chat partners of {user_id}: {chat_partners}")
    fetch_service = FetchUserService(
        RedisMatchmakingOnlineUserService(dependencies.redis()),
        dependencies.redis())
    connections = await fetch_service.collect(
        user_id,
        user_age=user_age,
        filter_params=OnlineFilterBody(
            session_id=session_id,
            gender=gender_filter,
            limit=100
        ),
        disallowed_users=chat_partners)

    logger.info(f"Got possible connections for {user_id}: {connections}")
    return {
        'connections': connections
    }


def start_server():
    server_config = Config(app=app, host='0.0.0.0',
                           port=settings.MATCHMAKING_SERVER_PORT,
                           workers=1, loop='asyncio')
    server = Server(server_config)
    loop.run_until_complete(server.serve())
