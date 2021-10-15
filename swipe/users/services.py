import time
import uuid
from typing import Optional
from uuid import UUID

from fastapi import Depends, UploadFile
from jose import jwt
from jose.constants import ALGORITHMS
from sqlalchemy import select
from sqlalchemy.orm import Session

import swipe.database
from settings import settings
from swipe.storage import CloudStorage
from swipe.users import schemas, models


class UserService:
    def __init__(self, db: Session = Depends(swipe.database.db)):
        self.db = db
        self._storage = CloudStorage()

    def create_user(self,
                    user_payload: schemas.AuthenticationIn) -> models.User:
        auth_info = models.AuthInfo(**user_payload.dict())
        user_object = models.User()
        user_object.auth_info = auth_info

        self.db.add(auth_info)
        self.db.add(user_object)
        self.db.commit()
        self.db.refresh(user_object)
        return user_object

    def get_user(self, user_id: UUID) -> models.User:
        return self.db.execute(
            select(models.User).where(models.User.id == user_id)) \
            .scalar_one_or_none()

    def get_users(self) -> list[models.User]:
        return self.db.execute(select(models.User)).scalars().all()

    def update_user(
            self,
            user_object: models.User,
            user: schemas.UserUpdate) -> models.User:
        # TODO think of a way to update photos EZ
        for k, v in user.dict(exclude_unset=True).items():
            setattr(user_object, k, v)
        self.db.commit()
        self.db.refresh(user_object)
        return user_object

    def add_photo(self, user_object: models.User, file: UploadFile):
        _, _, extension = file.content_type.partition('/')
        image_id = f'{uuid.uuid4()}.{extension}'
        self._storage.upload_image(image_id, file.file)

        user_object.photos = user_object.photos + [image_id]
        self.db.commit()
        return image_id

    def delete_photo(self, user_object: models.User, photo_id: UUID):
        new_list = list(user_object.photos)
        new_list.remove(photo_id)
        user_object.photos = new_list

        self._storage.delete_image(photo_id)
        self.db.commit()

    def find_user_by_auth(
            self,
            user_payload: schemas.AuthenticationIn) -> Optional[models.User]:
        auth_info = self.db.execute(
            select(models.AuthInfo)
                .where(models.AuthInfo.auth_provider
                       == user_payload.auth_provider)
                .where(models.AuthInfo.provider_user_id
                       == user_payload.provider_user_id)) \
            .scalar_one_or_none()
        # TODO check queries for extra joins
        return auth_info.user if auth_info else None

    def create_access_token(self, user_object: models.User,
                            payload: schemas.AuthenticationIn) -> str:
        access_token = jwt.encode(
            schemas.JWTPayload(
                **payload.dict(),
                user_id=user_object.id,
                created_at=time.time_ns()
            ).dict(),
            settings.SWIPE_SECRET_KEY, algorithm=ALGORITHMS.HS256)

        user_object.auth_info.access_token = access_token
        self.db.commit()
        return access_token
