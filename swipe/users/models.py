import uuid

from sqlalchemy import Column, String, Boolean, Integer, Enum, ARRAY, JSON, \
    ForeignKey, Date
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
from swipe.users.enums import UserInterests, Gender, AuthProvider, ZodiacSign, \
    RecurrenceRate


class User(ModelBase):
    __tablename__ = 'users'

    MAX_ALLOWED_PHOTOS = 6

    # can not be updated
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(20), nullable=False, default='')

    bio = Column(String(200), nullable=False, default='')
    height = Column(Integer(), nullable=False, default=0)
    gender = Column(Enum(Gender), nullable=False,
                    default=Gender.ATTACK_HELICOPTER)

    date_of_birth = Column(Date)
    zodiac_sign = Column(Enum(ZodiacSign))

    smoking = Column(Enum(RecurrenceRate), nullable=False,
                     default=RecurrenceRate.NEVER)
    drinking = Column(Enum(RecurrenceRate), nullable=False,
                      default=RecurrenceRate.NEVER)

    interests = Column(ARRAY(Enum(UserInterests)), nullable=False, default=[])
    photos = Column(ARRAY(String(50)), nullable=False, default=[])

    # TODO there is a better way to store coordinates
    coordinates = Column(JSON)
    rating = Column(Integer, nullable=False, default=0)

    auth_info_id = Column(UUID(as_uuid=True), ForeignKey('auth_info.id'))
    auth_info = relationship('AuthInfo', back_populates='user', uselist=False)

    is_premium = Column(Boolean, nullable=False, default=False)


class AuthInfo(ModelBase):
    __tablename__ = 'auth_info'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    access_token = Column(String)

    auth_provider = Column(Enum(AuthProvider), nullable=False)
    provider_token = Column(String, nullable=False)
    provider_user_id = Column(String, nullable=False)

    user = relationship('User', back_populates='auth_info', uselist=False)
