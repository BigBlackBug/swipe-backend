from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, Field, validator

from .models import UserInterests, Gender


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
    # TODO add a validator which fetches proper image urls
    # TODO or a separate endpoint which redirects to S3
    photos: list[str] = []

    rating: int
    is_premium: bool

    class Config:
        # allows Pydantic to read orm models and not just dicts
        orm_mode = True


class UserIn(UserBase):
    pass


class CreateUserIn(BaseModel):
    auth_provider: str
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
