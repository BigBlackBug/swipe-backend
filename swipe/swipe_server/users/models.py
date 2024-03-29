from __future__ import annotations

import datetime
import logging
import uuid

from dateutil.relativedelta import relativedelta
from sqlalchemy import Column, String, Boolean, Integer, Enum, ARRAY, \
    ForeignKey, Date, UniqueConstraint, select, Table, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, object_session

from swipe.settings import constants, settings
from swipe.swipe_server.misc.database import ModelBase
from swipe.swipe_server.misc.storage import storage_client
from swipe.swipe_server.users.enums import UserInterests, Gender, \
    AuthProvider, ZodiacSign, RecurrenceRate, NotificationTypes, AccountStatus

logger = logging.getLogger(__name__)

IDList = list[UUID]

blacklist_table = Table(
    "blacklist",
    ModelBase.metadata,
    Column('block_date', DateTime, nullable=False,
           default=datetime.datetime.utcnow().replace(microsecond=0)),
    Column('comment', String(200), default='Fuck him'),
    Column("blocked_by_id", UUID(as_uuid=True),
           ForeignKey("users.id", ondelete='CASCADE'), primary_key=True),
    Column("blocked_user_id", UUID(as_uuid=True),
           ForeignKey("users.id", ondelete='CASCADE'), primary_key=True),
)

# we're searching the table by these fields separately
Index("idx_blacklist_blocked_by", blacklist_table.c.blocked_by_id)
Index("idx_blacklist_blocked_user", blacklist_table.c.blocked_user_id)

DEFAULT_PHOTO_ID = '23d66fc7-d87c-415d-9834-ba84a0a72a6f.jpg'


class User(ModelBase):
    __tablename__ = 'users'

    MAX_ALLOWED_PHOTOS = 6

    # can not be updated
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # TODO ёбаный костыль, пощади
    account_status = Column(Enum(AccountStatus), nullable=False,
                            default=AccountStatus.REGISTRATION)
    registration_date = Column(
        DateTime, nullable=False,
        default=datetime.datetime.utcnow().replace(microsecond=0))
    deactivation_date = Column(DateTime)
    # NULL if he is online
    last_online = Column(DateTime)
    name = Column(String(30), nullable=False, default='')

    bio = Column(String(200), nullable=False, default='👋 Я здесь недавно')
    height = Column(Integer())
    gender = Column(Enum(Gender))

    date_of_birth = Column(Date)
    zodiac_sign = Column(Enum(ZodiacSign))

    smoking = Column(Enum(RecurrenceRate))
    drinking = Column(Enum(RecurrenceRate))

    interests = Column(ARRAY(Enum(UserInterests)), nullable=False, default=[])
    photos = Column(ARRAY(String(50)), nullable=False, default=[])
    avatar_id = Column(String)

    enabled_notifications = Column(Enum(NotificationTypes))
    instagram_profile = Column(String, nullable=False, default='')
    tiktok_profile = Column(String, nullable=False, default='')
    snapchat_profile = Column(String, nullable=False, default='')

    location = relationship('Location', uselist=False)
    location_id = Column(UUID(as_uuid=True), ForeignKey('location.id'))

    auth_info = relationship('AuthInfo', back_populates='user', uselist=False)
    firebase_token = Column(String)
    # variables
    rating = Column(Integer, nullable=False, default=0)
    swipes = Column(Integer, nullable=False,
                    default=constants.SWIPES_DEFAULT_NUMBER)
    is_premium = Column(Boolean, nullable=False, default=False)

    blacklist = relationship(
        "User",
        secondary=blacklist_table,
        back_populates="blocked_by",
        primaryjoin=id == blacklist_table.c.blocked_by_id,  # noqa
        secondaryjoin=id == blacklist_table.c.blocked_user_id)  # noqa
    blocked_by = relationship(
        "User",
        secondary=blacklist_table,
        back_populates="blacklist",
        primaryjoin=id == blacklist_table.c.blocked_user_id,  # noqa
        secondaryjoin=id == blacklist_table.c.blocked_by_id)  # noqa

    @property
    def age(self):
        return relativedelta(datetime.datetime.utcnow().date(),
                             self.date_of_birth).years

    @property
    def online(self):
        return self.last_online is None

    @property
    def photo_urls(self):
        return [self.photo_url(photo_id) for photo_id in self.photos]

    @property
    def avatar_url(self):
        if self.avatar_id:
            photo_id = self.avatar_id
        else:
            photo_id = DEFAULT_PHOTO_ID
        return f'{settings.SWIPE_REST_SERVER_HOST}' \
               f'/v1/users/photos/{photo_id}'

    def photo_url(self, photo_id: str):
        if not photo_id or photo_id not in self.photos:
            photo_id = DEFAULT_PHOTO_ID
        return f'{settings.SWIPE_REST_SERVER_HOST}' \
               f'/v1/users/photos/{photo_id}'

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

    def delete_photos(self):
        logger.info(f"Deleting user {self.id} photos")
        for photo in self.photos:
            storage_client.delete_image(photo)

        logger.info(f"Deleting user {self.id} avatar")
        if self.avatar_id:
            storage_client.delete_image(self.avatar_id)

    def __str__(self):
        return f'User {self.id}, name: {self.name}'


Index('idx_user_gender', User.gender)
Index('idx_user_date_of_birth', User.date_of_birth)

# for ordering in popular query
Index('idx_user_rating', User.rating)


class Location(ModelBase):
    __table_args__ = (
        UniqueConstraint('city', 'country', name='_location'),
    )
    __tablename__ = 'location'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    city = Column(String, nullable=False)
    country = Column(String, nullable=False)
    flag = Column(String, nullable=False)

    def __str__(self):
        return f'Country: {self.country}, city: {self.city}'


Index('idx_location_city', Location.city)
Index('idx_location_country', Location.country)


class AuthInfo(ModelBase):
    __tablename__ = 'auth_info'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    access_token = Column(String)

    auth_provider = Column(Enum(AuthProvider), nullable=False)
    provider_user_id = Column(String, nullable=False)

    user = relationship('User', back_populates='auth_info')
    user_id = Column(UUID(as_uuid=True),
                     ForeignKey('users.id', ondelete="CASCADE"))


Index('idx_auth_provider_provider', AuthInfo.auth_provider)
Index('idx_auth_provider_provider_user_id', AuthInfo.provider_user_id)
