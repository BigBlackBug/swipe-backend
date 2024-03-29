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
from starlette import status
from starlette.responses import Response
from starlette.websockets import WebSocketDisconnect
from uvicorn import Server, Config

from swipe import error_handlers
from swipe.chat_server.schemas import BasePayload, GlobalMessagePayload, \
    MessagePayload, CreateChatPayload, \
    UserJoinEventPayload, GenericEventPayload, UserEventType, \
    DeclineChatPayload, MessageLikePayload, RatingChangedEventPayload, \
    OutPayload, AckPayload, AckType, AcceptChatPayload
from swipe.chat_server.services import ChatServerRequestProcessor
from swipe.middlewares import CorrelationIdMiddleware
from swipe.settings import settings
from swipe.swipe_server.chats.services import ChatService
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.services.online_cache import \
    RedisOnlineUserService
from swipe.swipe_server.users.services.redis_services import \
    RedisBlacklistService, RedisChatCacheService, \
    RedisFirebaseService, RedisUserFetchService
from swipe.swipe_server.users.services.user_service import UserService
from swipe.ws_connection import ChatUserData, ConnectedUser, WSConnectionManager

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


loop = asyncio.get_event_loop()

connection_manager = WSConnectionManager()

redis_client = dependencies.redis()
firebase_service = RedisFirebaseService(redis_client)
redis_online = RedisOnlineUserService(redis_client)
redis_blacklist = RedisBlacklistService(redis_client)
redis_chats = RedisChatCacheService(redis_client)
redis_fetch = RedisUserFetchService(redis_client)


@app.websocket("/connect/{user_id}")
async def websocket_endpoint(
        user_id: str,
        websocket: WebSocket,
        redis: aioredis.Redis = Depends(dependencies.redis)):
    user: User
    try:
        user = await _init_user(user_id, websocket)
        logger.info(f"{user_id} connected from {websocket.client}")
    except:
        logger.exception(f"Error connecting user {user_id}")
        await websocket.close(1003)
        return

    while True:
        try:
            raw_data: str = await websocket.receive_text()
            logger.info(f"Received data {raw_data} from {user_id}")
        except WebSocketDisconnect as e:
            logger.info(f"{user_id} disconnected with code {e.code}")
            await _process_disconnect(user)
            return

        try:
            base_payload = BasePayload.validate(json.loads(raw_data))
        except:
            logger.exception(f"Invalid message: {raw_data}")
            continue

        logger.info(f"request_id={base_payload.request_id} successfully acked, "
                    f"processing payload")
        try:
            with dependencies.db_context() as session:
                request_processor = \
                    ChatServerRequestProcessor(session, redis)
                await request_processor.process(base_payload)
        except:
            logger.exception(f"Error processing payload {base_payload}")
            await _send_ack(base_payload, success=False)
            continue
        else:
            await _send_ack(base_payload)

        try:
            await _send_response_to_recipient(base_payload)
        except:
            logger.exception(
                f"Error delivering payload to {base_payload.recipient_id}")


async def _send_response_to_recipient(base_payload: BasePayload):
    if isinstance(base_payload.payload, DeclineChatPayload):
        await _send_blacklist_events(
            blocked_user_id=str(base_payload.recipient_id),
            blocked_by_id=str(base_payload.sender_id))

    if isinstance(base_payload.payload, GlobalMessagePayload):
        await connection_manager.broadcast(
            str(base_payload.sender_id), base_payload.dict(
                by_alias=True, exclude_unset=True))
    else:
        recipient_id = str(base_payload.recipient_id)
        # offline users receive a notification instead
        if not connection_manager.is_connected(recipient_id):
            await _send_firebase_notification(base_payload)
        else:
            out_payload = base_payload.dict(by_alias=True,
                                            exclude_unset=True)
            await connection_manager.send(recipient_id, out_payload)


