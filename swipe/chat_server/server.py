import asyncio
import json
import logging
from uuid import UUID

from fastapi import FastAPI, Depends, Body
from fastapi import WebSocket
from firebase_admin import messaging as firebase
from pydantic import BaseModel
from starlette.responses import Response
from starlette.websockets import WebSocketDisconnect
from uvicorn import Server, Config

from swipe import error_handlers
from swipe.chat_server.schemas import BasePayload, GlobalMessagePayload, \
    MessagePayload, CreateChatPayload
from swipe.chat_server.services import ChatServerRequestProcessor, \
    WSConnectionManager, ConnectedUser, ChatUserData
from swipe.settings import settings
from swipe.swipe_server.chats.services import ChatService
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.users.schemas import UserOutGlobalChatPreviewORM
from swipe.swipe_server.users.services import UserService, RedisUserService

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
        user_service: UserService = Depends(),
        chat_service: ChatService = Depends(),
        redis_service: RedisUserService = Depends()):
    try:
        user_uuid = UUID(hex=user_id)
    except ValueError:
        logger.exception(f"Invalid user id: {user_id}")
        await websocket.close(1003)
        return

    if (user := user_service.get_global_chat_preview_one(user_uuid)) is None:
        logger.info(f"User {user_id} not found")
        await websocket.close(1003)
        return

    user = UserOutGlobalChatPreviewORM.patched_from_orm(user)
    user = ConnectedUser(
        user_id=user_id, connection=websocket,
        data=ChatUserData(name=user.name, avatar_url=user.avatar_url))

    await connection_manager.connect(user)
    await redis_service.connect_user(user_uuid)
    blacklist:set[str] = user_service.fetch_blacklist(user_id)
    await redis_service.populate_blacklist(user_id, blacklist)

    logger.info(f"{user_id} connected from {websocket.client}, "
                f"sending join event")
    await connection_manager.broadcast(
        user_id, {
            'type': 'join',
            'user_id': user.user_id,
            'name': user.data.name,
            'avatar_url': user.data.avatar_url
        })

    request_processor = ChatServerRequestProcessor(chat_service, redis_service)
    while True:
        try:
            raw_data: str = await websocket.receive_text()
            logger.info(f"Received data {raw_data} from {user_id}")
        except WebSocketDisconnect as e:
            logger.exception(f"{user_id} disconnected with code {e.code}")
            await connection_manager.disconnect(user_id)
            await redis_service.disconnect_user(user_uuid)
            break

        try:
            payload: BasePayload = BasePayload.validate(json.loads(raw_data))
            logger.info(f"Payload type: {payload.payload.type_}")

            await request_processor.process(payload)
            if isinstance(payload.payload, GlobalMessagePayload):
                await connection_manager.broadcast(
                    str(payload.sender_id), payload.dict(
                        by_alias=True, exclude_unset=True))
            else:
                await _send_payload(payload, user_service)
        except:
            logger.exception(f"Error processing message: {raw_data}")


@app.post("/matchmaking/create_chat")
async def create_chat_from_matchmaking(
        payload: BasePayload = Body(...),
        chat_service: ChatService = Depends(),
        redis_service: RedisUserService = Depends()):
    request_processor = ChatServerRequestProcessor(chat_service, redis_service)
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


async def _send_payload(payload: BasePayload, user_service: UserService):
    recipient_id = payload.recipient_id
    out_payload = payload.dict(by_alias=True, exclude_unset=True)

    # sending message/create_chat to offline users
    if not connection_manager.is_connected(str(recipient_id)):
        if isinstance(payload.payload, MessagePayload) \
                or isinstance(payload.payload, CreateChatPayload):
            logger.info(
                f"{recipient_id} is offline, sending push "
                f"notification for '{payload.payload.type_}' payload")
            # TODO cache token
            firebase_token = user_service.get_firebase_token(recipient_id)
            if not firebase_token:
                logger.error(
                    f"User {recipient_id} does not have a firebase token "
                    f"which is weird")
                return

            firebase.send(firebase.Message(
                data=out_payload, token=firebase_token))
    else:
        await connection_manager.send(str(recipient_id), out_payload)


def start_server():
    app.add_exception_handler(SwipeError, error_handlers.swipe_error_handler)
    app.add_exception_handler(Exception, error_handlers.global_error_handler)
    server_config = Config(app=app, host='0.0.0.0',
                           port=settings.CHAT_SERVER_PORT,
                           workers=1, loop='asyncio')
    server = Server(server_config)
    loop.run_until_complete(server.serve())
