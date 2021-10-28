import datetime
import io
import logging
import random
import uuid
from typing import Optional

import lorem
from fastapi import Depends
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

import swipe.dependencies
from swipe import images
from swipe.chats.models import Chat, ChatStatus, ChatMessage, MessageStatus
from swipe.storage import CloudStorage
from swipe.users.models import User

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self,
                 db: Session = Depends(swipe.dependencies.db)):
        self.db = db
        self._storage = CloudStorage()

    def fetch_chat(self, chat_id: uuid.UUID) -> Optional[Chat]:
        return self.db.execute(select(Chat).options(
            selectinload(Chat.messages)).where(Chat.id == chat_id)) \
            .scalar_one_or_none()

    def fetch_chat_by_members(self, user_a_id: uuid.UUID,
                              user_b_id: uuid.UUID) -> Optional[Chat]:
        # TODO a shitty query, but I don't know how todo union intersections
        # in sqlalchemy
        return self.db.execute(select(Chat).where(
            ((Chat.initiator_id == user_a_id) &
             (Chat.the_other_person_id == user_b_id)) |
            ((Chat.initiator_id == user_b_id) & (
                    Chat.the_other_person_id == user_a_id))
        )).scalar_one_or_none()

    def post_message(self, message_id: uuid.UUID,
                     sender_id: uuid.UUID,
                     recipient_id: uuid.UUID, message: str,
                     timestamp: datetime.datetime):
        chat: Chat = self.fetch_chat_by_members(sender_id, recipient_id)
        if not chat:
            logger.info(f"Chat between {sender_id} and {recipient_id} "
                        f"does not exist, creating")
            chat = Chat(status=ChatStatus.ACCEPTED,
                        initiator_id=sender_id,
                        the_other_person_id=recipient_id)
            self.db.add(chat)
        else:
            logger.info("Found a chat")

        self.db.commit()
        self.db.refresh(chat)

        logger.info(f"Saving message from {sender_id} to {recipient_id} "
                    f"to chat {chat.id}")
        message = ChatMessage(
            id=message_id,
            timestamp=timestamp,
            status=MessageStatus.SENT,
            message=message,
            sender_id=sender_id)
        chat.messages.append(message)
        self.db.commit()

    def update_message_status(self, message_id: uuid.UUID,
                              status: MessageStatus):
        logger.info(f"Updating message {message_id} status to {status}")
        self.db.execute(
            update(ChatMessage).where(
                ChatMessage.id == message_id).values(
                status=status))
        self.db.commit()

    def fetch_chats(self, user_object: User) -> list[Chat]:
        """
        Returns all chats for the provided user
        """
        query = select(Chat). \
            options(selectinload(Chat.messages)). \
            where(((Chat.initiator_id == user_object.id) |
                   (Chat.the_other_person_id == user_object.id)))

        return self.db.execute(query).scalars().all()

    def generate_random_chat(
            self, user_a: User, user_b: User, n_messages: int) -> Chat:
        chat = Chat(status=ChatStatus.ACCEPTED,
                    initiator=user_a, the_other_person=user_b)
        self.db.add(chat)

        people = [user_a, user_b]
        message_time = datetime.datetime.utcnow()
        for _ in range(n_messages):
            message_time -= datetime.timedelta(minutes=random.randint(1, 10))
            sender = random.choice(people)
            if random.random() > 0.7:
                # text
                message = ChatMessage(
                    timestamp=message_time,
                    status=random.choice(list(MessageStatus)),
                    message=lorem.sentence(),
                    sender=sender)
            else:
                # image
                extension = 'png'
                image_id = f'{uuid.uuid4()}.{extension}'
                image = images.generate_random_avatar(sender.name)
                with io.BytesIO() as output:
                    image.save(output, format=extension)
                    contents = output.getvalue()
                self._storage.upload_image(image_id, contents)

                message = ChatMessage(
                    timestamp=message_time,
                    status=random.choice(list(MessageStatus)),
                    image_id=image_id,
                    sender=sender)
            chat.messages.append(message)

        self.db.commit()
        self.db.refresh(chat)
        return chat
