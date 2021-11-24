from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from starlette.websockets import WebSocket

from swipe.chat_server.schemas import BasePayload, MessagePayload, \
    GlobalMessagePayload, \
    MessageStatusPayload, MessageLikePayload, ChatMessagePayload, \
    AcceptChatPayload, OpenChatPayload, DeclineChatPayload, CreateChatPayload
from swipe.swipe_server.chats.models import MessageStatus, ChatSource, \
    ChatStatus
from swipe.swipe_server.chats.services import ChatService
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.services import RedisUserService, UserService

logger = logging.getLogger(__name__)


class ChatServerRequestProcessor:
    def __init__(self, chat_service: ChatService,
                 user_service: UserService,
                 redis_service: RedisUserService):
        self.chat_service = chat_service
        self.user_service = user_service
        self.redis_service = redis_service

    async def process(self, data: BasePayload):
        payload = data.payload
        logger.info(f"Got payload with type '{payload.type_}' "
                    f"from {data.sender_id}, payload: {payload}")

        if isinstance(payload, MessagePayload):
            self.chat_service.post_message(
                message_id=payload.message_id,
                sender_id=data.sender_id,
                recipient_id=data.recipient_id,
                message=payload.text,
                image_id=payload.image_id,
                timestamp=payload.timestamp
            )
        elif isinstance(payload, GlobalMessagePayload):
            self.chat_service.post_message_to_global(
                message_id=payload.message_id,
                sender_id=data.sender_id,
                message=payload.text,
                timestamp=payload.timestamp
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
            try:
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
            except:
                # TODO this should not be possible in the first place
                self.chat_service.db.rollback()
                logger.exception(
                    f"Error creating chat between {payload.chat_id} "
                    f"and {data.recipient_id}")

        elif isinstance(payload, AcceptChatPayload):
            self.chat_service.update_chat_status(
                payload.chat_id, status=ChatStatus.ACCEPTED)
        elif isinstance(payload, OpenChatPayload):
            self.chat_service.update_chat_status(
                payload.chat_id, status=ChatStatus.OPENED)
        elif isinstance(payload, DeclineChatPayload):
            self.chat_service.delete_chat(chat_id=payload.chat_id)
            logger.info(
                f"Chat {payload.chat_id} was declined, "
                f"adding both {data.sender_id} and {data.recipient_id}"
                f"to each others blacklist")
            self.user_service.update_blacklist(
                str(data.sender_id), str(data.recipient_id))
            await self.redis_service.add_to_blacklist(
                str(data.sender_id), str(data.recipient_id))


class PayloadEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, datetime.datetime):
            return str(obj)
        elif isinstance(obj, bytes):
            # avatars are b64 encoded byte strings
            return obj.decode('utf-8')
        return json.JSONEncoder.default(self, obj)


@dataclass
class ChatUserData:
    name: str
    avatar_url: str


@dataclass
class MMUserData:
    age: int
    gender: Gender
    gender_filter: Optional[Gender] = None


class ConnectedUser:
    def __init__(self, user_id: str, connection: WebSocket,
                 data: ChatUserData | MMUserData):
        self.connection = connection
        self.user_id = user_id
        self.data = data


class WSConnectionManager:
    active_connections: dict[str, ConnectedUser] = {}

    async def connect(self, user: ConnectedUser):
        await user.connection.accept()
        self.active_connections[user.user_id] = user

    async def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    async def send(self, user_id: str, payload: dict):
        logger.info(f"Sending payload {payload} to {user_id}")
        if user_id not in self.active_connections:
            logger.info(f"{user_id} is not online, payload won't be sent")
            return

        await self.active_connections[user_id].connection.send_text(
            json.dumps(payload, cls=PayloadEncoder))

    async def broadcast(self, sender_id: str, payload: dict):
        for user_id, user in self.active_connections.items():
            if user_id == sender_id:
                continue
            logger.info(f"Sending payload to {user_id}")
            await user.connection.send_text(
                json.dumps(payload, cls=PayloadEncoder))

    def is_connected(self, user_id: str):
        return user_id in self.active_connections
