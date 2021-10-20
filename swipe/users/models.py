import uuid

from sqlalchemy import Column, String, Boolean, Integer, Enum, ARRAY, \
    ForeignKey, Date, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, object_session

from swipe.database import ModelBase
from swipe.users.enums import UserInterests, Gender, AuthProvider, ZodiacSign, \
    RecurrenceRate, NotificationTypes

IDList = list[UUID]


# TODO add a shit ton of indices

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

    enabled_notifications = Column(Enum(NotificationTypes), nullable=False,
                                   default=NotificationTypes.FRIENDS_MESSAGES)
    instagram_profile = Column(String)
    tiktok_profile = Column(String)
    snapchat_profile = Column(String)

    location = relationship('Location', uselist=False)
    location_id = Column(UUID(as_uuid=True), ForeignKey('location.id'))

    auth_info_id = Column(UUID(as_uuid=True), ForeignKey('auth_info.id'))
    auth_info = relationship('AuthInfo', back_populates='user', uselist=False)

    # variables
    rating = Column(Integer, nullable=False, default=0)
    swipes = Column(Integer, nullable=False, default=0)
    is_premium = Column(Boolean, nullable=False, default=False)

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
    provider_token = Column(String, nullable=False)
    provider_user_id = Column(String, nullable=False)

    user = relationship('User', back_populates='auth_info', uselist=False)
