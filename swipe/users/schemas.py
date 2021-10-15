from __future__ import annotations

from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, Field, validator

from swipe.storage import CloudStorage
from .enums import UserInterests, Gender, AuthProvider


class UserBase(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = Field(
        None, title="User's bio", max_length=200
    )
    height: Optional[int]

    interests: list[UserInterests] = []
    gender: Optional[Gender] = None


class UserOut(UserBase):
    id: UUID
    photos: list[str] = []

    rating: int
    is_premium: bool

    @classmethod
    def patched_from_orm(cls: UserOut, obj: Any) -> UserOut:
        schema_obj = cls.from_orm(obj)
        # TODO make it a dependency or smth
        storage = CloudStorage()
        patched_photos = []
        for photo_id in schema_obj.photos:
            # TODO add a url shortener cuz these urls a freaking looong
            # and include auth info
            patched_photos.append(storage.get_image_url(photo_id))
        schema_obj.photos = patched_photos
        return schema_obj

    class Config:
        # allows Pydantic to read orm models and not just dicts
        orm_mode = True


class UserIn(UserBase):
    pass


class CreateUserIn(BaseModel):
    auth_provider: AuthProvider
    provider_token: str
    provider_user_id: str


class CreateUserOut(BaseModel):
    user_id: UUID
    access_token: str


class JWTPayload(CreateUserIn):
    user_id: UUID
    created_at: int

    @validator("user_id")
    def cast_user_id(cls, value: UUID,
                     values: dict[str, Any]) -> Any:
        return str(value)
