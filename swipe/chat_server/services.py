from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import aioredis
from sqlalchemy.orm import Session
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
from swipe.swipe_server.users.services.services import UserService, \
    BlacklistService

logger = logging.getLogger(__name__)


class ChatServerRequestProcessor:
    def __init__(self, db: Session, redis: aioredis.Redis):
        self.chat_service = ChatService(db)
        self.user_service = UserService(db)
        self.blacklist_service = BlacklistService(db, redis)

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
                # it's a stub, because some devices might have
                # their local time fucked up
                timestamp=datetime.datetime.utcnow()
            )
        elif isinstance(payload, GlobalMessagePayload):
            self.chat_service.post_message_to_global(
                message_id=payload.message_id,
                sender_id=data.sender_id,
                message=payload.text,
                # it's a stub, because some devices might have
                # their local time fucked up
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
                        timestamp=data.timestamp,
                        is_liked=data.is_liked
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
            logger.info(f"Chat {payload.chat_id} was declined")

            await self.blacklist_service.update_blacklist(
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
    user_id: str
    name: str
    avatar_url: str


@dataclass
class MMUserData:
    age: int
    gender: Gender
    gender_filter: Optional[Gender] = None


class ConnectedUser:
    def __init__(self, user_id: str, connection: WebSocket,
                 data: Optional[ChatUserData | MMUserData] = None):
        self.connection = connection
        self.user_id = user_id
        self.data = data


class WSConnectionManager:
    active_connections: dict[str, ConnectedUser] = {}

    def get_user_data(self, user_id: str) \
            -> Optional[ChatUserData | MMUserData]:
        return self.active_connections[user_id].data \
            if user_id in self.active_connections else None

    async def connect(self, user: ConnectedUser):
        await user.connection.accept()
        self.active_connections[user.user_id] = user

    async def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    async def send(self, user_id: str, payload: dict):
        if user_id not in self.active_connections:
            logger.info(f"{user_id} is not online, payload won't be sent")
            return

        # TODO stupid workaround
        if 'payload' in payload:
            payload_type = payload['payload'].get('type', '???')
        else:
            payload_type = payload.get('type', '???')

        logger.info(f"Sending '{payload_type}' payload to {user_id}")
        # TODO use orjson instead of that dumb shit
        try:
            await self.active_connections[user_id].connection.send_text(
                json.dumps(payload, cls=PayloadEncoder))
        except:
            logger.exception(f"Unable to send '{payload_type}' to {user_id}")

    async def broadcast(self, sender_id: str, payload: dict):
        # TODO stupid workaround
        if 'payload' in payload:
            payload_type = payload['payload'].get('type', '???')
        else:
            payload_type = payload.get('type', '???')

        logger.info(f"Broadcasting '{payload_type}' event of {sender_id}")

        # it's required because another coroutine might change this dict
        user_ids = list(self.active_connections.keys())
        for user_id in user_ids:
            if user_id == sender_id:
                continue

            logger.info(f"Sending '{payload_type}' payload to {user_id}")
            try:
                if user := self.active_connections.get(user_id, None):
                    await user.connection.send_text(
                        json.dumps(payload, cls=PayloadEncoder))
            except:
                logger.exception(
                    f"Unable to send '{payload_type}' to {user_id}")

    def is_connected(self, user_id: str):
        return user_id in self.active_connections