async def _send_ack(payload: BasePayload, success: bool = True):
    if not payload.request_id:
        return

    try:
        logger.info(
            f"Sending ack={success} payload to request_id={payload.request_id}")
        out_payload = OutPayload(payload=AckPayload(
            type=AckType.ACK if success else AckType.ACK_FAILED,
            request_id=payload.request_id,
            timestamp=datetime.datetime.utcnow(),
        ))
        await connection_manager.send(
            str(payload.sender_id), out_payload.dict(by_alias=True),
            raise_on_disconnect=True)
    except:
        logger.exception(
            f"Unable to send ack payload to {payload.sender_id},"
            f"request={payload.request_id}")


async def _init_user(user_id, websocket: WebSocket) -> User:
    try:
        user_uuid = UUID(hex=user_id)
    except ValueError:
        raise SwipeError(f"Invalid user id: {user_id}")

    user: User
    with dependencies.db_context(expire_on_commit=False) as session:
        user_service, chat_service = UserService(session), ChatService(session)
        # loading only required fields
        if user := user_service.get_user_card_preview(user_uuid):
            user.last_online = None
            session.commit()
        else:
            raise SwipeError(f"User {user_id} not found")

        blacklist: set[str] = await user_service.fetch_blacklist(user_id)
        logger.info(f"Blacklist of {user_id}: {blacklist}")

        partner_ids: list[str] = chat_service.get_chat_partners(user_id)
        logger.info(f"Chat partners of {user_id}: {partner_ids}")

    # we're online so we don't need a token in cache
    await firebase_service.remove_token_from_cache(user_id)
    # gender, dob, location, name, firebase_token, avatar_id + avatar_url
    await redis_online.add_to_online_caches(user)
    # they may have returned before the cache is dropped
    await redis_online.remove_from_recently_online(user_id)
    # populating blacklist cache only for online users
    await redis_blacklist.populate_blacklist(user_id, blacklist)
    # we're gonna need it in /fetch
    await redis_chats.populate_chat_partner_cache(user_id, partner_ids)

    user_data = ChatUserData(
        user_id=user_id, avatar_url=user.avatar_url,
        name=user.name, gender=user.gender)
    await connection_manager.connect(
        ConnectedUser(user_id=user_id, connection=websocket, data=user_data))

    # TODO make it unified
    await connection_manager.broadcast(
        user_id, UserJoinEventPayload(
            user_id=user_id,
            name=user_data.name,
            avatar_url=user_data.avatar_url
        ).dict(by_alias=True))

    return user


async def _process_disconnect(user: User):
    user_id = str(user.id)

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
    await redis_fetch.drop_response_cache(user_id)
    # removing blacklist cache
    await redis_blacklist.drop_blacklist_cache(user_id)
    # dropping chat cache
    await redis_chats.drop_chat_partner_cache(user_id)
    # sending leave payloads to everyone
    await connection_manager.broadcast(
        user_id, BasePayload(
            sender_id=UUID(hex=user_id),
            payload=GenericEventPayload(type=UserEventType.USER_LEFT)
        ).dict(by_alias=True))


async def _send_firebase_notification(base_payload: BasePayload):
    recipient_id = str(base_payload.recipient_id)
    sender_id = str(base_payload.sender_id)
    payload = base_payload.payload

    if type(payload) \
            not in {MessagePayload, CreateChatPayload, AcceptChatPayload}:
        return

    logger.info(
        f"{recipient_id} is offline, sending push "
        f"notification for '{payload.type_}' payload")

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

    user_data: ChatUserData = connection_manager.get_user_data(sender_id)
    # TODO should move that to the Gender enum
    if user_data.gender == Gender.MALE:
        ending = ''
    elif user_data.gender == Gender.FEMALE:
        ending = 'а'
    elif user_data.gender == Gender.ATTACK_HELICOPTER:
        # sorry not sorry
        ending = 'о'

    if isinstance(payload, MessagePayload):
        notification = firebase.Notification(
            title=f'Dombo',
            body=f'{user_data.name} написал{ending} вам сообщение 💬💬💬')  # noqa
    elif isinstance(payload, CreateChatPayload):
        notification = firebase.Notification(
            title=f'Dombo',
            body='У вас новый запрос на переписку 👋👋👋')
    elif isinstance(payload, AcceptChatPayload):
        notification = firebase.Notification(
            title=f'Dombo',
            body=f'{user_data.name} принял{ending} запрос на переписку 😉😉😉')  # noqa

    logger.info(
        f"Sending firebase notification '{payload.type_}' "
        f"to {recipient_id}")
    firebase.send(firebase.Message(
        notification=notification, token=firebase_token))  # noqa

    await firebase_service.set_cooldown_token(sender_id, recipient_id)


