import asyncio
import datetime
import json
import logging
from uuid import UUID

import aioredis
from fastapi import FastAPI, Depends, Body
from fastapi import WebSocket
from firebase_admin import messaging as firebase
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.responses import Response
from starlette.websockets import WebSocketDisconnect
from uvicorn import Server, Config

from swipe import error_handlers
from swipe.chat_server.schemas import BasePayload, GlobalMessagePayload, \
    MessagePayload, CreateChatPayload, \
    UserJoinEventPayload, GenericEventPayload, UserEventType, DeclineChatPayload
from swipe.chat_server.services import ChatServerRequestProcessor, \
    WSConnectionManager, ConnectedUser, ChatUserData
from swipe.settings import settings
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.services.online_cache import \
    RedisOnlineUserService
from swipe.swipe_server.users.services.redis_services import \
    RedisBlacklistService, RedisUserFetchService, RedisChatCacheService, \
    RedisFirebaseService
from swipe.swipe_server.users.services.services import UserService

logger = logging.getLogger(__name__)

app = FastAPI()

_supported_payloads = []
for cls in BaseModel.__subclasses__():
    if cls.__name__.endswith('Payload') \
            and not cls.__name__.startswith('MM') \
            and 'type_' in cls.__fields__:
        _supported_payloads.append(cls.__name__)


