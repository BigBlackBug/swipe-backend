import datetime
import io
import logging
import random
from typing import Optional
from uuid import UUID, uuid4

import lorem
from fastapi import Depends
from sqlalchemy import select, update, desc
from sqlalchemy.orm import Session, selectinload

import swipe.dependencies
from swipe import images
from swipe.chats.models import Chat, ChatStatus, ChatMessage, MessageStatus, \
    GlobalChatMessage
from swipe.errors import SwipeError
from swipe.storage import storage_client
from swipe.users.models import User

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self,
                 db: Session = Depends(swipe.dependencies.db)):
        self.db = db

    def fetch_chat(self, chat_id: UUID) -> Optional[Chat]:
        return self.db.execute(select(Chat).options(
            selectinload(Chat.messages)).where(Chat.id == chat_id)) \
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

    def post_message(self, message_id: UUID,
                     sender_id: UUID,
                     recipient_id: UUID,
                     timestamp: datetime.datetime,
                     message: Optional[str] = None,
                     image_id: Optional[UUID] = None) -> UUID:
        """
        Adds a message to the chat between supplied users.
        If the chat doesn't exist, creates one.

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
                id=message_id,
                timestamp=timestamp,
                status=MessageStatus.SENT,
                message=message,
                sender_id=sender_id)
        elif image_id:
            chat_message = ChatMessage(
                id=message_id,
                timestamp=timestamp,
                status=MessageStatus.SENT,
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
        message: ChatMessage = self.db.execute(
            select(ChatMessage).where(ChatMessage.id == message_id)). \
            scalar_one_or_none()

        # TODO update only received or all?
        self.db.execute(
            update(ChatMessage).where(
                (ChatMessage.timestamp <= message.timestamp) &
                (ChatMessage.status != MessageStatus.READ) &
                (ChatMessage.sender_id == message.sender_id)).values(
                status=MessageStatus.READ))

    def fetch_chats(self, user_object: User) -> list[Chat]:
        """
        Returns all chats for the provided user
        """
        query = select(Chat). \
            options(selectinload(Chat.messages)). \
            where(((Chat.initiator_id == user_object.id) |
                   (Chat.the_other_person_id == user_object.id)))

        return self.db.execute(query).scalars().all()

    def fetch_global_chat(self) -> list[GlobalChatMessage]:
        query = select(GlobalChatMessage).order_by(
            desc(GlobalChatMessage.timestamp))
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
