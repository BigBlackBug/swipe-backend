import datetime
import io
import json
import logging
import random
from typing import Optional, Any
from uuid import UUID, uuid4

import lorem
from aioredis import Redis
from fastapi import Depends
from sqlalchemy import select, update, desc, delete
from sqlalchemy.orm import Session, selectinload, contains_eager

import swipe.dependencies
from swipe import images
from swipe.chats.models import Chat, ChatStatus, ChatMessage, MessageStatus, \
    GlobalChatMessage
from swipe.chats.schemas import ChatMessageORMSchema
from swipe.errors import SwipeError
from swipe.storage import storage_client
from swipe.users.models import User

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self,
                 db: Session = Depends(swipe.dependencies.db)):
        self.db = db

    def fetch_chat(self, chat_id: UUID, only_unread: bool = False) \
            -> Optional[Chat]:
        if only_unread:
            return self.db.query(Chat). \
                join(Chat.messages). \
                filter(ChatMessage.status != MessageStatus.READ). \
                where(Chat.id == chat_id). \
                options(contains_eager(Chat.messages)). \
                order_by(desc(ChatMessage.timestamp)). \
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
            status: Optional[MessageStatus] = MessageStatus.SENT) -> UUID:
        """
        Adds a message to the chat between supplied users.
        If the chat doesn't exist, creates one.

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
            logger.info(f"Chat between {sender_id} and {recipient_id} "
                        f"does not exist, creating")
            chat = Chat(status=ChatStatus.ACCEPTED,
                        initiator_id=sender_id,
                        the_other_person_id=recipient_id)
            self.db.add(chat)
        self.db.commit()
        self.db.refresh(chat)

        logger.info(f"Saving message from {sender_id} to {recipient_id} "
                    f"to chat {chat.id}, text:{message}")
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

        return chat.id

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
                populate_existing()
        else:
            query = select(Chat). \
                options(selectinload(Chat.messages)). \
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
                order_by(desc(GlobalChatMessage.timestamp))
        else:
            query = select(GlobalChatMessage). \
                order_by(desc(GlobalChatMessage.timestamp))
        return self.db.execute(query).scalars().all()

    def generate_random_global_chat(self, n_messages: int):
        messages = []
        message_time = datetime.datetime.utcnow()
        people = self.db.execute(select(User)).scalars().all()
        for _ in range(n_messages):
            message_time -= datetime.timedelta(minutes=random.randint(1, 10))
            sender = random.choice(people)
            message = GlobalChatMessage(
                timestamp=message_time,
                message=lorem.sentence(),
                sender=sender)

            messages.append(message)
            self.db.add(message)
        self.db.commit()
        for message in messages:
            self.db.refresh(message)
        return messages

    def generate_random_chat(
            self, user_a: User, user_b: User,
            n_messages: int = 10, generate_images: bool = False) -> Chat:
        chat = Chat(status=ChatStatus.ACCEPTED,
                    initiator=user_a, the_other_person=user_b)
        self.db.add(chat)

        people = [user_a, user_b]
        message_time = datetime.datetime.utcnow()
        for _ in range(n_messages):
            message_time -= datetime.timedelta(minutes=random.randint(1, 10))
            sender = random.choice(people)
            if generate_images and random.random() < 0.3:
                # image
                extension = 'png'
                image_id = f'{uuid4()}.{extension}'
                image = images.generate_random_avatar(sender.name)
                with io.BytesIO() as output:
                    image.save(output, format=extension)
                    contents = output.getvalue()
                storage_client.upload_image(image_id, contents)

                message = ChatMessage(
                    timestamp=message_time,
                    status=random.choice(list(MessageStatus)),
                    image_id=image_id,
                    sender=sender)
            else:
                # text
                message = ChatMessage(
                    timestamp=message_time,
                    status=random.choice(list(MessageStatus)),
                    message=lorem.sentence(),
                    sender=sender)

            chat.messages.append(message)

        self.db.commit()
        self.db.refresh(chat)
        return chat

    def set_like_status(self, message_id: UUID, status: bool = True):
        self.db.execute(
            update(ChatMessage).where(
                ChatMessage.id == message_id).values(is_liked=status))

    def fetch_message(self, message_id: UUID):
        return self.db.execute(
            select(ChatMessage).where(ChatMessage.id == message_id)). \
            scalar_one_or_none()

    def fetch_global_message(self, message_id: UUID):
        return self.db.execute(
            select(GlobalChatMessage). \
                where(GlobalChatMessage.id == message_id)). \
            scalar_one_or_none()

    def delete_chat(self, chat_id: UUID, current_user: User):
        # Why make another query, when we can check rowcount?
        result = self.db.execute(
            delete(Chat).where(Chat.id == chat_id).
                where((Chat.initiator_id == current_user.id) |
                      (Chat.the_other_person_id == current_user.id)))
        if result.rowcount != 1:
            raise SwipeError("You are not allowed to delete this chat "
                             "because you are not a member")


class RedisChatService:
    def __init__(self,
                 redis: Redis = Depends(swipe.dependencies.redis)):
        self.redis = redis

    async def save_message(
            self, sender_id: str, recipient_id: str,
            timestamp: datetime.datetime,
            payload: dict[str, Any]):
        chat_dict = ChatMessageORMSchema(
            id=payload['message_id'],
            sender_id=UUID(hex=sender_id),
            message=payload.get('text'),
            image_id=payload.get('image_id'),
            timestamp=timestamp,
            is_liked=False
        ).dict(exclude_unset=True)
        await self.redis.hset(name=self._chat_id_key(sender_id, recipient_id),
                              key=payload['message_id'],
                              value=json.dumps(chat_dict))

    def _chat_id_key(self, user_a_id: str, user_b_id):
        return f"temp_chat_{'|'.join(sorted([user_a_id, user_b_id]))}"

    async def drop_chat(self, sender_id: str, recipient_id: str):
        await self.redis.delete(self._chat_id_key(sender_id, recipient_id))

    async def fetch_chat(self, sender_id: str, recipient_id: str) \
            -> dict[str, dict]:
        result: dict[str, dict] = {}
        chat_data: dict = await self.redis.hgetall(
            name=self._chat_id_key(sender_id, recipient_id))
        for message_id, message_data in chat_data.items():
            result[str(message_id)] = json.loads(message_data)
        return result

    async def set_read_status(self, sender_id: str, recipient_id: str):
        chat_id = self._chat_id_key(sender_id, recipient_id)
        for message_id in await self.redis.hkeys(chat_id):
            await self._update_chat_message(
                chat_id, message_id, {
                    'status': MessageStatus.READ
                })

    async def _update_chat_message(
            self, chat_id: str, message_id: str, values: dict):
        message_json = await self.redis.hget(chat_id, message_id)
        message_data: dict = json.loads(message_json)
        message_data.update(values)

        await self.redis.hset(
            name=chat_id, key=message_id,
            value=json.dumps(message_data))

    async def set_like_status(self, sender_id: str, recipient_id: str,
                              message_id: str, is_liked: bool):
        chat_id = self._chat_id_key(sender_id, recipient_id)
        await self._update_chat_message(chat_id, message_id, {
            'is_liked': is_liked
        })
