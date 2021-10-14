import enum
import uuid

from sqlalchemy import Column, String, Boolean, Integer, Enum, ARRAY, JSON, \
    ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from swipe.database import ModelBase


#
# class MessageStatus(str, enum.Enum):
#     SENT = 'sent'
#     RECEIVED = 'received'
#     READ = 'read'
#
#
# class Chat(ModelBase):
#     __tablename__ = 'chats'
#     id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
#
#     # TODO lazy mode comparison - immediate/joined/subquery/selectin
#     messages = relationship('ChatMessage', back_populates='chat')
#
#     initiator_id = Column(UUID(as_uuid=True), ForeignKey('users.id'))
#     initiator = relationship('User', foreign_keys=[initiator_id])
#
#     interlocutor_id = Column(UUID(as_uuid=True), ForeignKey('users.id'))
#     interlocutor = relationship('User', foreign_keys=[interlocutor_id])
#
#
# class ChatMessage(ModelBase):
#     __tablename__ = 'chat_messages'
#     id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
#
#     index = Column(Integer, unique=True)
#
#     status = Column(Enum(MessageStatus), default=MessageStatus.SENT)
#     message = Column(String(100))
#
#     sender_id = Column(UUID(as_uuid=True), ForeignKey('users.id'))
#     sender = relationship('User')
#
#     chat_id = Column(UUID(as_uuid=True), ForeignKey('chats.id'))
#     chat = relationship('Chat', back_populates='messages')
#

class UserInterests(str, enum.Enum):
    WORK = 'work'
    FRIENDSHIP = 'friendship'
    FLIRTING = 'flirting'
    NETWORKING = 'networking'
    CHAT = 'chat'
    LOVE = 'love'


class Gender(str, enum.Enum):
    MALE = 'male'
    FEMALE = 'female'
    ATTACK_HELICOPTER = 'attack_helicopter'


class AuthProvider(str, enum.Enum):
    GOOGLE = 'google'
    VK = 'vk'
    SNAPCHAT = 'snapchat'
    APPLE_ID = 'apple_id'


class User(ModelBase):
    __tablename__ = 'users'

    MAX_ALLOWED_PHOTOS = 6

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # can not be updated
    name = Column(String(20), nullable=False, default='')
    bio = Column(String(200), nullable=False, default='')
    height = Column(Integer(), nullable=False, default=0)

    interests = Column(ARRAY(Enum(UserInterests)), nullable=False, default=[])
    # TODO obviously proper image handling
    photos = Column(ARRAY(String(50)), nullable=False, default=[])
    gender = Column(Enum(Gender), nullable=False,
                    default=Gender.ATTACK_HELICOPTER)

    # TODO there is a better way to store coordinates
    coordinates = Column(JSON)
    rating = Column(Integer, nullable=False, default=0)

    auth_info_id = Column(UUID(as_uuid=True), ForeignKey('auth_info.id'))
    auth_info = relationship('AuthInfo', back_populates='user', uselist=False)

    is_premium = Column(Boolean, nullable=False, default=False)


class AuthInfo(ModelBase):
    __tablename__ = 'auth_info'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    auth_provider = Column(Enum(AuthProvider), nullable=False)
    # TODO maybe get away with just a single token
    payload = Column(JSON, nullable=False)

    user = relationship('User', back_populates='auth_info')
