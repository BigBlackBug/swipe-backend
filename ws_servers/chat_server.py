import base64

import config

config.configure_logging()

import json
import logging
from uuid import UUID

import uvicorn
from fastapi import FastAPI, Depends, Body
from fastapi import WebSocket
from pydantic import BaseModel
from starlette.datastructures import Address
from starlette.websockets import WebSocketDisconnect

from swipe.users.services import UserService, RedisUserService
from ws_servers.schemas import BasePayload, GlobalMessagePayload
from ws_servers.services import WSChatRequestProcessor, WSConnectionManager, \
    ConnectedUser

logger = logging.getLogger(__name__)

app = FastAPI()

_supported_payloads = []
for cls in BaseModel.__subclasses__():
    if cls.__name__.endswith('Payload') and 'type_' in cls.__fields__:
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


@app.websocket("/connect/{user_id}")
async def websocket_endpoint(
        user_id: UUID,
        websocket: WebSocket,
        connection_manager: WSConnectionManager = Depends(),
        user_service: UserService = Depends(),
        redis_service: RedisUserService = Depends(),
        request_processor: WSChatRequestProcessor = Depends()):
    if (user := user_service.get_global_chat_preview_one(user_id)) is None:
        logger.info(f"User {user_id} not found")
        await websocket.close(1003)
        return

    # TODO that's bad, no indices
    avatar = user[2]
    if avatar:
        avatar = base64.b64encode(avatar)
    user = ConnectedUser(id=user_id, name=user[1],
                         avatar=avatar, websocket=websocket)

    await connection_manager.connect(user)
    await redis_service.refresh_online_status(user_id)

    address: Address = websocket.client

    logger.info(f"{user_id} connected from {address}")
    while True:
        try:
            data = await websocket.receive_text()
            logger.info(f"Received data {data} from {user_id}")
        except WebSocketDisconnect as e:
            logger.exception(f"{user_id} disconnected with code {e.code}")
            await connection_manager.disconnect(user_id)
            await redis_service.remove_online_user(user_id)
            break

        payload: BasePayload = BasePayload.validate(json.loads(data))
        logger.info(f"Payload type: {payload.payload.type_}")

        request_processor.process(payload)
        if isinstance(payload.payload, GlobalMessagePayload):
            output_data = payload.payload.dict(by_alias=True)
            output_data['name'] = user.name
            output_data['avatar'] = user.avatar
            await connection_manager.broadcast(payload.sender_id, output_data)
        else:
            await connection_manager.send(
                payload.recipient_id, payload.payload.dict(by_alias=True))


if __name__ == '__main__':
    uvicorn.run('chat_server:app', host='0.0.0.0',  # noqa
                port=16000, workers=1)