@app.get("/connect/docs")
async def docs(json_data: BasePayload = Body(..., examples={
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


connection_manager = WSConnectionManager()
loop = asyncio.get_event_loop()


@app.websocket("/connect/{user_id}")
async def websocket_endpoint(
        user_id: str,
        websocket: WebSocket,
        redis: aioredis.Redis = Depends(dependencies.redis)):
    try:
        user_uuid = UUID(hex=user_id)
    except ValueError:
        logger.exception(f"Invalid user id: {user_id}")
        await websocket.close(1003)
        return

    user: User
    with dependencies.db_context(expire_on_commit=False) as session:
        user_service = UserService(session)
        # loading only required fields
        if user := user_service.get_user_card_preview(user_uuid):
            user.last_online = None
            session.commit()
        else:
            logger.info(f"User {user_id} not found")
            await websocket.close(1003)
            return
        blacklist: set[str] = await user_service.fetch_blacklist(user_id)

    firebase_service = RedisFirebaseService(redis)
    # we're online so we don't need a token in cache
    await firebase_service.remove_token_from_cache(user_id)

    redis_online = RedisOnlineUserService(redis)
    redis_chats = RedisChatCacheService(redis)
    redis_blacklist = RedisBlacklistService(redis)
    redis_fetch = RedisUserFetchService(redis)

    # gender, dob, location, name, firebase_token, avatar_id + avatar_url
    await redis_online.add_to_online_caches(user)
    # they may have returned before the cache is dropped
    await redis_online.remove_from_recently_online(user_id)

    user_data = ChatUserData(
        user_id=user_id, avatar_url=user.avatar_url, name=user.name)
    await connection_manager.connect(
        ConnectedUser(user_id=user_id, connection=websocket, data=user_data))

    # populating blacklist cache only for online users
    await redis_blacklist.populate_blacklist(user_id, blacklist)

    # sending join event to all connected users
    logger.info(f"{user_id} connected from {websocket.client}")
    # TODO make it unified
    await connection_manager.broadcast(
        user_id, UserJoinEventPayload(
            user_id=user_id,
            name=user_data.name,
            avatar_url=user_data.avatar_url
        ).dict(by_alias=True))

    while True:
        try:
            raw_data: str = await websocket.receive_text()
            logger.info(f"Received data {raw_data} from {user_id}")
        except WebSocketDisconnect as e:
            logger.info(f"{user_id} disconnected with code {e.code}")
            await connection_manager.disconnect(user_id)
            # setting last_online field
            logger.info(f"Updating last_online on {user_id} "
                        f"and saving firebase cache")
            with dependencies.db_context(expire_on_commit=False) as session:
                session.add(user)
                # going offline, gotta save the token to cache
                await firebase_service.add_token_to_cache(
                    user_id, user.firebase_token)

                user.last_online = datetime.datetime.utcnow()
                session.commit()
            # adding him to recently online
            # such users are cleared every 10 minutes
            # check main server @startup events
            await redis_online.add_to_recently_online_cache(user)
            # removing all /fetch responses
            await redis_fetch.drop_fetch_response_caches(user_id)
            # removing blacklist cache
            await redis_blacklist.drop_blacklist_cache(user_id)
            # sending leave payloads to everyone
            payload = BasePayload(
                sender_id=UUID(hex=user_id),
                payload=GenericEventPayload(type=UserEventType.USER_LEFT))
            await connection_manager.broadcast(
                user_id, payload.dict(by_alias=True))
            return

        try:
            payload: BasePayload = BasePayload.validate(json.loads(raw_data))

            with dependencies.db_context() as session:
                request_processor = ChatServerRequestProcessor(session, redis)
                await request_processor.process(payload)

            if isinstance(payload.payload, CreateChatPayload):
                # we need to have a chat cache to speed up matchmaking queries
                # because we should not offer users who already got a chat
                # with the current user

                # only sender_id is added to recipient_id's chat cache
                # because recipient_id might be in the lobby
                # but sender_id is definitely NOT in the lobby
                await redis_chats.add_chat_partner(
                    str(payload.sender_id), str(payload.recipient_id))

            if isinstance(payload.payload, DeclineChatPayload):
                blocked_by_id = str(payload.sender_id)
                blocked_user_id = str(payload.recipient_id)

                logger.info(
                    f"Sending blacklist event from {blocked_by_id} "
                    f"to {blocked_user_id}")
                decline_payload = BasePayload(
                    sender_id=UUID(hex=blocked_by_id),
                    recipient_id=UUID(hex=blocked_user_id),
                    payload=GenericEventPayload(
                        type=UserEventType.USER_BLACKLISTED))
                await connection_manager.send(
                    blocked_user_id, decline_payload.dict(by_alias=True))

            if isinstance(payload.payload, GlobalMessagePayload):
                await connection_manager.broadcast(
                    str(payload.sender_id), payload.dict(
                        by_alias=True, exclude_unset=True))
            else:
                await _send_payload(payload)
        except:
            logger.exception(f"Error processing message: {raw_data}")


@app.post("/matchmaking/create_chat")
async def create_chat_from_matchmaking(
        payload: BasePayload = Body(...),
        db: Session = Depends(dependencies.db),
        redis: aioredis.Redis = Depends(dependencies.redis)):
    request_processor = ChatServerRequestProcessor(db, redis)
    if not isinstance(payload.payload, CreateChatPayload):
        # TODO refactor
        raise SwipeError("Unsupported payload")

    logger.info(f"Creating chat from matchmaking: {payload}")
    await request_processor.process(payload)

    out_payload = payload.dict(by_alias=True, exclude_unset=True)
    logger.info(f"Sending data to {payload.recipient_id}")
    await connection_manager.send(str(payload.recipient_id), out_payload)
    logger.info(f"Sending data to {payload.sender_id}")
    await connection_manager.send(str(payload.sender_id), out_payload)

    return Response()


@app.post("/events/blacklist")
async def send_blacklist_event(blocked_by_id: str = Body(..., embed=True),
                               blocked_user_id: str = Body(..., embed=True)):
    logger.info(f"Sending blacklist event "
                f"from {blocked_by_id} to {blocked_user_id}")
    payload = BasePayload(
        sender_id=UUID(hex=blocked_by_id),
        recipient_id=UUID(hex=blocked_user_id),
        payload=GenericEventPayload(type=UserEventType.USER_BLACKLISTED))
    await connection_manager.send(blocked_user_id, payload.dict(by_alias=True))


@app.post("/events/user_deleted")
async def send_user_deleted_event(
        user_id: str = Body(..., embed=True),
        recipients: list[str] = Body(..., embed=True)):
    logger.info(f"Sending user_deleted event for {user_id} to {recipients}")
    payload = BasePayload(
        sender_id=UUID(hex=user_id), payload=GenericEventPayload(
            type=UserEventType.USER_DELETED
        ))
    for recipient in recipients:
        await connection_manager.send(recipient, payload.dict(by_alias=True))


async def _send_payload(base_payload: BasePayload):
    recipient_id = str(base_payload.recipient_id)
    sender_id = str(base_payload.sender_id)
    payload = base_payload.payload
    # sending message/create_chat to offline users
    if not connection_manager.is_connected(recipient_id):
        if isinstance(payload, MessagePayload) \
                or isinstance(payload, CreateChatPayload):
            logger.info(
                f"{recipient_id} is offline, sending push "
                f"notification for '{payload.type_}' payload")

            firebase_service = RedisFirebaseService(dependencies.redis())

            on_cooldown = await firebase_service.is_on_cooldown(
                sender_id, recipient_id)
            if on_cooldown:
                logger.info(f"Notifications are in cooldown "
                            f"for {sender_id}->{recipient_id}")
                return

            firebase_token = \
                await firebase_service.get_firebase_token(recipient_id)
            if not firebase_token:
                logger.error(
                    f"User {recipient_id} does not have a firebase token "
                    f"which is weird")
                return

            sender_name = connection_manager.get_user_data(sender_id).name
            out_payload = {
                'sender_id': sender_id,
                'sender_name': sender_name,
                'type': payload.type_
            }
            logger.info(
                f"Sending firebase message payload {out_payload}"
                f"to {recipient_id}")
            # firebase.send(firebase.Message(
            #     data=out_payload, token=firebase_token))
            firebase.send(firebase.Message(
                notification=firebase.Notification(
                    title=f'{sender_name} считает, что всё хуйня',
                    body='Давай по новой!'),
                token=firebase_token
            ))

            await firebase_service.set_cooldown_token(sender_id, recipient_id)
    else:
        out_payload = base_payload.dict(by_alias=True, exclude_unset=True)
        await connection_manager.send(recipient_id, out_payload)


def start_server():
    app.add_exception_handler(SwipeError, error_handlers.swipe_error_handler)
    app.add_exception_handler(Exception, error_handlers.global_error_handler)
    server_config = Config(app=app, host='0.0.0.0',
                           port=settings.CHAT_SERVER_PORT,
                           reload=settings.ENABLE_WEB_SERVER_AUTORELOAD,
                           workers=1, loop='asyncio')
    server = Server(server_config)
    loop.run_until_complete(server.serve())
