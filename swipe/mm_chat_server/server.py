import asyncio
import datetime
import logging
import uuid
from collections import namedtuple
from dataclasses import dataclass, field

import requests
from fastapi import FastAPI, Query
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from uvicorn import Config, Server

from swipe.chat_server.services import ConnectedUser, WSConnectionManager
from swipe.matchmaking.schemas import MMRoundData
from swipe.mm_chat_server.schemas import MMTextBasePayload, \
    MMTextMessagePayload, MMTextChatPayload, MMTextMessageLikePayload, \
    MMTextChatAction, MMTextMessageModel
from swipe.settings import settings
from swipe.swipe_server.chats.models import ChatSource
from swipe.swipe_server.misc.errors import SwipeError

logger = logging.getLogger(__name__)

app = FastAPI()

loop = asyncio.get_event_loop()
matchmaking_data = MMRoundData()
connection_manager = WSConnectionManager()

ChatTuple = namedtuple('ChatTuple', ['the_other_person_id', 'chat_id'])
CHAT_SERVER_URL = f'{settings.CHAT_SERVER_HOST}/matchmaking/chat'


@dataclass
class TemporaryChat:
    saved: bool = False
    messages: list[MMTextMessageModel] = field(default_factory=list)


# user -> chat_id
current_clients: dict[str, ChatTuple] = dict()
# chat_id -> messages
current_chats: dict[str, TemporaryChat] = dict()


@app.websocket("/connect/{user_id}")
async def matchmaker_endpoint(
        user_id: str,
        websocket: WebSocket,
        the_other_person_id: str = Query(None)):
    logger.info(f"{user_id} connected, "
                f"the_other_person_id: {the_other_person_id}")

    connected_user = ConnectedUser(
        user_id=user_id, connection=websocket)
    await connection_manager.connect(connected_user)

    # host comes in first
    if the_other_person_id not in current_clients:
        logger.info(f"{user_id} connected first, creating empty chat")
        chat_id = str(uuid.uuid4())
        current_clients[user_id] = ChatTuple(
            the_other_person_id=the_other_person_id, chat_id=chat_id)
        current_clients[the_other_person_id] = ChatTuple(
            the_other_person_id=user_id, chat_id=chat_id)
        current_chats[chat_id] = TemporaryChat()
    else:
        # the other dude joins
        chat_id = current_clients[user_id].chat_id
        logger.info(f"{the_other_person_id} joined to {user_id}, "
                    f"chat_id: {chat_id}")
        # sending connected to both
        await connection_manager.send(
            current_clients[user_id].the_other_person_id, {
                'status': 'partner_connected'
            })
        await connection_manager.send(
            user_id, {
                'status': 'partner_connected'
            })

    while True:
        try:
            data: dict = await websocket.receive_json()
            logger.info(f"Received data {data} from {user_id}")
        except WebSocketDisconnect as e:
            logger.info(f"{user_id} disconnected with code {e.code}")
            if the_other_person_id in current_clients:
                logger.info("Sending disconnect event to his partner")
                await connection_manager.send(
                    the_other_person_id, {
                        'status': 'partner_disconnected'
                    })

            logger.info(
                f"Deleting clients {user_id} and {the_other_person_id} and "
                f"their new chat {chat_id}")
            current_clients.pop(user_id, None)
            current_clients.pop(the_other_person_id, None)
            current_chats.pop(chat_id, None)
            return

        try:
            base_payload: MMTextBasePayload = MMTextBasePayload.validate(data)
            await _process_payload(base_payload, chat_id)

            await connection_manager.send(
                base_payload.recipient_id,
                base_payload.dict(by_alias=True, exclude_unset=True))
        except:
            logger.exception(f"Error processing payload from {user_id}")


async def _process_payload(base_payload: MMTextBasePayload, chat_id: str):
    payload = base_payload.payload
    sender_id = base_payload.sender_id
    recipient_id = base_payload.recipient_id

    if (chat := current_chats.get(chat_id)) is None:
        raise SwipeError(
            f"No chat exists between {sender_id} and {recipient_id}")

    logger.info(f"Got payload {payload} from {sender_id}")

    if isinstance(payload, MMTextMessagePayload):
        if chat.saved:
            logger.info(f"Chat {chat_id} is already saved to db, "
                        f"sending {payload} payload to chat server")
            # yeah they are reversed
            output_payload = {
                'sender_id': base_payload.recipient_id,
                'recipient_id': base_payload.sender_id,
                'payload': {
                    'type': 'message',
                    'message_id': payload.message_id,
                    'timestamp': datetime.datetime.utcnow().isoformat(),
                    'text': payload.text
                }
            }
            # TODO use aiohttp?
            requests.post(CHAT_SERVER_URL, json=output_payload)
        else:
            chat.messages.append(MMTextMessageModel(
                sender_id=sender_id,
                recipient_id=recipient_id,
                message_id=payload.message_id,
                timestamp=datetime.datetime.utcnow().isoformat(),
                text=payload.text
            ))
    elif isinstance(payload, MMTextMessageLikePayload):
        if chat.saved:
            logger.info(f"Chat {chat_id} is already saved to db, "
                        f"sending {payload} payload to chat server")
            # yeah they are reversed
            output_payload = {
                'sender_id': base_payload.recipient_id,
                'recipient_id': base_payload.sender_id,
                'payload': {
                    'type': 'like',
                    'like': payload.like,
                    'message_id': payload.message_id,
                }
            }
            # TODO use aiohttp?
            requests.post(CHAT_SERVER_URL, json=output_payload)
        else:
            message: MMTextMessagePayload
            for message in chat.messages:
                if message.message_id == payload.message_id:
                    logger.info(f"Setting like:{payload.like} "
                                f"on {payload.message_id}")
                    message.is_liked = payload.like
    elif isinstance(payload, MMTextChatPayload):
        if payload.action == MMTextChatAction.ACCEPT:
            chat.saved = True

            logger.info(
                f"{sender_id} has accepted chat request from {recipient_id}, "
                f"sending request to chat server")
            # yeah they are reversed
            output_payload = {
                'sender_id': base_payload.recipient_id,
                'recipient_id': base_payload.sender_id,
                'payload': {
                    'type': 'create_chat',
                    'source': ChatSource.TEXT_LOBBY.value,
                    'chat_id': chat_id,
                    'messages': [
                        message.dict() for message in chat.messages
                    ]
                }
            }
            # TODO use aiohttp?
            requests.post(CHAT_SERVER_URL, json=output_payload)


def start_server():
    server_config = Config(app=app, host='0.0.0.0',
                           port=settings.MATCHMAKING_TEXT_CHAT_SERVER_PORT,
                           workers=1, loop='asyncio')
    server = Server(server_config)
    loop.run_until_complete(server.serve())