@app.post("/matchmaking/chat")
async def matchmaking_chat_handler(
        payload: BasePayload = Body(...),
        db: Session = Depends(dependencies.db),
        redis: aioredis.Redis = Depends(dependencies.redis)):
    request_processor = ChatServerRequestProcessor(db, redis)
    if not type(payload.payload) in [
        CreateChatPayload, MessagePayload, MessageLikePayload
    ]:
        raise SwipeError(f"Unsupported payload {payload.payload.type_}")

    await request_processor.process(payload)

    out_payload = payload.dict(by_alias=True, exclude_unset=True)

    # chat host
    logger.info(f"Sending data to {payload.sender_id}")
    await connection_manager.send(str(payload.sender_id), out_payload)

    # chat partner
    logger.info(f"Sending data to {payload.recipient_id}")
    await connection_manager.send(str(payload.recipient_id), out_payload)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/events/blacklist")
async def send_blacklist_event(blocked_by_id: str = Body(..., embed=True),
                               blocked_user_id: str = Body(..., embed=True)):
    await _send_blacklist_events(blocked_user_id, blocked_by_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/events/user_deleted")
async def send_user_deleted_event(
        user_id: str = Body(..., embed=True),
        recipients: list[str] = Body(None, embed=True)):
    logger.info(f"Sending user_deleted event of {user_id} to "
                f"{recipients or 'everyone'}")
    payload = BasePayload(
        sender_id=UUID(hex=user_id), payload=GenericEventPayload(
            type=UserEventType.USER_DELETED
        ))
    if recipients is None:
        await connection_manager.broadcast(user_id, payload.dict(by_alias=True))
    else:
        for recipient in recipients:
            await connection_manager.send(
                recipient, payload.dict(by_alias=True))

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/events/rating_changed")
async def send_rating_changed_event(
        user_id: str = Body(..., embed=True),
        sender_id: str = Body(..., embed=True),
        rating: int = Body(..., embed=True)):
    logger.info(f"Sending rating_changed event for {user_id}, "
                f"new rating: {rating}")
    payload = BasePayload(
        sender_id=UUID(hex=sender_id),
        recipient_id=UUID(hex=user_id),
        payload=RatingChangedEventPayload(
            user_id=user_id, rating=rating
        ))
    await connection_manager.send(user_id, payload.dict(by_alias=True))

    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _send_blacklist_events(blocked_user_id: str, blocked_by_id: str):
    logger.info(
        f"Sending blacklisted event from {blocked_by_id} "
        f"to {blocked_user_id}")
    blacklist_payload = BasePayload(
        sender_id=UUID(hex=blocked_by_id),
        recipient_id=UUID(hex=blocked_user_id),
        payload=GenericEventPayload(
            type=UserEventType.USER_BLACKLISTED))
    await connection_manager.send(
        blocked_user_id, blacklist_payload.dict(by_alias=True))

    logger.info(
        f"Sending blacklisted event from {blocked_user_id} "
        f"to {blocked_by_id}")
    blacklist_payload = BasePayload(
        sender_id=UUID(hex=blocked_user_id),
        recipient_id=UUID(hex=blocked_by_id),
        payload=GenericEventPayload(
            type=UserEventType.USER_BLACKLISTED))
    await connection_manager.send(
        blocked_by_id, blacklist_payload.dict(by_alias=True))


def start_server():
    app.add_exception_handler(SwipeError, error_handlers.swipe_error_handler)
    app.add_exception_handler(Exception, error_handlers.global_error_handler)
    app.add_middleware(CorrelationIdMiddleware)
    server_config = Config(app=app, host='0.0.0.0',
                           port=80,
                           reload=settings.ENABLE_WEB_SERVER_AUTORELOAD,
                           workers=1, loop='asyncio')
    server = Server(server_config)
    loop.run_until_complete(server.serve())
