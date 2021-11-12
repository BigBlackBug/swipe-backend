import datetime
import json
import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends
from starlette.websockets import WebSocket

from swipe.chats.models import MessageStatus, ChatSource, ChatStatus
from swipe.chats.services import ChatService
from swipe.errors import SwipeError
from ws_servers.schemas import BasePayload, MessagePayload, \
    GlobalMessagePayload, \
    MessageStatusPayload, MessageLikePayload, ChatMessagePayload, \
    AcceptChatPayload, OpenChatPayload, DeclineChatPayload, CreateChatPayload

logger = logging.getLogger(__name__)


class UUIDEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        return json.JSONEncoder.default(self, obj)


@dataclass
class ConnectedUser:
    id: UUID
    name: str
    avatar: bytes
    websocket: WebSocket


class WSConnectionManager:
    active_connections: dict[UUID, ConnectedUser] = {}

    async def connect(self, user: ConnectedUser):
        await user.websocket.accept()
        self.active_connections[user.id] = user

    async def disconnect(self, user_id: UUID):
        del self.active_connections[user_id]

    async def send(self, user_id: UUID, payload: dict):
        logger.info(f"Sending payload to {user_id}")
        await self.active_connections[user_id].websocket.send_text(
            json.dumps(payload, cls=UUIDEncoder))

    async def broadcast(self, sender_id: UUID, payload: dict):
        for user_id, user in self.active_connections.items():
            if user_id == sender_id:
                continue
            logger.info(f"Sending payload to {user_id}")
            await user.websocket.send_text(json.dumps(payload, cls=UUIDEncoder))


class WSChatRequestProcessor:
    def __init__(self, chat_service: ChatService = Depends()):
        self.chat_service = chat_service

    def process(self, data: BasePayload):
        payload = data.payload
        logger.info(f"Got payload with type '{payload.type_}' "
                    f"from {data.sender_id}, payload:{payload}")

        if isinstance(payload, MessagePayload):
            self.chat_service.post_message(
                message_id=payload.message_id,
                sender_id=data.sender_id,
                recipient_id=data.recipient_id,
                message=payload.text,
                image_id=payload.image_id,
                timestamp=datetime.datetime.utcnow()
            )
        elif isinstance(payload, GlobalMessagePayload):
            self.chat_service.post_message_to_global(
                message_id=payload.message_id,
                sender_id=data.sender_id,
                message=payload.text,
                timestamp=datetime.datetime.utcnow()
            )
        elif isinstance(payload, MessageStatusPayload):
            message_status = MessageStatus.__members__[payload.status.upper()]
            if message_status == MessageStatus.RECEIVED:
                self.chat_service.set_received_status(payload.message_id)
            elif message_status == MessageStatus.READ:
                self.chat_service.set_read_status(payload.message_id)
        elif isinstance(payload, MessageLikePayload):
            self.chat_service.set_like_status(payload.message_id, payload.like)
        elif isinstance(payload, CreateChatPayload):
            source = ChatSource.__members__[payload.source.upper()]
            # video/audio lobby chats start empty
            messages = []
            # audio/video/text lobby chats are created as accepted
            chat_status = ChatStatus.ACCEPTED
            if source == ChatSource.DIRECT:
                # direct chats go to requested
                # direct chats start with one message
                chat_status = ChatStatus.REQUESTED
                if not payload.message:
                    raise SwipeError(
                        "Direct chat payload must include 'message' field")
                messages = [payload.message]
            elif source == ChatSource.TEXT_LOBBY:
                # text lobby chats start with a shitload of messages
                if not payload.messages:
                    raise SwipeError(
                        "Text lobby chat payload must include 'messages' field")
                messages = payload.messages

            # if a second user tries to accept a text lobby chat
            # before he receives an event, the method will raise SwipeError
            self.chat_service.create_chat(
                chat_id=payload.chat_id,
                initiator_id=data.sender_id,
                the_other_person_id=data.recipient_id,
                chat_status=chat_status,
                source=source)
            data: ChatMessagePayload
            for data in messages:
                self.chat_service.post_message(
                    message_id=data.message_id,
                    sender_id=data.sender_id,
                    recipient_id=data.recipient_id,
                    message=data.text,
                    image_id=data.image_id,
                    timestamp=data.timestamp
                )

        elif isinstance(payload, AcceptChatPayload):
            self.chat_service.update_chat_status(
                payload.chat_id, status=ChatStatus.ACCEPTED)
        elif isinstance(payload, OpenChatPayload):
            self.chat_service.update_chat_status(
                payload.chat_id, status=ChatStatus.OPENED)
        elif isinstance(payload, DeclineChatPayload):
            self.chat_service.delete_chat(chat_id=payload.chat_id)
