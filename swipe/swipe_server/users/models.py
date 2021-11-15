from __future__ import annotations

import logging
import uuid

from sqlalchemy import Column, String, Boolean, Integer, Enum, ARRAY, \
    ForeignKey, Date, UniqueConstraint, select, Table, LargeBinary
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, object_session

from swipe.swipe_server.misc.database import ModelBase
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.misc.storage import storage_client
from swipe.swipe_server.users.enums import UserInterests, Gender, \
    AuthProvider, ZodiacSign, RecurrenceRate, NotificationTypes

logger = logging.getLogger(__name__)

IDList = list[UUID]

# TODO add a shit ton of indices
blacklist_table = Table(
    "blacklist",
    ModelBase.metadata,
    Column("blocked_by_id", UUID(as_uuid=True),
           ForeignKey("users.id", ondelete='CASCADE'), primary_key=True),
    Column("blocked_user_id", UUID(as_uuid=True),
           ForeignKey("users.id", ondelete='CASCADE'), primary_key=True),
)


class User(ModelBase):
    __tablename__ = 'users'

    MAX_ALLOWED_PHOTOS = 6

    # can not be updated
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(30), nullable=False, default='')

    bio = Column(String(200), nullable=False, default='')
    height = Column(Integer())
    gender = Column(Enum(Gender))

    date_of_birth = Column(Date)
    zodiac_sign = Column(Enum(ZodiacSign))

    smoking = Column(Enum(RecurrenceRate))
    drinking = Column(Enum(RecurrenceRate))

    interests = Column(ARRAY(Enum(UserInterests)), nullable=False, default=[])
    photos = Column(ARRAY(String(50)), nullable=False, default=[])
    # base64 encoded 30x30 avatar
    avatar = Column(LargeBinary)

    enabled_notifications = Column(Enum(NotificationTypes))
    instagram_profile = Column(String, nullable=False, default='')
    tiktok_profile = Column(String, nullable=False, default='')
    snapchat_profile = Column(String, nullable=False, default='')

    location = relationship('Location', uselist=False)
    location_id = Column(UUID(as_uuid=True), ForeignKey('location.id'))

    auth_info = relationship('AuthInfo', back_populates='user', uselist=False)

    # variables
    rating = Column(Integer, nullable=False, default=0)
    swipes = Column(Integer, nullable=False, default=0)
    is_premium = Column(Boolean, nullable=False, default=False)

    blacklist = relationship(
        "User",
        secondary=blacklist_table,
        backref="blocked_by",
        primaryjoin=id == blacklist_table.c.blocked_by_id,  # noqa
        secondaryjoin=id == blacklist_table.c.blocked_user_id)  # noqa

    def set_location(self, location: dict[str, str]):
        # location rows are unique with regards to city/country
        session = object_session(self)
        location_in_db = \
            session.execute(
                select(Location). \
                    where(Location.city == location['city']). \
                    where(Location.country == location['country'])). \
                scalar_one_or_none()

        if not location_in_db:
            location_in_db = Location(**location)
            session.add(location_in_db)

        self.location = location_in_db

    def block_user(self, target_user: User):
        if target_user in self.blacklist:
            raise SwipeError(
                f'{target_user.id} is already blocked by {self.id}')

        self.blacklist.append(target_user)

    def delete_photos(self):
        logger.info(f"Deleting user {self.id} photos")
        for photo in self.photos:
            storage_client.delete_image(photo)

    def __str__(self):
        return f'User {self.id}, name: {self.name}'


class Location(ModelBase):
    __table_args__ = (
        UniqueConstraint('city', 'country', name='_location'),
    )
    __tablename__ = 'location'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    city = Column(String, nullable=False)
    country = Column(String, nullable=False)
    flag = Column(String, nullable=False)


class AuthInfo(ModelBase):
    __tablename__ = 'auth_info'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    access_token = Column(String)

    auth_provider = Column(Enum(AuthProvider), nullable=False)
    provider_user_id = Column(String, nullable=False)

    user = relationship('User', back_populates='auth_info')
    user_id = Column(UUID(as_uuid=True),
                     ForeignKey('users.id', ondelete="CASCADE"))
