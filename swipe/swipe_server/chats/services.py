import datetime
import logging
from typing import Optional
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session, selectinload, contains_eager

from swipe.swipe_server.chats.models import Chat, ChatStatus, ChatMessage, \
    MessageStatus, \
    GlobalChatMessage, ChatSource
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.users.models import User

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self,
                 db: Session = Depends(dependencies.db)):
        self.db = db

    def fetch_chat(self, chat_id: UUID, only_unread: bool = False) \
            -> Optional[Chat]:
        if only_unread:
            return self.db.query(Chat). \
                join(Chat.messages). \
                filter(ChatMessage.status != MessageStatus.READ). \
                where(Chat.id == chat_id). \
                options(contains_eager(Chat.messages)). \
                order_by(ChatMessage.timestamp). \
                populate_existing().one_or_none()
        else:
            return self.db.execute(
                select(Chat).options(selectinload(Chat.messages)). \
                    where(Chat.id == chat_id)) \
                .scalar_one_or_none()

    def fetch_chat_by_members(self, user_a_id: UUID,
                              user_b_id: UUID) -> Optional[Chat]:
        """
        :return: Chat between provided users or None
        """
        # TODO a shitty query, but I don't know how todo union intersections
        # in sqlalchemy
        return self.db.execute(select(Chat).where(
            ((Chat.initiator_id == user_a_id) &
             (Chat.the_other_person_id == user_b_id)) |
            ((Chat.initiator_id == user_b_id) & (
                    Chat.the_other_person_id == user_a_id))
        )).scalar_one_or_none()

    def post_message(
            self, message_id: UUID,
            sender_id: UUID,
            recipient_id: UUID,
            timestamp: datetime.datetime,
            message: Optional[str] = None,
            image_id: Optional[UUID] = None,
            is_liked: Optional[bool] = False,
            status: Optional[MessageStatus] = MessageStatus.SENT):
        """
        Adds a message to the chat between supplied users.

        Raises SwipeError if the chat does not exist

        :param status:
        :param is_liked:
        :param image_id:
        :param message_id:
        :param sender_id:
        :param recipient_id:
        :param message:
        :param timestamp:
        :return: chat id
        """
        chat: Chat = self.fetch_chat_by_members(sender_id, recipient_id)
        if not chat:
            raise SwipeError(f"Chat between {sender_id} and {recipient_id} "
                             f"does not exist")

        logger.info(f"Saving message from '{sender_id}' to '{recipient_id}' "
                    f"to chat '{chat.id}', text: '{message}'")
        if message:
            chat_message = ChatMessage(
                id=message_id, is_liked=is_liked,
                timestamp=timestamp,
                status=status,
                message=message,
                sender_id=sender_id)
        elif image_id:
            chat_message = ChatMessage(
                id=message_id, is_liked=is_liked,
                timestamp=timestamp,
                status=status,
                image_id=image_id,
                sender_id=sender_id)
        else:
            raise SwipeError("Either message or image_id must be provided")

        chat.messages.append(chat_message)
        self.db.commit()

    def post_message_to_global(self, message_id: UUID,
                               sender_id: UUID, message: str,
                               timestamp: datetime.datetime):
        logger.info(f"Saving message from {sender_id} to global chat")
        chat_message = GlobalChatMessage(
            id=message_id, timestamp=timestamp, message=message,
            sender_id=sender_id)
        self.db.add(chat_message)
        self.db.commit()

    def set_received_status(self, message_id: UUID):
        logger.info(f"Updating message {message_id} status to received")
        self.db.execute(
            update(ChatMessage).where(
                ChatMessage.id == message_id).values(
                status=MessageStatus.RECEIVED))
        self.db.commit()

    def set_read_status(self, message_id: UUID):
        """
        Set status of all messages before and including the one with
        message_id to MessageStatus.READ

        :param message_id:
        """
        logger.info(f"Updating message status to read "
                    f"starting from {message_id}")
        message: ChatMessage = self.fetch_message(message_id)

        # TODO update only received or all?
        self.db.execute(
            update(ChatMessage).where(
                (ChatMessage.timestamp <= message.timestamp) &
                (ChatMessage.status != MessageStatus.READ) &
                (ChatMessage.sender_id == message.sender_id)).values(
                status=MessageStatus.READ))
        self.db.commit()

    def fetch_chats(self, user_id: UUID,
                    only_unread: bool = False) -> list[Chat]:
        """
        Returns all chats for the provided user
        """
        if only_unread:
            result = self.db.query(Chat). \
                join(Chat.messages). \
                filter(ChatMessage.status != MessageStatus.READ). \
                options(contains_eager(Chat.messages)). \
                order_by(ChatMessage.timestamp). \
                populate_existing().all()
        else:
            query = select(Chat). \
                options(selectinload(Chat.messages)). \
                where(((Chat.initiator_id == user_id) |
                       (Chat.the_other_person_id == user_id)))
            result = self.db.execute(query).scalars().all()
        return result

    def fetch_chat_ids(self, user_id: UUID) -> list[UUID]:
        query = select(Chat.id). \
            where(((Chat.initiator_id == user_id) |
                   (Chat.the_other_person_id == user_id)))
        result = self.db.execute(query).scalars().all()
        return result

    def fetch_global_chat(self, last_message_id: Optional[UUID] = None) \
            -> list[GlobalChatMessage]:
        if last_message_id:
            last_message = self.fetch_global_message(last_message_id)
            query = select(GlobalChatMessage). \
                where(GlobalChatMessage.timestamp > last_message.timestamp). \
                order_by(GlobalChatMessage.timestamp)
        else:
            query = select(GlobalChatMessage). \
                order_by(GlobalChatMessage.timestamp)
        return self.db.execute(query).scalars().all()

    def set_like_status(self, message_id: UUID, status: bool = True):
        self.db.execute(
            update(ChatMessage).where(
                ChatMessage.id == message_id).values(is_liked=status))
        self.db.commit()

    def fetch_message(self, message_id: UUID):
        return self.db.execute(
            select(ChatMessage).where(ChatMessage.id == message_id)). \
            scalar_one_or_none()

    def fetch_global_message(self, message_id: UUID):
        return self.db.execute(
            select(GlobalChatMessage). \
                where(GlobalChatMessage.id == message_id)). \
            scalar_one_or_none()

    def delete_chat(self, chat_id: UUID, user_object: Optional[User] = None):
        """
        Deletes a chat. If user_object is provided and he is not a member
        of the chat, raises SwipeError

        :param chat_id:
        :param user_object:
        """
        chat = self.db.execute(
            select(Chat).where(Chat.id == chat_id)). \
            scalar_one_or_none()
        if not chat:
            raise SwipeError("You are not allowed to delete this chat "
                             "because chat does not exist")
        if user_object \
                and user_object.id not in (
                chat.initiator_id, chat.the_other_person_id):
            raise SwipeError("You are not allowed to delete this chat "
                             "because you are not a member")

        for message in chat.messages:
            message.delete_image()

        self.db.execute(delete(Chat).where(Chat.id == chat_id))
        self.db.commit()

    def update_chat_status(self, chat_id: UUID, status: ChatStatus):
        result = self.db.execute(update(Chat).where(Chat.id == chat_id).
                                 values(status=status))
        self.db.commit()
        if result.rowcount == 0:
            raise SwipeError(f'Chat with id:{chat_id} does not exist')

    def create_chat(self, chat_id: UUID, initiator_id: UUID,
                    the_other_person_id: UUID, chat_status: ChatStatus,
                    source: ChatSource):
        if self.fetch_chat(chat_id):
            raise SwipeError(f"Chat with id:'{chat_id}' already exists")

        logger.info(f"Creating chat, id:'{chat_id}' "
                    f"between '{initiator_id}' and '{the_other_person_id}'")
        chat = Chat(id=chat_id,
                    source=source,
                    status=chat_status,
                    initiator_id=initiator_id,
                    the_other_person_id=the_other_person_id)
        self.db.add(chat)
        self.db.commit()
