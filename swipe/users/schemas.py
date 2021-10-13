from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from .models import UserInterests, Gender


class UserBase(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = Field(
        None, title="User's bio", max_length=200
    )
    height: Optional[int]

    photos: list[str] = []
    interests: list[UserInterests] = []
    gender: Optional[Gender] = None


class UserOut(UserBase):
    id: UUID
    rating: int
    is_premium: bool

    class Config:
        # allows Pydantic to read orm models and not just dicts
        orm_mode = True


class UserIn(UserBase):
    pass
