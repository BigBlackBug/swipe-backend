import datetime
import logging

from fastapi import Depends

from swipe.chat_server.schemas import BasePayload, MessagePayload, \
    GlobalMessagePayload, \
    MessageStatusPayload, MessageLikePayload, ChatMessagePayload, \
    AcceptChatPayload, OpenChatPayload, DeclineChatPayload, CreateChatPayload
from swipe.swipe_server.chats.models import MessageStatus, ChatSource, ChatStatus
from swipe.swipe_server.chats.services import ChatService
from swipe.swipe_server.misc.errors import SwipeError

logger = logging.getLogger(__name__)


class ChatServerRequestProcessor:
    def __init__(self, chat_service: ChatService = Depends()):
        self.chat_service = chat_service

    def process(self, data: BasePayload):
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
            # TODO add to blacklist
            self.chat_service.delete_chat(chat_id=payload.chat_id)
