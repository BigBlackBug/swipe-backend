from __future__ import annotations

import enum
import uuid

from sqlalchemy import Column, String, Enum, ForeignKey, DateTime, \
    UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import relationship

from swipe.database import ModelBase


class MessageStatus(str, enum.Enum):
    SENT = 'sent'
    RECEIVED = 'received'
    READ = 'read'


class ChatStatus(str, enum.Enum):
    REQUESTED = 'requested'
    ACCEPTED = 'accepted'


class Chat(ModelBase):
    __tablename__ = 'chats'
    __table_args__ = (
        UniqueConstraint('initiator_id', 'the_other_person_id',
                         name='one_chat_per_pair'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    status = Column(Enum(ChatStatus), nullable=False,
                    default=ChatStatus.REQUESTED)
    messages = relationship('ChatMessage',
                            order_by='desc(ChatMessage.timestamp)',
                            collection_class=ordering_list('timestamp'),
                            back_populates='chat')

    initiator_id = Column(UUID(as_uuid=True), ForeignKey('users.id'))
    initiator = relationship('User', foreign_keys=[initiator_id], uselist=False)

    the_other_person_id = Column(UUID(as_uuid=True), ForeignKey('users.id'))
    the_other_person = relationship('User', foreign_keys=[the_other_person_id],
                                    uselist=False)


class ChatMessage(ModelBase):
    __tablename__ = 'chat_messages'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    timestamp = Column(DateTime, nullable=False)
    status = Column(Enum(MessageStatus), default=MessageStatus.SENT)

    message = Column(String(256))
    image_id = Column(String(50))

    sender_id = Column(UUID(as_uuid=True), ForeignKey('users.id'))
    sender = relationship('User', uselist=False)

    chat_id = Column(UUID(as_uuid=True), ForeignKey('chats.id'))
    chat = relationship('Chat', back_populates='messages')
