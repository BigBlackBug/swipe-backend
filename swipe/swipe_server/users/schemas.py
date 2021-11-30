from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, Field, validator, root_validator
from sqlalchemy.engine import Row

from swipe.swipe_server.misc.storage import storage_client
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
    date_of_birth: datetime.date
    rating: int
    location: LocationSchema
    photos: Optional[list[str]] = []
    photo_urls: Optional[list[str]] = []

    @classmethod
    def patched_from_orm(cls: UserOut, obj: Any) -> UserOut:
        schema_obj = cls.from_orm(obj)
        patched_photos = []
        for photo_id in schema_obj.photos:
            patched_photos.append(storage_client.get_image_url(photo_id))
        schema_obj.photo_urls = patched_photos
        return schema_obj

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

    @classmethod
    def patched_from_orm(cls: UserOut, obj: Any) -> UserOut:
        schema_obj = cls.from_orm(obj)
        patched_photos = []
        for photo_id in schema_obj.photos:
            patched_photos.append(storage_client.get_image_url(photo_id))
        schema_obj.photo_urls = patched_photos

        if schema_obj.avatar_id:
            schema_obj.avatar_url = \
                storage_client.get_image_url(schema_obj.avatar_id)
        return schema_obj

    class Config:
        # allows Pydantic to read orm models and not just dicts
        orm_mode = True


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
    user_id: UUID
    created_at: int

    @validator("user_id")
    def cast_user_id(cls, value: UUID,
                     values: dict[str, Any]) -> Any:
        return str(value)


class PopularFilterBody(BaseModel):
    limit: Optional[int] = 15
    offset: Optional[int] = 0
    gender: Optional[Gender] = None
    city: Optional[str] = None
    country: str


class OnlineFilterBody(BaseModel):
    session_id: str

    country: Optional[str] = None
    city: Optional[str] = None
    gender: Optional[Gender] = None
    limit: Optional[int] = 15


class UserOutChatPreviewORM(BaseModel):
    id: UUID
    name: str
    photos: list[str] = []
    last_online: datetime.datetime
    location: Optional[LocationSchema] = Field(None, alias='Location')

    class Config:
        # allows Pydantic to read orm models and not just dicts
        orm_mode = True


class UserOutGlobalChatPreviewORM(BaseModel):
    id: UUID
    name: str
    avatar_id: Optional[str] = None
    avatar_url: Optional[str] = None

    @classmethod
    def patched_from_orm(cls: UserOutGlobalChatPreviewORM,
                         obj: User | Row) -> UserOutGlobalChatPreviewORM:
        orm_schema = UserOutGlobalChatPreviewORM.from_orm(obj)
        schema_obj = cls.parse_obj(orm_schema)
        if schema_obj.avatar_id:
            schema_obj.avatar_url = \
                storage_client.get_image_url(schema_obj.avatar_id)
        return schema_obj

    class Config:
        orm_mode = True


class UserOutChatPreview(BaseModel):
    id: UUID
    name: str
    last_online: datetime.datetime
    photo_url: Optional[str] = None
    location: Optional[LocationSchema] = None
    # filled later
    online: Optional[bool] = None

    @classmethod
    def patched_from_orm(cls: UserOutChatPreview,
                         obj: User | Row) -> UserOutChatPreview:
        orm_schema = UserOutChatPreviewORM.from_orm(obj)
        schema_obj = cls.parse_obj(orm_schema)
        if orm_schema.photos:
            photo = orm_schema.photos[0]
            schema_obj.photo_url = storage_client.get_image_url(photo)
        return schema_obj
