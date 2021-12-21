from __future__ import annotations

import datetime
import enum
import logging
import uuid

from sqlalchemy import Column, String, Enum, ForeignKey, DateTime, \
    UniqueConstraint, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import relationship

from swipe.swipe_server.misc.database import ModelBase
from swipe.swipe_server.misc.storage import storage_client

logger = logging.getLogger(__name__)


class MessageStatus(str, enum.Enum):
    SENT = 'sent'
    RECEIVED = 'received'
    READ = 'read'


class ChatStatus(str, enum.Enum):
    REQUESTED = 'requested'
    ACCEPTED = 'accepted'
    OPENED = 'opened'


class ChatSource(str, enum.Enum):
    TEXT_LOBBY = 'text_lobby'
    VIDEO_LOBBY = 'video_lobby'
    AUDIO_LOBBY = 'audio_lobby'
    DIRECT = 'direct'


class Chat(ModelBase):
    __tablename__ = 'chats'
    __table_args__ = (
        UniqueConstraint('initiator_id', 'the_other_person_id',
                         name='one_chat_per_pair'),
        UniqueConstraint('the_other_person_id', 'initiator_id',
                         name='one_chat_per_pair_2'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    creation_date = Column(DateTime, nullable=False)
    source = Column(Enum(ChatSource), nullable=False)
    status = Column(Enum(ChatStatus), nullable=False,
                    default=ChatStatus.REQUESTED)
    messages = relationship('ChatMessage',
                            order_by='asc(ChatMessage.timestamp)',
                            collection_class=ordering_list('timestamp'),
                            # lazy='noload',
                            # we're using database cascades
                            # so this setting is due
                            passive_deletes=True,
                            back_populates='chat')

    initiator_id = Column(UUID(as_uuid=True),
                          ForeignKey('users.id', ondelete='CASCADE'))
    initiator = relationship('User', foreign_keys=[initiator_id], uselist=False)

    the_other_person_id = Column(UUID(as_uuid=True),
                                 ForeignKey('users.id', ondelete='CASCADE'))
    the_other_person = relationship('User', foreign_keys=[the_other_person_id],
                                    uselist=False)


Index('chat_initiator_id', Chat.initiator_id)
Index('chat_the_other_person_id', Chat.the_other_person_id)


class ChatMessage(ModelBase):
    __tablename__ = 'chat_messages'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    timestamp = Column(DateTime, nullable=False)
    status = Column(Enum(MessageStatus), default=MessageStatus.SENT)

    message = Column(String(256))
    image_id = Column(String(50))

    is_liked = Column(Boolean, default=False)

    sender_id = Column(UUID(as_uuid=True),
                       ForeignKey('users.id', ondelete="CASCADE"))
    sender = relationship('User', uselist=False)

    chat_id = Column(UUID(as_uuid=True),
                     ForeignKey('chats.id', ondelete="CASCADE"))
    chat = relationship('Chat', back_populates='messages')

    def delete_image(self):
        if self.image_id:
            logger.info(f"Deleting image {self.image_id} of chat {self.id}")
            storage_client.delete_chat_image(self.image_id)


Index('chat_message_sender_id', ChatMessage.sender_id)
# for order by clauses
Index('chat_message_timestamp', ChatMessage.timestamp)


class GlobalChatMessage(ModelBase):
    __tablename__ = 'global_chat_messages'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    timestamp = Column(DateTime, nullable=False)

    message = Column(String(256))

    sender_id = Column(UUID(as_uuid=True),
                       ForeignKey('users.id', ondelete='CASCADE'))
    sender = relationship('User', uselist=False)


Index('global_chat_message_timestamp', GlobalChatMessage.timestamp)
