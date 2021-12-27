from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional, Any
from uuid import UUID

from dateutil.relativedelta import relativedelta
from pydantic import BaseModel, Field, root_validator

from .enums import UserInterests, Gender, AuthProvider, ZodiacSign, \
    RecurrenceRate, NotificationTypes
from .models import User


class CallFeedback(str, Enum):
    THUMBS_UP = 'thumbs_up'
    THUMBS_DOWN = 'thumbs_down'


class RatingUpdateReason(str, Enum):
    FRIEND_REFERRED = 'friend_referred'
    AD_WATCHED = 'ad_watched'
    APP_REVIEWED = 'app_reviewed'
    PREMIUM_ACTIVATED = 'premium_activated'


class LocationSchema(BaseModel):
    city: str
    country: str
    flag: str

    class Config:
        orm_mode = True


class UserBase(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = Field(
        None, title="User's bio", max_length=200
    )
    height: Optional[int] = None

    interests: list[UserInterests] = []
    gender: Optional[Gender] = None

    smoking: Optional[RecurrenceRate] = None
    drinking: Optional[RecurrenceRate] = None

    instagram_profile: Optional[str] = None
    tiktok_profile: Optional[str] = None
    snapchat_profile: Optional[str] = None

    location: Optional[LocationSchema] = None
    enabled_notifications: Optional[NotificationTypes] = None


class UserCardPreviewOut(BaseModel):
    id: UUID
    name: str
    bio: str
    zodiac_sign: str
    date_of_birth: datetime.date

    rating: int
    location: LocationSchema

    interests: list[UserInterests] = []
    photos: Optional[list[str]] = []
    photo_urls: Optional[list[str]] = []

    avatar_id: Optional[str] = None

    instagram_profile: Optional[str] = None
    tiktok_profile: Optional[str] = None
    snapchat_profile: Optional[str] = None

    online: bool = False
    last_online: Optional[datetime.datetime] = None

    @staticmethod
    def sort_key(user: UserCardPreviewOut, current_user_dob: datetime.date):
        # offline dudes should come last
        if user.last_online:
            # grouping by 10 minutes
            key = 100 * relativedelta(
                datetime.datetime.utcnow(), user.last_online).minutes % 10
        else:
            # online users come first
            key = 1_000_000_000
        key -= 1000 * abs(current_user_dob - user.date_of_birth).days
        return key

    class Config:
        # allows Pydantic to read orm models and not just dicts
        orm_mode = True


class UserOut(UserBase):
    id: UUID
    photos: list[str] = []
    photo_urls: Optional[list[str]] = []

    avatar_id: Optional[str] = None
    avatar_url: Optional[str] = None

    date_of_birth: Optional[datetime.date] = None
    zodiac_sign: Optional[ZodiacSign] = None

    is_premium: bool
    rating: int
    swipes: int

    online: bool = False
    last_online: Optional[datetime.datetime] = None

    class Config:
        # allows Pydantic to read orm models and not just dicts
        orm_mode = True
        use_enum_values = True


class UserUpdate(UserBase):
    date_of_birth: Optional[datetime.date] = None
    zodiac_sign: Optional[ZodiacSign] = None
    photos: list[str] = None
    firebase_token: Optional[str] = None

    @root_validator(pre=True)
    def set_zodiac_sign(cls, values: dict[str, Any]):
        if 'date_of_birth' in values:
            values['zodiac_sign'] = \
                ZodiacSign.from_date(values['date_of_birth'])
        return values


class AuthenticationIn(BaseModel):
    auth_provider: AuthProvider
    provider_user_id: str


class AuthenticationOut(BaseModel):
    user_id: UUID
    access_token: str


class JWTPayload(AuthenticationIn):
    user_id: str
    created_at: int


class PopularFilterBody(BaseModel):
    gender: Optional[Gender] = None
    city: Optional[str] = None
    country: Optional[str] = None

    limit: Optional[int] = 15
    offset: Optional[int] = 0

    @root_validator(pre=True)
    def validate_params(cls, values: dict):
        if values.get('city') and not values.get('country'):
            raise ValueError("Either none of both city and country must be set")
        return values


class OnlineFilterBody(BaseModel):
    session_id: Optional[str] = ''

    country: Optional[str] = None
    city: Optional[str] = None
    gender: Optional[Gender] = None
    limit: Optional[int] = 15


class UserOutGlobalChatPreviewORM(BaseModel):
    id: UUID
    name: str
    avatar_id: Optional[str] = None
    avatar_url: Optional[str] = None

    class Config:
        orm_mode = True


class UserOutChatPreviewORM(BaseModel):
    id: UUID
    name: str
    photos: list[str] = []
    # None if he is online
    last_online: Optional[datetime.datetime] = None
    location: Optional[LocationSchema] = None

    class Config:
        # allows Pydantic to read orm models and not just dicts
        orm_mode = True


class UserOutChatPreview(BaseModel):
    id: UUID
    name: str
    online: bool = False
    # None if he is online
    last_online: Optional[datetime.datetime] = None
    photo_url: Optional[str] = None
    location: Optional[LocationSchema] = None

    @classmethod
    def patched_from_orm(cls: UserOutChatPreview,
                         obj: User) -> UserOutChatPreview:
        orm_schema = UserOutChatPreviewORM.from_orm(obj)
        schema_obj = cls.parse_obj(orm_schema)
        if orm_schema.photos:
            photo_id = orm_schema.photos[0]
            schema_obj.photo_url = obj.photo_url(photo_id)
        return schema_obj
