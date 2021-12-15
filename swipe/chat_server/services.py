from __future__ import annotations

import datetime
import logging

import aioredis
from sqlalchemy.orm import Session

from swipe.chat_server.schemas import BasePayload, MessagePayload, \
    GlobalMessagePayload, \
    MessageStatusPayload, MessageLikePayload, ChatMessagePayload, \
    AcceptChatPayload, OpenChatPayload, DeclineChatPayload, CreateChatPayload
from swipe.swipe_server.chats.models import MessageStatus, ChatSource, \
    ChatStatus
from swipe.swipe_server.chats.services import ChatService
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.users.services.redis_services import \
    RedisChatCacheService
from swipe.swipe_server.users.services.services import UserService, \
    BlacklistService

logger = logging.getLogger(__name__)


class ChatServerRequestProcessor:
    def __init__(self, db: Session, redis: aioredis.Redis):
        self.chat_service = ChatService(db)
        self.user_service = UserService(db)
        self.blacklist_service = BlacklistService(db, redis)
        self.redis_chats = RedisChatCacheService(redis)

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

            # we need to have a chat cache to speed up matchmaking queries
            # because we should not offer users who already got a chat
            # with the current user

            sender_id = str(data.sender_id)
            recipient_id = str(data.recipient_id)

            await self.redis_chats.add_chat_partner(sender_id, recipient_id)
            await self.redis_chats.add_chat_partner(recipient_id, sender_id)

        elif isinstance(payload, AcceptChatPayload):
            self.chat_service.update_chat_status(
                payload.chat_id, status=ChatStatus.ACCEPTED)
        elif isinstance(payload, OpenChatPayload):
            self.chat_service.update_chat_status(
                payload.chat_id, status=ChatStatus.OPENED)
        elif isinstance(payload, DeclineChatPayload):
            self.chat_service.delete_chat(chat_id=payload.chat_id)

            sender_id = str(data.sender_id)
            recipient_id = str(data.recipient_id)
            await self.blacklist_service.update_blacklist(
                sender_id, recipient_id)

            await self.redis_chats.remove_chat_partner(sender_id, recipient_id)
            await self.redis_chats.remove_chat_partner(recipient_id, sender_id)
