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

from swipe.users.services import UserService
from ws_servers.schemas import BasePayload, GlobalMessagePayload
from ws_servers.services import WSChatRequestProcessor, WSConnectionManager

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
            'timestamp': 'iso formatted utc timestamp',
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
        request_processor: WSChatRequestProcessor = Depends()):
    if not user_service.get_user(user_id):
        logger.info(f"User {user_id} not found")
        await websocket.close(1003)
        return

    await connection_manager.connect(user_id, websocket)
    address: Address = websocket.client

    logger.info(f"{user_id} connected from {address}")
    while True:
        try:
            data = await websocket.receive_text()
            logger.info(f"Received data {data} from {user_id}")
        except WebSocketDisconnect as e:
            logger.exception(f"{user_id} disconnected with code {e.code}")
            await connection_manager.disconnect(user_id)
            break

        payload: BasePayload = BasePayload.validate(json.loads(data))
        logger.info(f"Payload type: {payload.payload.type_}")

        request_processor.process(payload)
        if isinstance(payload.payload, GlobalMessagePayload):
            await connection_manager.broadcast(payload.sender_id,
                                               payload.payload.dict(
                                                   by_alias=True))
        else:
            await connection_manager.send(payload.recipient_id,
                                          payload.payload.dict(by_alias=True))


if __name__ == '__main__':
    uvicorn.run('chat_server:app', host='0.0.0.0',  # noqa
                port=16000, workers=1)
